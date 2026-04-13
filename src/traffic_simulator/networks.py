from __future__ import annotations

import importlib.util
import math
import random
import uuid
from typing import Any, Dict, List

import networkx as nx

from traffic_simulator.domain import DemandProfile, RoadEdge, RoadNode, TrafficNetwork, TripRequest


def _edge_orientation(a: RoadNode, b: RoadNode) -> str:
    return "horizontal" if abs(a.x - b.x) >= abs(a.y - b.y) else "vertical"


def build_synthetic_grid(rows: int = 4, cols: int = 4, seed: int = 1, spacing: float = 1.0) -> TrafficNetwork:
    network_id = f"net-{uuid.uuid4().hex[:10]}"
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
        metadata={"rows": rows, "cols": cols, "seed": seed},
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
    graph = ox.project_graph(graph, to_crs="EPSG:4326")
    network_id = f"net-{uuid.uuid4().hex[:10]}"
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
        metadata={"place_query": place_query},
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


def generate_demand_profile(network: TrafficNetwork, seed: int = 1, horizon_s: int = 600, trip_count: int = 260) -> DemandProfile:
    rng = random.Random(seed)
    boundary_nodes = network.boundary_nodes()
    hotspot_candidates = sorted(
        network.nodes.values(),
        key=lambda node: math.dist((node.x, node.y), _network_center(network)),
    )
    hotspots = [node.id for node in hotspot_candidates[: max(2, len(hotspot_candidates) // 5)]]
    boundary_ids = [node.id for node in boundary_nodes]
    graph = build_graph(network)
    trips: List[TripRequest] = []
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
        trips.append(TripRequest(id=f"trip-{idx}", origin=origin, destination=destination, departure_s=departure_s))
    return DemandProfile(
        id=f"demand-{uuid.uuid4().hex[:10]}",
        name="rush-hour-weighted",
        seed=seed,
        horizon_s=horizon_s,
        trips=sorted(trips, key=lambda trip: trip.departure_s),
        metadata={"hotspots": hotspots, "boundary_nodes": boundary_ids},
    )


def _network_center(network: TrafficNetwork) -> tuple[float, float]:
    xs = [node.x for node in network.nodes.values()]
    ys = [node.y for node in network.nodes.values()]
    return (sum(xs) / len(xs), sum(ys) / len(ys))
