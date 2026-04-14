from __future__ import annotations

import importlib.util
import hashlib
import json
import math
import random
from typing import Any, Dict, List

import networkx as nx

from traffic_simulator.domain import DemandProfile, RoadEdge, RoadNode, TrafficNetwork, TripRequest

CITY_INPUT_FEEDS = [
    "Traffic light statuses",
    "Vehicle counters",
    "Traffic cameras",
    "Average vehicle speeds",
    "Police incident reports",
]


def _stable_token(*parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def _edge_orientation(a: RoadNode, b: RoadNode) -> str:
    return "horizontal" if abs(a.x - b.x) >= abs(a.y - b.y) else "vertical"


def build_synthetic_grid(rows: int = 4, cols: int = 4, seed: int = 1, spacing: float = 1.0) -> TrafficNetwork:
    network_id = f"net-{_stable_token('synthetic', rows, cols, seed, spacing)}"
    nodes: Dict[str, RoadNode] = {}
    edges: Dict[str, RoadEdge] = {}
    for row in range(rows):
        for col in range(cols):
            node_id = f"{network_id}-n-{row}-{col}"
            nodes[node_id] = RoadNode(id=node_id, x=col * spacing, y=row * spacing)
    for row in range(rows):
        for col in range(cols):
            here = nodes[f"{network_id}-n-{row}-{col}"]
            if col + 1 < cols:
                right = nodes[f"{network_id}-n-{row}-{col+1}"]
                _add_bidirectional_edge(edges, here, right)
            if row + 1 < rows:
                down = nodes[f"{network_id}-n-{row+1}-{col}"]
                _add_bidirectional_edge(edges, here, down)
    return TrafficNetwork(
        id=network_id,
        name=f"synthetic-grid-{rows}x{cols}",
        version=1,
        source_type="synthetic",
        nodes=nodes,
        edges=edges,
        metadata={"rows": rows, "cols": cols, "seed": seed, "city_inputs": CITY_INPUT_FEEDS},
    )


def _add_bidirectional_edge(edges: Dict[str, RoadEdge], a: RoadNode, b: RoadNode, speed_limit_mps: float = 13.4) -> None:
    for source, target in ((a, b), (b, a)):
        edge_id = f"e-{source.id}-{target.id}"
        edges[edge_id] = RoadEdge(
            id=edge_id,
            source=source.id,
            target=target.id,
            orientation=_edge_orientation(source, target),
            length_m=120.0,
            speed_limit_mps=speed_limit_mps,
            lane_count=1,
            capacity_vph=900.0,
            geometry=[(source.x, source.y), (target.x, target.y)],
        )


def load_osm_network(name: str, place_query: str) -> TrafficNetwork:
    if importlib.util.find_spec("osmnx") is None:
        raise RuntimeError("Real neighborhood import is not available yet because the optional map import package is not installed.")
    import osmnx as ox

    center = ox.geocode(place_query)
    graph = ox.graph_from_point(center, dist=1200, network_type="drive")
    graph = _compact_osm_graph(graph, center)
    graph = ox.project_graph(graph, to_crs="EPSG:4326")
    network_id = f"net-{_stable_token('osm', place_query.strip().lower())}"
    nodes: Dict[str, RoadNode] = {}
    edges: Dict[str, RoadEdge] = {}
    for node_id, data in graph.nodes(data=True):
        prefixed_id = f"{network_id}-n-{node_id}"
        node_highway = data.get("highway")
        control_type = "signal" if node_highway == "traffic_signals" else "priority"
        nodes[prefixed_id] = RoadNode(
            id=prefixed_id,
            x=float(data["x"]),
            y=float(data["y"]),
            control_type=control_type,
            metadata={"street_count": data.get("street_count", 0), "highway": node_highway},
        )
    for source, target, key, data in graph.edges(keys=True, data=True):
        source_id = f"{network_id}-n-{source}"
        target_id = f"{network_id}-n-{target}"
        source_node = nodes[source_id]
        target_node = nodes[target_id]
        geometry = data.get("geometry")
        if geometry is None:
            coords = [(source_node.x, source_node.y), (target_node.x, target_node.y)]
        else:
            coords = [(float(x), float(y)) for x, y in geometry.coords]
        edge_id = f"{network_id}-e-{source}-{target}-{key}"
        speed_kph = data.get("speed_kph") or data.get("maxspeed") or 40
        if isinstance(speed_kph, list):
            speed_kph = speed_kph[0]
        try:
            speed_kph = float(str(speed_kph).split()[0])
        except ValueError:
            speed_kph = 40.0
        edges[edge_id] = RoadEdge(
            id=edge_id,
            source=source_id,
            target=target_id,
            orientation=_edge_orientation(source_node, target_node),
            length_m=float(data.get("length", 80.0)),
            speed_limit_mps=max(5.0, speed_kph / 3.6),
            lane_count=int(data.get("lanes", 1) if str(data.get("lanes", "1")).isdigit() else 1),
            capacity_vph=900.0,
            geometry=coords,
            metadata={"osmid": data.get("osmid")},
        )
    return TrafficNetwork(
        id=network_id,
        name=name,
        version=1,
        source_type="osm",
        nodes=nodes,
        edges=edges,
        metadata={"place_query": place_query, "city_inputs": CITY_INPUT_FEEDS},
    )


def build_graph(network: TrafficNetwork, travel_time_overrides: Dict[str, float] | None = None) -> nx.DiGraph:
    graph = nx.DiGraph()
    for node in network.nodes.values():
        graph.add_node(node.id)
    overrides = travel_time_overrides or {}
    for edge in network.edges.values():
        if not edge.enabled:
            continue
        graph.add_edge(
            edge.source,
            edge.target,
            edge_id=edge.id,
            weight=float(overrides.get(edge.id, edge.base_travel_time_s)),
        )
    return graph


def generate_demand_profile(
    network: TrafficNetwork,
    seed: int = 1,
    horizon_s: int | None = None,
    trip_count: int | None = None,
    traffic_scale: float = 1.0,
) -> DemandProfile:
    rng = random.Random(seed)
    horizon_s = horizon_s if horizon_s is not None else _default_demand_horizon(network)
    trip_count = trip_count if trip_count is not None else _default_trip_count(network, traffic_scale)
    boundary_nodes = network.boundary_nodes()
    hotspot_candidates = sorted(
        network.nodes.values(),
        key=lambda node: math.dist((node.x, node.y), _network_center(network)),
    )
    hotspots = [node.id for node in hotspot_candidates[: max(2, len(hotspot_candidates) // 5)]]
    boundary_ids = [node.id for node in boundary_nodes]
    graph = build_graph(network)
    trips: List[TripRequest] = []
    bus_lines = _build_bus_lines(network, graph)
    if network.source_type == "osm":
        trips.extend(_generate_osm_car_trips(network, graph, rng, trip_count, horizon_s))
    else:
        for idx in range(trip_count):
            departure_s = int(rng.triangular(0, horizon_s - 1, horizon_s * 0.55))
            if idx % 5 == 0:
                origin = rng.choice(hotspots)
                destination = rng.choice(boundary_ids)
            else:
                origin = rng.choice(boundary_ids)
                destination = rng.choice(hotspots)
            if origin == destination:
                destination = rng.choice([node_id for node_id in boundary_ids + hotspots if node_id != origin])
            if not nx.has_path(graph, origin, destination):
                continue
            trips.append(
                TripRequest(
                    id=f"trip-{idx}",
                    origin=origin,
                    destination=destination,
                    departure_s=departure_s,
                    vehicle_type="car",
                )
            )
    bus_trip_index = len(trips)
    for line_index, line in enumerate(bus_lines):
        for direction_index, (origin, destination) in enumerate(((line["origin"], line["destination"]), (line["destination"], line["origin"]))):
            for departure_s in range(line["offset_s"] + direction_index * (line["headway_s"] // 2), horizon_s, line["headway_s"]):
                if not nx.has_path(graph, origin, destination):
                    continue
                trips.append(
                    TripRequest(
                        id=f"trip-bus-{bus_trip_index}",
                        origin=origin,
                        destination=destination,
                        departure_s=departure_s,
                        vehicle_type="bus",
                        route_name=line["name"],
                    )
                )
                bus_trip_index += 1
    return DemandProfile(
        id=f"demand-{_stable_token(network.id, seed, horizon_s, trip_count, round(traffic_scale, 3))}",
        name="rush-hour-weighted",
        seed=seed,
        horizon_s=horizon_s,
        trips=sorted(trips, key=lambda trip: trip.departure_s),
        metadata={
            "hotspots": hotspots,
            "boundary_nodes": boundary_ids,
            "bus_lines": bus_lines,
            "city_inputs": network.metadata.get("city_inputs", CITY_INPUT_FEEDS),
            "traffic_scale": traffic_scale,
        },
    )


def _network_center(network: TrafficNetwork) -> tuple[float, float]:
    xs = [node.x for node in network.nodes.values()]
    ys = [node.y for node in network.nodes.values()]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _compact_osm_graph(graph: nx.MultiDiGraph, center: tuple[float, float]) -> nx.MultiDiGraph:
    if graph.number_of_nodes() <= 140:
        return graph
    center_lat, center_lon = center
    center_node = min(
        graph.nodes,
        key=lambda node_id: math.dist(
            (float(graph.nodes[node_id].get("x", 0.0)), float(graph.nodes[node_id].get("y", 0.0))),
            (float(center_lon), float(center_lat)),
        ),
    )
    undirected = graph.to_undirected(as_view=False)
    chosen = None
    for radius_m in (850, 700, 550, 425):
        ego = nx.ego_graph(undirected, center_node, radius=radius_m, distance="length")
        if ego.number_of_nodes() >= 20:
            chosen = ego
        if 20 <= ego.number_of_nodes() <= 140:
            chosen = ego
            break
    if chosen is None:
        return graph
    compact = graph.subgraph(chosen.nodes()).copy()
    if compact.number_of_nodes() < 10:
        return graph
    if not nx.is_weakly_connected(compact):
        largest_component = max(nx.weakly_connected_components(compact), key=len)
        compact = compact.subgraph(largest_component).copy()
    return compact


def _generate_osm_car_trips(
    network: TrafficNetwork,
    graph: nx.DiGraph,
    rng: random.Random,
    trip_count: int,
    horizon_s: int,
) -> List[TripRequest]:
    navigable_nodes = _navigable_node_ids(graph)
    if len(navigable_nodes) < 2:
        return []
    center = _network_center(network)
    activity_nodes = sorted(
        navigable_nodes,
        key=lambda node_id: math.dist((network.nodes[node_id].x, network.nodes[node_id].y), center),
    )[: max(8, len(navigable_nodes) // 6)]
    boundary_ids = [node.id for node in network.boundary_nodes() if node.id in navigable_nodes] or navigable_nodes
    successors = {
        node_id: [target for target in graph.successors(node_id) if target in navigable_nodes]
        for node_id in navigable_nodes
    }
    local_min_steps = 2 if len(navigable_nodes) <= 90 else 3
    local_max_steps = 6 if len(navigable_nodes) <= 90 else 8
    car_trips: List[TripRequest] = []
    for idx in range(trip_count):
        departure_s = int(rng.triangular(0, horizon_s - 1, horizon_s * 0.55))
        mode_roll = rng.random()
        if mode_roll < 0.72:
            origin_pool = activity_nodes if rng.random() < 0.58 else navigable_nodes
            origin = rng.choice(origin_pool)
            destination = _random_walk_destination(origin, successors, rng, local_min_steps, local_max_steps)
        elif mode_roll < 0.9:
            origin = rng.choice(boundary_ids if rng.random() < 0.55 else activity_nodes)
            destination = rng.choice(activity_nodes if origin in boundary_ids else boundary_ids)
        else:
            origin = rng.choice(navigable_nodes)
            destination = _random_walk_destination(origin, successors, rng, local_min_steps + 2, local_max_steps + 3)
        if origin == destination:
            destination = rng.choice([node_id for node_id in navigable_nodes if node_id != origin])
        try:
            travel_time_s = nx.shortest_path_length(graph, origin, destination, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if travel_time_s > 110:
            destination = _random_walk_destination(origin, successors, rng, local_min_steps, local_max_steps)
            if destination == origin:
                continue
            try:
                travel_time_s = nx.shortest_path_length(graph, origin, destination, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
        if travel_time_s < 18:
            destination = _random_walk_destination(origin, successors, rng, local_min_steps + 1, local_max_steps + 1)
            if destination == origin:
                continue
            try:
                travel_time_s = nx.shortest_path_length(graph, origin, destination, weight="weight")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
        if travel_time_s <= 0:
            continue
        car_trips.append(
            TripRequest(
                id=f"trip-{idx}",
                origin=origin,
                destination=destination,
                departure_s=departure_s,
                vehicle_type="car",
            )
        )
    return car_trips


def _navigable_node_ids(graph: nx.DiGraph) -> List[str]:
    if not graph.nodes:
        return []
    try:
        component = max(nx.strongly_connected_components(graph), key=len)
    except ValueError:
        return list(graph.nodes)
    return list(component) if len(component) >= 2 else list(graph.nodes)


def _random_walk_destination(
    origin: str,
    successors: Dict[str, List[str]],
    rng: random.Random,
    min_steps: int,
    max_steps: int,
) -> str:
    steps = rng.randint(min_steps, max_steps)
    current = origin
    for _ in range(steps):
        options = successors.get(current) or []
        if not options:
            break
        current = rng.choice(options)
    return current


def _fallback_bus_pair(network: TrafficNetwork, graph: nx.DiGraph, axis: str) -> tuple[str, str] | None:
    navigable_nodes = _navigable_node_ids(graph)
    if len(navigable_nodes) < 2:
        return None
    center_x, center_y = _network_center(network)
    candidates = [
        network.nodes[node_id]
        for node_id in navigable_nodes
        if network.nodes[node_id].metadata.get("street_count", 0) >= 2
    ] or [network.nodes[node_id] for node_id in navigable_nodes]
    if len(candidates) < 2:
        return None
    band_size = max(6, min(18, len(candidates) // 4))
    if axis == "x":
        origin_band = sorted(candidates, key=lambda node: (node.x, abs(node.y - center_y), -node.metadata.get("street_count", 0)))[:band_size]
        destination_band = sorted(candidates, key=lambda node: (-node.x, abs(node.y - center_y), -node.metadata.get("street_count", 0)))[:band_size]
        span = lambda a, b: abs(a.x - b.x)
    else:
        origin_band = sorted(candidates, key=lambda node: (-node.y, abs(node.x - center_x), -node.metadata.get("street_count", 0)))[:band_size]
        destination_band = sorted(candidates, key=lambda node: (node.y, abs(node.x - center_x), -node.metadata.get("street_count", 0)))[:band_size]
        span = lambda a, b: abs(a.y - b.y)
    best_pair = None
    best_span = -1.0
    for origin_node in origin_band:
        for destination_node in destination_band:
            if origin_node.id == destination_node.id:
                continue
            if not nx.has_path(graph, origin_node.id, destination_node.id):
                continue
            candidate_span = span(origin_node, destination_node)
            if candidate_span > best_span:
                best_pair = (origin_node.id, destination_node.id)
                best_span = candidate_span
    return best_pair


def _build_bus_lines(network: TrafficNetwork, graph: nx.DiGraph) -> List[Dict[str, Any]]:
    terminals = _cardinal_terminals(network)
    candidates = [
        ("Crosstown Line", terminals["west"], terminals["east"], 70, 18),
        ("North-South Line", terminals["north"], terminals["south"], 85, 44),
    ]
    bus_lines: List[Dict[str, Any]] = []
    for name, origin, destination, headway_s, offset_s in candidates:
        if origin == destination:
            continue
        if not nx.has_path(graph, origin, destination):
            continue
        bus_lines.append(
            {
                "name": name,
                "origin": origin,
                "destination": destination,
                "headway_s": headway_s,
                "offset_s": offset_s,
            }
        )
    if not bus_lines and network.source_type == "osm":
        fallback_pairs = [
            ("Crosstown Line", _fallback_bus_pair(network, graph, axis="x"), 80, 18),
            ("North-South Line", _fallback_bus_pair(network, graph, axis="y"), 95, 44),
        ]
        for name, pair, headway_s, offset_s in fallback_pairs:
            if not pair:
                continue
            origin, destination = pair
            bus_lines.append(
                {
                    "name": name,
                    "origin": origin,
                    "destination": destination,
                    "headway_s": headway_s,
                    "offset_s": offset_s,
                }
            )
    return bus_lines


def _default_demand_horizon(network: TrafficNetwork) -> int:
    return 240 if network.source_type == "osm" else 300


def _default_trip_count(network: TrafficNetwork, traffic_scale: float) -> int:
    enabled_edges = len([edge for edge in network.edges.values() if edge.enabled])
    if network.source_type == "osm":
        base = max(360, min(900, int(enabled_edges * 0.55)))
    else:
        base = 260
    return max(120, int(round(base * traffic_scale)))


def _cardinal_terminals(network: TrafficNetwork) -> Dict[str, str]:
    center_x, center_y = _network_center(network)
    nodes = list(network.nodes.values())
    return {
        "west": min(nodes, key=lambda node: (node.x, abs(node.y - center_y))).id,
        "east": max(nodes, key=lambda node: (node.x, -abs(node.y - center_y))).id,
        "north": max(nodes, key=lambda node: (node.y, -abs(node.x - center_x))).id,
        "south": min(nodes, key=lambda node: (node.y, abs(node.x - center_x))).id,
    }
