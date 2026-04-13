from __future__ import annotations

import re
import uuid
from typing import Dict, List

from traffic_simulator.domain import DemandProfile, Mutation, ScenarioProposal, TrafficNetwork


ALLOWED_MUTATIONS = {
    "replace_signal_with_roundabout",
    "add_connector",
    "remove_connector",
    "close_edge",
    "change_speed_limit",
    "change_lane_count",
    "change_signal_plan",
}


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
    mutated.metadata["scenario_id"] = proposal.id
    return mutated


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
    if "close" in lowered and "road" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("close_edge", {"edge_id": edge_id}))
        title = "Close connector near hotspot"
    connector_match = re.search(r"connector|ramp|link", lowered)
    if connector_match:
        source, target = _choose_connector_nodes(network)
        mutations.append(
            Mutation(
                "add_connector",
                {
                    "source": source,
                    "target": target,
                    "lane_count": 1,
                    "length_m": 100.0,
                    "speed_limit_mps": 16.0,
                },
            )
        )
        title = "Connector proposal"
    if "lane" in lowered and "more" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("change_lane_count", {"edge_id": edge_id, "lane_count": 2}))
    if "speed" in lowered:
        edge_id = _choose_edge_near_node(network, target_node_id)
        mutations.append(Mutation("change_speed_limit", {"edge_id": edge_id, "speed_limit_mps": 10.0}))
    if not mutations:
        mutations.append(Mutation("replace_signal_with_roundabout", {"node_id": target_node_id}))
    proposal = ScenarioProposal(
        id=f"scenario-{uuid.uuid4().hex[:10]}",
        title=title,
        intent=text,
        target_area={"primary_node_id": target_node_id, "hotspot": hotspot},
        mutations=mutations,
        evaluation_horizon_s=300,
        objective=objective,
    )
    validate_mutations(network, proposal.mutations)
    return proposal


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

