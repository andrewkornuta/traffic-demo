from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations
import json
import re
from typing import Any, Dict, List

import networkx as nx

from traffic_simulator.domain import DemandProfile, Mutation, ScenarioProposal, TrafficNetwork, TripRequest
from traffic_simulator.networks import build_graph


ALLOWED_MUTATIONS = {
    "replace_signal_with_roundabout",
    "add_connector",
    "remove_connector",
    "close_edge",
    "change_speed_limit",
    "change_lane_count",
    "change_signal_plan",
    "increase_bus_service",
    "build_light_rail_line",
}


def _stable_scenario_id(
    network: TrafficNetwork,
    title: str,
    intent: str,
    objective: str,
    mutations: List[Mutation],
) -> str:
    digest = hashlib.sha1(
        json.dumps(
            {
                "network_id": network.id,
                "title": title,
                "intent": intent,
                "objective": objective,
                "mutations": [{"mutation_type": mutation.mutation_type, "params": mutation.params} for mutation in mutations],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"scenario-{digest}"


def validate_mutations(network: TrafficNetwork, mutations: List[Mutation]) -> None:
    for mutation in mutations:
        if mutation.mutation_type not in ALLOWED_MUTATIONS:
            raise ValueError(f"Unsupported mutation type: {mutation.mutation_type}")
        params = mutation.params
        if mutation.mutation_type == "replace_signal_with_roundabout":
            node_id = params.get("node_id")
            if node_id not in network.nodes:
                raise ValueError(f"Unknown node_id: {node_id}")
        if mutation.mutation_type in {"close_edge", "change_speed_limit", "change_lane_count", "remove_connector"}:
            edge_id = params.get("edge_id")
            if edge_id not in network.edges:
                raise ValueError(f"Unknown edge_id: {edge_id}")
        if mutation.mutation_type == "add_connector":
            for field_name in ("source", "target"):
                if params.get(field_name) not in network.nodes:
                    raise ValueError(f"Unknown {field_name}: {params.get(field_name)}")
        if mutation.mutation_type in {"increase_bus_service", "build_light_rail_line"}:
            for field_name in ("origin", "destination"):
                if params.get(field_name) not in network.nodes:
                    raise ValueError(f"Unknown {field_name}: {params.get(field_name)}")
        if mutation.mutation_type == "change_lane_count" and int(params.get("lane_count", 0)) < 1:
            raise ValueError("lane_count must be >= 1")


def apply_scenario(network: TrafficNetwork, proposal: ScenarioProposal) -> TrafficNetwork:
    validate_mutations(network, proposal.mutations)
    mutated = network.copy(version=network.version + 1)
    for mutation in proposal.mutations:
        params = mutation.params
        if mutation.mutation_type == "replace_signal_with_roundabout":
            mutated.nodes[params["node_id"]].control_type = "roundabout"
        elif mutation.mutation_type == "close_edge":
            mutated.edges[params["edge_id"]].enabled = False
        elif mutation.mutation_type == "change_speed_limit":
            mutated.edges[params["edge_id"]].speed_limit_mps = float(params["speed_limit_mps"])
        elif mutation.mutation_type == "change_lane_count":
            edge = mutated.edges[params["edge_id"]]
            edge.lane_count = int(params["lane_count"])
            edge.capacity_vph = 900.0 * edge.lane_count
        elif mutation.mutation_type == "add_connector":
            source = mutated.nodes[params["source"]]
            target = mutated.nodes[params["target"]]
            edge_id = params.get("edge_id", f"e-{source.id}-{target.id}-custom")
            orientation = "horizontal" if abs(source.x - target.x) >= abs(source.y - target.y) else "vertical"
            mutated.edges[edge_id] = mutated.edges.get(edge_id) or type(next(iter(mutated.edges.values())))(
                id=edge_id,
                source=source.id,
                target=target.id,
                orientation=orientation,
                length_m=float(params.get("length_m", 90.0)),
                speed_limit_mps=float(params.get("speed_limit_mps", 13.4)),
                lane_count=int(params.get("lane_count", 1)),
                capacity_vph=900.0 * int(params.get("lane_count", 1)),
                geometry=[(source.x, source.y), (target.x, target.y)],
            )
        elif mutation.mutation_type == "remove_connector":
            mutated.edges[params["edge_id"]].enabled = False
        elif mutation.mutation_type == "change_signal_plan":
            node_id = params["node_id"]
            mutated.nodes[node_id].metadata["signal_override"] = params
        elif mutation.mutation_type == "increase_bus_service":
            overlay = _build_transit_overlay(
                mutated,
                params["origin"],
                params["destination"],
                line_name=params.get("line_name", "Express Bus Service"),
                overlay_type="bus",
                color="#22D3EE",
            )
            mutated.metadata.setdefault("transit_overlays", []).append(overlay)
        elif mutation.mutation_type == "build_light_rail_line":
            overlay = _build_transit_overlay(
                mutated,
                params["origin"],
                params["destination"],
                line_name=params.get("line_name", "Light Rail Link"),
                overlay_type="rail",
                color="#F59E0B",
            )
            mutated.metadata.setdefault("transit_overlays", []).append(overlay)
    mutated.metadata["scenario_id"] = proposal.id
    return mutated


def apply_demand_changes(network: TrafficNetwork, demand_profile: DemandProfile, proposal: ScenarioProposal | None) -> DemandProfile:
    if proposal is None:
        return demand_profile
    adjusted = DemandProfile(
        id=f"{demand_profile.id}-{proposal.id}",
        name=demand_profile.name,
        seed=demand_profile.seed,
        horizon_s=demand_profile.horizon_s,
        trips=[TripRequest(**trip.__dict__) for trip in demand_profile.trips],
        metadata=deepcopy(demand_profile.metadata),
    )
    adjusted.metadata.setdefault("mode_shift_removed_cars", 0)
    adjusted.metadata.setdefault("rail_riders_served", 0)
    adjusted.metadata.setdefault("transit_overlays", [])
    graph = build_graph(network)
    for mutation in proposal.mutations:
        params = mutation.params
        if mutation.mutation_type == "increase_bus_service":
            extra_bus_trips = _build_service_trips(
                graph,
                adjusted.horizon_s,
                origin=params["origin"],
                destination=params["destination"],
                headway_s=int(params.get("headway_s", 55)),
                route_name=params.get("line_name", "Express Bus Service"),
                trip_prefix=f"trip-bus-boost-{proposal.id}",
            )
            adjusted.trips.extend(extra_bus_trips)
            adjusted.metadata.setdefault("bus_lines", []).append(
                {
                    "name": params.get("line_name", "Express Bus Service"),
                    "origin": params["origin"],
                    "destination": params["destination"],
                    "headway_s": int(params.get("headway_s", 55)),
                    "offset_s": int(params.get("offset_s", 16)),
                    "boosted": True,
                }
            )
            adjusted.trips, removed = _remove_car_trips_for_mode_shift(
                adjusted.trips,
                preferred_nodes={params["origin"], params["destination"], *adjusted.metadata.get("hotspots", [])},
                fraction=0.08,
                minimum=8,
            )
            adjusted.metadata["mode_shift_removed_cars"] += removed
        elif mutation.mutation_type == "build_light_rail_line":
            adjusted.trips, removed = _remove_car_trips_for_mode_shift(
                adjusted.trips,
                preferred_nodes={params["origin"], params["destination"], *adjusted.metadata.get("hotspots", [])},
                fraction=0.14,
                minimum=14,
            )
            adjusted.metadata["mode_shift_removed_cars"] += removed
            adjusted.metadata["rail_riders_served"] += removed
    adjusted.trips = sorted(adjusted.trips, key=lambda trip: trip.departure_s)
    return adjusted


def parse_proposal_text(text: str, network: TrafficNetwork, demand_profile: DemandProfile) -> ScenarioProposal:
    lowered = text.lower()
    hotspots = demand_profile.metadata.get("hotspots", [])
    hotspot = hotspots[0] if hotspots else sorted(network.nodes)[0]
    target_node_id = _choose_target_node(network, hotspot)
    mutations: List[Mutation] = []
    title = "Structured scenario proposal"
    objective = "avg_travel_time_s"
    if "throughput" in lowered:
        objective = "throughput"
    if "roundabout" in lowered:
        mutations.append(Mutation("replace_signal_with_roundabout", {"node_id": target_node_id}))
        title = "Roundabout at hotspot"
    if re.search(r"(more buses|buy buses|purchase buses|add buses|increase bus service|bus line|express bus)", lowered):
        origin, destination = _choose_corridor_nodes(network)
        mutations.append(
            Mutation(
                "increase_bus_service",
                {
                    "origin": origin,
                    "destination": destination,
                    "headway_s": 55,
                    "offset_s": 16,
                    "line_name": "Express Bus Upgrade",
                },
            )
        )
        title = "Extra bus service on the busiest corridor"
        objective = "people_moved"
    if re.search(r"(light rail|rail line|commuter rail|train line|tram)", lowered):
        origin, destination = _choose_corridor_nodes(network)
        mutations.append(
            Mutation(
                "build_light_rail_line",
                {
                    "origin": origin,
                    "destination": destination,
                    "line_name": "New Light Rail Link",
                },
            )
        )
        title = "Light rail corridor proposal"
        objective = "people_moved"
    if "close" in lowered and "road" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("close_edge", {"edge_id": edge_id}))
        title = "Close connector near hotspot"
    connector_match = re.search(r"connector|ramp|link", lowered)
    if connector_match:
        source, target = _choose_connector_nodes(network)
        lane_count = 2 if re.search(r"ramp|highway|off-ramp|on-ramp", lowered) else 1
        speed_limit_mps = 22.0 if lane_count == 2 else 16.0
        mutations.append(
            Mutation(
                "add_connector",
                {
                    "source": source,
                    "target": target,
                    "lane_count": lane_count,
                    "length_m": 100.0,
                    "speed_limit_mps": speed_limit_mps,
                },
            )
        )
        title = "Ramp or connector proposal"
    if "lane" in lowered and "more" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("change_lane_count", {"edge_id": edge_id, "lane_count": 2}))
    if "bus" in lowered and "priority" in lowered:
        mutations.append(Mutation("change_signal_plan", {"node_id": target_node_id, "mode": "bus_priority"}))
        title = "Bus-priority signal update"
    if "speed" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("change_speed_limit", {"edge_id": edge_id, "speed_limit_mps": 10.0}))
    if not mutations:
        mutations.append(Mutation("replace_signal_with_roundabout", {"node_id": target_node_id}))
    proposal = ScenarioProposal(
        id=_stable_scenario_id(network, title, text, objective, mutations),
        title=title,
        intent=text,
        target_area={"primary_node_id": target_node_id, "hotspot": hotspot},
        mutations=mutations,
        evaluation_horizon_s=300,
        objective=objective,
    )
    validate_mutations(network, proposal.mutations)
    return proposal


def build_scenario_templates(network: TrafficNetwork, demand_profile: DemandProfile) -> List[Dict[str, Any]]:
    hotspots = demand_profile.metadata.get("hotspots", [])
    hotspot = hotspots[0] if hotspots else sorted(network.nodes)[0]
    target_node_id = _choose_target_node(network, hotspot)
    target_edge_id = _choose_edge_near_node(network, target_node_id)
    connector_source, connector_target = _choose_connector_nodes(network)
    corridor_origin, corridor_destination = _choose_corridor_nodes(network)
    templates = [
        {
            "key": "roundabout_hotspot",
            "title": "Replace one busy traffic light with a roundabout",
            "summary": "A focused street redesign study that checks whether one bottleneck intersection should become a roundabout.",
            "category": "Street redesign",
            "objective": "avg_travel_time_s",
            "what_to_watch": "Average travel time, queue length, and cars that finish the trip.",
            "intent": "Replace one busy traffic light with a roundabout and compare the impact on traffic flow.",
            "target_area": {"primary_node_id": target_node_id, "hotspot": hotspot},
            "mutations": [{"mutation_type": "replace_signal_with_roundabout", "params": {"node_id": target_node_id}}],
        },
        {
            "key": "incident_detour",
            "title": "Close one busy road after an accident and test the detour plan",
            "summary": "An incident-response study that blocks a major road segment and checks how well the city reroutes traffic around it.",
            "category": "Accident response",
            "objective": "avg_travel_time_s",
            "what_to_watch": "Travel time, queue growth, and whether the smart controller keeps traffic moving around the closure.",
            "intent": "Close one busy road because of an accident and compare the impact on travel times and queue build-up.",
            "target_area": {"primary_node_id": target_node_id, "edge_id": target_edge_id, "hotspot": hotspot},
            "mutations": [{"mutation_type": "close_edge", "params": {"edge_id": target_edge_id}}],
        },
        {
            "key": "ramp_connector",
            "title": "Add a new on/off-ramp style connector near a busy destination",
            "summary": "A macro network expansion study that tests whether a faster connector helps or creates new backups.",
            "category": "Highway access",
            "objective": "avg_travel_time_s",
            "what_to_watch": "Travel time gains versus any new queue growth at nearby streets.",
            "intent": "Add a new connector near a hot destination and measure whether travel gets faster or backups get worse.",
            "target_area": {"source_node_id": connector_source, "target_node_id": connector_target, "hotspot": hotspot},
            "mutations": [
                {
                    "mutation_type": "add_connector",
                    "params": {
                        "source": connector_source,
                        "target": connector_target,
                        "lane_count": 2,
                        "length_m": 110.0,
                        "speed_limit_mps": 22.0,
                    },
                }
            ],
        },
        {
            "key": "lane_upgrade",
            "title": "Add one more lane on the busiest approach",
            "summary": "A local capacity study that widens one constrained corridor near the main hotspot.",
            "category": "Road capacity",
            "objective": "throughput",
            "what_to_watch": "Cars that finish, people moved, and whether queues shrink in the same area.",
            "intent": "Widen the busiest approach near the hotspot and compare throughput.",
            "target_area": {"primary_node_id": target_node_id, "edge_id": target_edge_id, "hotspot": hotspot},
            "mutations": [{"mutation_type": "change_lane_count", "params": {"edge_id": target_edge_id, "lane_count": 2}}],
        },
        {
            "key": "bus_upgrade",
            "title": "Buy more buses on the busiest corridor",
            "summary": "A transit investment study that adds more frequent bus service and removes some car trips from the same corridor.",
            "category": "Transit service",
            "objective": "people_moved",
            "what_to_watch": "People moved, bus travel time, and cars taken off the road.",
            "intent": "Add more buses on the busiest corridor and compare how many people move through the city.",
            "target_area": {"origin": corridor_origin, "destination": corridor_destination},
            "mutations": [
                {
                    "mutation_type": "increase_bus_service",
                    "params": {
                        "origin": corridor_origin,
                        "destination": corridor_destination,
                        "headway_s": 55,
                        "offset_s": 16,
                        "line_name": "Express Bus Upgrade",
                    },
                }
            ],
        },
        {
            "key": "light_rail",
            "title": "Build a new light-rail corridor across the city",
            "summary": "A macro transit study that shifts part of the busiest cross-city demand onto a new rail corridor.",
            "category": "Rail expansion",
            "objective": "people_moved",
            "what_to_watch": "People moved, cars removed from roads, and travel time relief for the rest of the network.",
            "intent": "Build a light-rail line across the city and compare citywide movement.",
            "target_area": {"origin": corridor_origin, "destination": corridor_destination},
            "mutations": [
                {
                    "mutation_type": "build_light_rail_line",
                    "params": {
                        "origin": corridor_origin,
                        "destination": corridor_destination,
                        "line_name": "New Light Rail Link",
                    },
                }
            ],
        },
    ]
    return templates


def _choose_target_node(network: TrafficNetwork, preferred_node_id: str) -> str:
    node = network.nodes.get(preferred_node_id)
    if node is not None and node.control_type == "signal":
        return node.id
    signal_ids = network.signal_node_ids()
    return signal_ids[len(signal_ids) // 2]


def _choose_edge_near_node(network: TrafficNetwork, node_id: str) -> str:
    candidates = sorted(network.outgoing_edges(node_id), key=lambda edge: edge.length_m)
    return candidates[0].id if candidates else sorted(network.edges)[0]


def _choose_connector_nodes(network: TrafficNetwork) -> tuple[str, str]:
    boundary_ids = [node.id for node in network.boundary_nodes()]
    return boundary_ids[0], boundary_ids[-1]


def _choose_corridor_nodes(network: TrafficNetwork) -> tuple[str, str]:
    boundary_nodes = network.boundary_nodes()
    if len(boundary_nodes) < 2:
        ordered_ids = sorted(network.nodes)
        return ordered_ids[0], ordered_ids[-1]
    start, end = max(
        combinations(boundary_nodes, 2),
        key=lambda pair: (pair[0].x - pair[1].x) ** 2 + (pair[0].y - pair[1].y) ** 2,
    )
    return start.id, end.id


def _build_service_trips(
    graph: nx.DiGraph,
    horizon_s: int,
    *,
    origin: str,
    destination: str,
    headway_s: int,
    route_name: str,
    trip_prefix: str,
) -> List[TripRequest]:
    if not nx.has_path(graph, origin, destination):
        return []
    trips: List[TripRequest] = []
    trip_index = 0
    for direction_index, (start, end) in enumerate(((origin, destination), (destination, origin))):
        if not nx.has_path(graph, start, end):
            continue
        start_offset = 16 + direction_index * max(12, headway_s // 2)
        for departure_s in range(start_offset, horizon_s, headway_s):
            trips.append(
                TripRequest(
                    id=f"{trip_prefix}-{trip_index}",
                    origin=start,
                    destination=end,
                    departure_s=departure_s,
                    vehicle_type="bus",
                    route_name=route_name,
                )
            )
            trip_index += 1
    return trips


def _remove_car_trips_for_mode_shift(
    trips: List[TripRequest],
    *,
    preferred_nodes: set[str],
    fraction: float,
    minimum: int,
) -> tuple[List[TripRequest], int]:
    car_candidates = [
        trip
        for trip in trips
        if trip.vehicle_type == "car" and (trip.origin in preferred_nodes or trip.destination in preferred_nodes)
    ]
    if not car_candidates:
        return trips, 0
    remove_target = min(len(car_candidates), max(minimum, int(len(car_candidates) * fraction)))
    step = max(1, len(car_candidates) // max(1, remove_target))
    removed_ids = {trip.id for trip in car_candidates[::step][:remove_target]}
    filtered = [trip for trip in trips if trip.id not in removed_ids]
    return filtered, len(removed_ids)


def _build_transit_overlay(
    network: TrafficNetwork,
    origin: str,
    destination: str,
    *,
    line_name: str,
    overlay_type: str,
    color: str,
) -> Dict[str, object]:
    graph = build_graph(network)
    path_geometry: List[tuple[float, float]] = []
    try:
        node_path = nx.shortest_path(graph, origin, destination, weight="weight")
        for source, target in zip(node_path[:-1], node_path[1:]):
            edge_id = graph[source][target]["edge_id"]
            edge = network.edges[edge_id]
            if path_geometry and path_geometry[-1] == edge.geometry[0]:
                path_geometry.extend(edge.geometry[1:])
            else:
                path_geometry.extend(edge.geometry)
    except (nx.NetworkXNoPath, nx.NodeNotFound, KeyError):
        origin_node = network.nodes[origin]
        destination_node = network.nodes[destination]
        path_geometry = [(origin_node.x, origin_node.y), (destination_node.x, destination_node.y)]
    return {
        "name": line_name,
        "type": overlay_type,
        "color": color,
        "origin": origin,
        "destination": destination,
        "geometry": path_geometry,
    }
