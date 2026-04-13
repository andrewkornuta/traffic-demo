from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from traffic_simulator.domain import DemandProfile, Incident, Mutation, RoadEdge, RoadNode, ScenarioProposal, TrafficNetwork, TripRequest
from traffic_simulator.models import (
    ControlActionModel,
    DemandProfileModel,
    IncidentModel,
    NetworkModel,
    RoadEdgeModel,
    RoadNodeModel,
    ScenarioModel,
    SensorModel,
    SimulationRunModel,
    TelemetryEventModel,
)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_json_safe(value))


def save_network(session: Session, network: TrafficNetwork) -> None:
    existing = session.get(NetworkModel, network.id)
    if existing is not None:
        session.query(RoadNodeModel).filter(RoadNodeModel.network_id == network.id).delete()
        session.query(RoadEdgeModel).filter(RoadEdgeModel.network_id == network.id).delete()
        session.query(SensorModel).filter(SensorModel.network_id == network.id).delete()
        existing.name = network.name
        existing.source_type = network.source_type
        existing.version = network.version
        existing.metadata_json = _json_dumps(network.metadata)
    else:
        existing = NetworkModel(
            id=network.id,
            name=network.name,
            source_type=network.source_type,
            version=network.version,
            metadata_json=_json_dumps(network.metadata),
        )
        session.add(existing)
    for node in network.nodes.values():
        session.add(
            RoadNodeModel(
                id=node.id,
                network_id=network.id,
                x=node.x,
                y=node.y,
                control_type=node.control_type,
                metadata_json=_json_dumps(node.metadata),
            )
        )
        session.add(
            SensorModel(
                id=f"sensor-{node.id}",
                network_id=network.id,
                node_id=node.id,
                sensor_type="intersection_counter",
                metadata_json=json.dumps({"kind": "derived"}),
            )
        )
    for edge in network.edges.values():
        session.add(
            RoadEdgeModel(
                id=edge.id,
                network_id=network.id,
                source=edge.source,
                target=edge.target,
                orientation=edge.orientation,
                length_m=edge.length_m,
                speed_limit_mps=edge.speed_limit_mps,
                lane_count=edge.lane_count,
                capacity_vph=edge.capacity_vph,
                enabled=edge.enabled,
                geometry_json=json.dumps(edge.geometry),
                metadata_json=_json_dumps(edge.metadata),
            )
        )
        session.add(
            SensorModel(
                id=f"sensor-{edge.id}",
                network_id=network.id,
                edge_id=edge.id,
                sensor_type="edge_counter",
                metadata_json=json.dumps({"kind": "derived"}),
            )
        )


def get_network(session: Session, network_id: str) -> TrafficNetwork:
    network_model = session.get(NetworkModel, network_id)
    if network_model is None:
        raise KeyError(f"Unknown network: {network_id}")
    nodes = {
        model.id: RoadNode(
            id=model.id,
            x=model.x,
            y=model.y,
            control_type=model.control_type,
            metadata=json.loads(model.metadata_json or "{}"),
        )
        for model in session.scalars(select(RoadNodeModel).where(RoadNodeModel.network_id == network_id))
    }
    edges = {
        model.id: RoadEdge(
            id=model.id,
            source=model.source,
            target=model.target,
            orientation=model.orientation,
            length_m=model.length_m,
            speed_limit_mps=model.speed_limit_mps,
            lane_count=model.lane_count,
            capacity_vph=model.capacity_vph,
            enabled=model.enabled,
            geometry=json.loads(model.geometry_json or "[]"),
            metadata=json.loads(model.metadata_json or "{}"),
        )
        for model in session.scalars(select(RoadEdgeModel).where(RoadEdgeModel.network_id == network_id))
    }
    return TrafficNetwork(
        id=network_model.id,
        name=network_model.name,
        version=network_model.version,
        source_type=network_model.source_type,
        nodes=nodes,
        edges=edges,
        metadata=json.loads(network_model.metadata_json or "{}"),
    )


def save_demand_profile(session: Session, network_id: str, demand_profile: DemandProfile) -> None:
    session.merge(
        DemandProfileModel(
            id=demand_profile.id,
            network_id=network_id,
            name=demand_profile.name,
            seed=demand_profile.seed,
            horizon_s=demand_profile.horizon_s,
            trips_json=_json_dumps([trip.__dict__ for trip in demand_profile.trips]),
            metadata_json=_json_dumps(demand_profile.metadata),
        )
    )


def get_demand_profile(session: Session, demand_profile_id: str) -> DemandProfile:
    model = session.get(DemandProfileModel, demand_profile_id)
    if model is None:
        raise KeyError(f"Unknown demand profile: {demand_profile_id}")
    trips = [TripRequest(**trip) for trip in json.loads(model.trips_json)]
    return DemandProfile(
        id=model.id,
        name=model.name,
        seed=model.seed,
        horizon_s=model.horizon_s,
        trips=trips,
        metadata=json.loads(model.metadata_json or "{}"),
    )


def save_incidents(session: Session, network_id: str, incidents: List[Incident]) -> None:
    session.query(IncidentModel).filter(IncidentModel.network_id == network_id).delete()
    for incident in incidents:
        session.add(
            IncidentModel(
                id=incident.id,
                network_id=network_id,
                edge_id=incident.edge_id,
                start_s=incident.start_s,
                end_s=incident.end_s,
                capacity_multiplier=incident.capacity_multiplier,
                speed_multiplier=incident.speed_multiplier,
                lanes_blocked=incident.lanes_blocked,
                notes=incident.notes,
            )
        )


def get_incidents(session: Session, network_id: str) -> List[Incident]:
    return [
        Incident(
            id=model.id,
            edge_id=model.edge_id,
            start_s=model.start_s,
            end_s=model.end_s,
            capacity_multiplier=model.capacity_multiplier,
            speed_multiplier=model.speed_multiplier,
            lanes_blocked=model.lanes_blocked,
            notes=model.notes,
        )
        for model in session.scalars(select(IncidentModel).where(IncidentModel.network_id == network_id))
    ]


def save_scenario(session: Session, network_id: str, proposal: ScenarioProposal) -> None:
    session.merge(
        ScenarioModel(
            id=proposal.id,
            network_id=network_id,
            title=proposal.title,
            intent=proposal.intent,
            objective=proposal.objective,
            target_area_json=_json_dumps(proposal.target_area),
            mutations_json=_json_dumps([{"mutation_type": m.mutation_type, "params": m.params} for m in proposal.mutations]),
            evaluation_horizon_s=proposal.evaluation_horizon_s,
        )
    )


def get_scenario(session: Session, scenario_id: str) -> ScenarioProposal:
    model = session.get(ScenarioModel, scenario_id)
    if model is None:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    return ScenarioProposal(
        id=model.id,
        title=model.title,
        intent=model.intent,
        target_area=json.loads(model.target_area_json or "{}"),
        mutations=[Mutation(**entry) for entry in json.loads(model.mutations_json)],
        evaluation_horizon_s=model.evaluation_horizon_s,
        objective=model.objective,
    )


def save_run(
    session: Session,
    *,
    run_id: str,
    network_id: str,
    demand_profile_id: str,
    scenario_id: str | None,
    controller_mode: str,
    seed: int,
    duration_s: int,
    metrics: Dict[str, Any],
    replay_path: Path,
    controller_config: Dict[str, Any],
) -> None:
    session.merge(
        SimulationRunModel(
            id=run_id,
            network_id=network_id,
            demand_profile_id=demand_profile_id,
            scenario_id=scenario_id,
            controller_mode=controller_mode,
            seed=seed,
            duration_s=duration_s,
            status="completed",
            metrics_json=json.dumps(metrics),
            replay_path=str(replay_path),
            controller_config_json=json.dumps(controller_config),
        )
    )


def save_telemetry(session: Session, run_id: str, telemetry_rows: List[Dict[str, Any]]) -> None:
    for row in telemetry_rows:
        session.add(
            TelemetryEventModel(
                run_id=run_id,
                time_s=row["time_s"],
                edge_id=row.get("edge_id"),
                sensor_id=row.get("sensor_id"),
                speed_mps=row.get("speed_mps", 0.0),
                count=row.get("count", 0),
                occupancy_pct=row.get("occupancy_pct", 0.0),
                queue_len_m=row.get("queue_len_m", 0.0),
                quality_score=row.get("quality_score", 1.0),
            )
        )


def save_control_actions(session: Session, run_id: str, actions: List[Dict[str, Any]]) -> None:
    for action in actions:
        session.add(
            ControlActionModel(
                run_id=run_id,
                time_s=action["time_s"],
                node_id=action["node_id"],
                controller=action["controller"],
                phase_id=action["phase_id"],
                duration_s=action["duration_s"],
                inputs_json=json.dumps(action.get("inputs", {})),
            )
        )


def get_run(session: Session, run_id: str) -> SimulationRunModel:
    run = session.get(SimulationRunModel, run_id)
    if run is None:
        raise KeyError(f"Unknown run: {run_id}")
    return run


def list_runs(session: Session) -> List[SimulationRunModel]:
    return list(session.scalars(select(SimulationRunModel).order_by(SimulationRunModel.created_at.desc()).limit(20)))
