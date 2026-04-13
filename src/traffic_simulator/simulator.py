from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Tuple

import networkx as nx

from traffic_simulator.config import ARTIFACTS_DIR
from traffic_simulator.controllers import BaseController, GAOptimizedController, MaxPressureController, optimize_ga_timings
from traffic_simulator.domain import DemandProfile, Incident, PhaseDecision, TrafficNetwork, TripRequest
from traffic_simulator.networks import build_graph


@dataclass
class Vehicle:
    id: str
    destination: str
    path: List[str]
    segment_index: int
    edge_id: str
    remaining_s: int
    entered_at_s: int
    total_free_flow_s: int
    departed_at_s: int
    finished_at_s: int | None = None


@dataclass
class SimulationResult:
    run_id: str
    metrics: Dict[str, Any]
    replay_path: Path
    frames: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    telemetry_rows: List[Dict[str, Any]]
    control_actions: List[Dict[str, Any]]
    controller_config: Dict[str, Any] = field(default_factory=dict)


class TrafficSimulation:
    def __init__(
        self,
        network: TrafficNetwork,
        demand_profile: DemandProfile,
        controller: BaseController,
        incidents: List[Incident] | None = None,
        duration_s: int = 300,
        seed: int = 1,
        capture_replay: bool = True,
        capture_telemetry: bool = True,
        capture_control_actions: bool = True,
    ) -> None:
        self.network = network
        self.demand_profile = demand_profile
        self.controller = controller
        self.incidents = incidents or []
        self.duration_s = duration_s
        self.seed = seed
        self.capture_replay = capture_replay
        self.capture_telemetry = capture_telemetry
        self.capture_control_actions = capture_control_actions
        self.graph = build_graph(network)
        self.incoming_edges_by_node: Dict[str, List[Any]] = defaultdict(list)
        self.outgoing_edges_by_node: Dict[str, List[Any]] = defaultdict(list)
        self.edge_lookup: Dict[Tuple[str, str], Any] = {}
        for edge in network.edges.values():
            if not edge.enabled:
                continue
            self.incoming_edges_by_node[edge.target].append(edge)
            self.outgoing_edges_by_node[edge.source].append(edge)
            self.edge_lookup[(edge.source, edge.target)] = edge
        self.edge_queues: Dict[str, Deque[Vehicle]] = {edge_id: deque() for edge_id in network.edges}
        self.edge_active: Dict[str, List[Vehicle]] = {edge_id: [] for edge_id in network.edges}
        self.active_vehicles: Dict[str, Vehicle] = {}
        self.finished: List[Vehicle] = []
        self.control_actions: List[Dict[str, Any]] = []
        self.telemetry_rows: List[Dict[str, Any]] = []
        self.frames: List[Dict[str, Any]] = []
        self.timeline: List[Dict[str, Any]] = []
        self.node_phase_started = {node_id: 0 for node_id in network.signal_node_ids()}
        self.node_current_phase = {node_id: "NS" for node_id in network.signal_node_ids()}
        self.departure_pointer = 0
        self.sorted_trips = list(demand_profile.trips)
        self.current_time_s = 0
        self._cached_reroute_time_s: int | None = None
        self._cached_reroute_graph: nx.DiGraph | None = None

    def run(self) -> SimulationResult:
        self.controller.initialize(self.network, self.demand_profile, {})
        for time_s in range(self.duration_s):
            self.current_time_s = time_s
            self._spawn_departures(time_s)
            self._advance_edges(time_s)
            sim_state = self._build_sim_state(time_s)
            decisions = self.controller.decide(sim_state)
            self._apply_decisions(decisions, time_s)
            self._move_queues(time_s)
            if self.capture_replay:
                self._record_frame(time_s)
        metrics = self._compute_metrics()
        if self.capture_replay:
            replay_path = ARTIFACTS_DIR / f"{uuid.uuid4().hex}-replay.json"
            replay_path.write_text(json.dumps({"frames": self.frames, "timeline": self.timeline, "metrics": metrics}, indent=2))
        else:
            replay_path = Path("")
        return SimulationResult(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            metrics=metrics,
            replay_path=replay_path,
            frames=self.frames,
            timeline=self.timeline,
            telemetry_rows=self.telemetry_rows,
            control_actions=self.control_actions,
        )

    def _spawn_departures(self, time_s: int) -> None:
        while self.departure_pointer < len(self.sorted_trips) and self.sorted_trips[self.departure_pointer].departure_s <= time_s:
            trip = self.sorted_trips[self.departure_pointer]
            self.departure_pointer += 1
            path = self._path_for_trip(trip)
            if len(path) < 2:
                continue
            first_edge = self._edge_between(path[0], path[1])
            free_flow = self._path_free_flow(path)
            vehicle = Vehicle(
                id=trip.id,
                destination=trip.destination,
                path=path,
                segment_index=0,
                edge_id=first_edge.id,
                remaining_s=self._edge_travel_time(first_edge.id),
                entered_at_s=time_s,
                total_free_flow_s=free_flow,
                departed_at_s=time_s,
            )
            self.edge_active[first_edge.id].append(vehicle)
            self.active_vehicles[vehicle.id] = vehicle

    def _advance_edges(self, time_s: int) -> None:
        for edge_id, vehicles in self.edge_active.items():
            remaining_active: List[Vehicle] = []
            for vehicle in vehicles:
                vehicle.remaining_s -= 1
                if vehicle.remaining_s > 0:
                    remaining_active.append(vehicle)
                    continue
                if vehicle.segment_index >= len(vehicle.path) - 2:
                    vehicle.finished_at_s = time_s
                    self.finished.append(vehicle)
                    self.active_vehicles.pop(vehicle.id, None)
                    continue
                self.edge_queues[edge_id].append(vehicle)
            self.edge_active[edge_id] = remaining_active

    def _apply_decisions(self, decisions: List[PhaseDecision], time_s: int) -> None:
        for decision in decisions:
            if decision.node_id not in self.node_current_phase:
                continue
            if self.node_current_phase[decision.node_id] != decision.phase_id:
                self.node_phase_started[decision.node_id] = time_s
            self.node_current_phase[decision.node_id] = decision.phase_id
            if self.capture_control_actions:
                self.control_actions.append(
                    {
                        "time_s": time_s,
                        "node_id": decision.node_id,
                        "controller": self.controller.mode,
                        "phase_id": decision.phase_id,
                        "duration_s": decision.duration_s,
                        "inputs": decision.inputs,
                    }
                )

    def _move_queues(self, time_s: int) -> None:
        for node_id, node in self.network.nodes.items():
            incoming_edges = self.incoming_edges_by_node.get(node_id, [])
            if not incoming_edges:
                continue
            if node.control_type == "roundabout":
                allowed_edges = incoming_edges
                node_capacity = 2
            elif node.control_type != "signal":
                allowed_edges = incoming_edges
                node_capacity = max(1, len(incoming_edges))
            else:
                phase = self.node_current_phase.get(node_id, "NS")
                allowed_edges = [edge for edge in incoming_edges if self._phase_allows_edge(phase, edge.id)]
                node_capacity = max(1, len(allowed_edges))
            moved = 0
            for edge in sorted(allowed_edges, key=lambda entry: len(self.edge_queues[entry.id]), reverse=True):
                edge_capacity = max(1, edge.lane_count)
                if self._incident_active(edge.id, time_s):
                    edge_capacity = max(0, math.floor(edge_capacity * self._incident_capacity_multiplier(edge.id, time_s)))
                for _ in range(edge_capacity):
                    if moved >= node_capacity or not self.edge_queues[edge.id]:
                        break
                    vehicle = self.edge_queues[edge.id].popleft()
                    current_node = edge.target
                    if current_node == vehicle.destination:
                        vehicle.finished_at_s = time_s
                        self.finished.append(vehicle)
                        self.active_vehicles.pop(vehicle.id, None)
                        moved += 1
                        continue
                    vehicle.segment_index += 1
                    rerouted_path = self._reroute(vehicle, current_node)
                    if rerouted_path is not None:
                        vehicle.path = rerouted_path
                        vehicle.segment_index = 0
                    next_edge = self._edge_between(vehicle.path[vehicle.segment_index], vehicle.path[vehicle.segment_index + 1])
                    vehicle.edge_id = next_edge.id
                    vehicle.entered_at_s = time_s
                    vehicle.remaining_s = self._edge_travel_time(next_edge.id)
                    self.edge_active[next_edge.id].append(vehicle)
                    moved += 1

    def _path_for_trip(self, trip: TripRequest) -> List[str]:
        try:
            return nx.shortest_path(self.graph, trip.origin, trip.destination, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return [trip.origin]

    def _reroute(self, vehicle: Vehicle, current_node: str) -> List[str] | None:
        if not self._has_active_incident(self.current_time_s):
            return None
        if self._cached_reroute_time_s != self.current_time_s or self._cached_reroute_graph is None:
            self._cached_reroute_graph = build_graph(self.network, travel_time_overrides=self._current_edge_weights())
            self._cached_reroute_time_s = self.current_time_s
        graph = self._cached_reroute_graph
        try:
            path = nx.shortest_path(graph, current_node, vehicle.destination, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None
        if len(path) < 2:
            return None
        return path

    def _has_active_incident(self, time_s: int) -> bool:
        return any(incident.start_s <= time_s <= incident.end_s for incident in self.incidents)

    def _path_free_flow(self, path: List[str]) -> int:
        total = 0
        for source, target in zip(path[:-1], path[1:]):
            total += self._edge_between(source, target).base_travel_time_s
        return total

    def _edge_between(self, source: str, target: str):
        edge = self.edge_lookup.get((source, target))
        if edge is None:
            raise KeyError(f"No edge between {source} and {target}")
        return edge

    def _phase_allows_edge(self, phase: str, edge_id: str) -> bool:
        edge = self.network.edges[edge_id]
        return (phase == "NS" and edge.orientation == "vertical") or (phase == "EW" and edge.orientation == "horizontal")

    def _incident_active(self, edge_id: str, time_s: int) -> bool:
        return any(incident.edge_id == edge_id and incident.start_s <= time_s <= incident.end_s for incident in self.incidents)

    def _incident_capacity_multiplier(self, edge_id: str, time_s: int) -> float:
        for incident in self.incidents:
            if incident.edge_id == edge_id and incident.start_s <= time_s <= incident.end_s:
                return incident.capacity_multiplier
        return 1.0

    def _incident_speed_multiplier(self, edge_id: str, time_s: int = 0) -> float:
        for incident in self.incidents:
            if incident.edge_id == edge_id and incident.start_s <= time_s <= incident.end_s:
                return incident.speed_multiplier
        return 1.0

    def _edge_travel_time(self, edge_id: str) -> int:
        edge = self.network.edges[edge_id]
        active = len(self.edge_active[edge_id])
        queue = len(self.edge_queues[edge_id])
        volume = active + queue
        capacity = max(1, edge.lane_count * 6)
        congestion_multiplier = 1.0 + 0.35 * (volume / capacity)
        incident_multiplier = 1.0 / max(0.2, self._incident_speed_multiplier(edge_id, self.current_time_s))
        return max(1, int(round(edge.base_travel_time_s * congestion_multiplier * incident_multiplier)))

    def _current_edge_weights(self) -> Dict[str, float]:
        return {edge_id: self._edge_travel_time(edge_id) for edge_id in self.network.edges}

    def _build_sim_state(self, time_s: int) -> Dict[str, Any]:
        node_queues = defaultdict(lambda: {"NS": 0, "EW": 0})
        node_edges = defaultdict(lambda: {"NS": [], "EW": []})
        downstream_queues = {}
        for edge_id, queue in self.edge_queues.items():
            edge = self.network.edges[edge_id]
            bucket = "NS" if edge.orientation == "vertical" else "EW"
            node_queues[edge.target][bucket] += len(queue)
            node_edges[edge.target][bucket].append(edge_id)
            downstream_queues[edge_id] = sum(len(self.edge_queues[outgoing.id]) for outgoing in self.outgoing_edges_by_node.get(edge.target, []))
            if self.capture_telemetry:
                self.telemetry_rows.append(
                    {
                        "time_s": time_s,
                        "edge_id": edge_id,
                        "sensor_id": f"sensor-{edge_id}",
                        "speed_mps": edge.length_m / max(self._edge_travel_time(edge_id), 1),
                        "count": len(self.edge_active[edge_id]),
                        "occupancy_pct": min(100.0, 100.0 * len(self.edge_active[edge_id]) / max(1, edge.lane_count * 8)),
                        "queue_len_m": len(queue) * 7.5,
                        "quality_score": 1.0,
                    }
                )
        return {
            "time_s": time_s,
            "node_queues": node_queues,
            "node_edges": node_edges,
            "downstream_queues": downstream_queues,
            "edge_queues": {edge_id: len(queue) for edge_id, queue in self.edge_queues.items()},
            "node_phase_started": self.node_phase_started,
        }

    def _record_frame(self, time_s: int) -> None:
        vehicles = []
        for edge_id, active in self.edge_active.items():
            edge = self.network.edges[edge_id]
            for vehicle in active[:12]:
                progress = 1.0 - (vehicle.remaining_s / max(self._edge_travel_time(edge_id), 1))
                x = edge.geometry[0][0] + (edge.geometry[-1][0] - edge.geometry[0][0]) * progress
                y = edge.geometry[0][1] + (edge.geometry[-1][1] - edge.geometry[0][1]) * progress
                vehicles.append({"id": vehicle.id, "edge_id": edge_id, "x": x, "y": y})
        self.frames.append(
            {
                "time_s": time_s,
                "signals": dict(self.node_current_phase),
                "queues": {edge_id: len(queue) for edge_id, queue in self.edge_queues.items()},
                "vehicles": vehicles,
            }
        )
        current_edge_times = [self._edge_travel_time(edge_id) for edge_id, edge in self.network.edges.items() if edge.enabled]
        avg_edge_time = sum(current_edge_times) / max(1, len(current_edge_times))
        avg_queue = sum(len(queue) * 7.5 for queue in self.edge_queues.values()) / max(1, len(self.edge_queues))
        completed = len(self.finished)
        travel_time_index_s = round(avg_edge_time * 4 + (avg_queue / 6), 2)
        self.timeline.append(
            {
                "time_s": time_s,
                "travel_time_index_s": travel_time_index_s,
                "avg_queue_len_m": round(avg_queue, 2),
                "cars_through": completed,
            }
        )

    def _compute_metrics(self) -> Dict[str, Any]:
        finished_times = [vehicle.finished_at_s - vehicle.departed_at_s for vehicle in self.finished if vehicle.finished_at_s is not None]
        delays = [
            (vehicle.finished_at_s - vehicle.departed_at_s) - vehicle.total_free_flow_s
            for vehicle in self.finished
            if vehicle.finished_at_s is not None
        ]
        avg_queue_len_m = 0.0
        if self.telemetry_rows:
            avg_queue_len_m = sum(row["queue_len_m"] for row in self.telemetry_rows) / len(self.telemetry_rows)
        finished_times_sorted = sorted(finished_times)
        p95 = finished_times_sorted[int(len(finished_times_sorted) * 0.95) - 1] if finished_times_sorted else 0.0
        incident_penalty = sum(
            row["queue_len_m"] for row in self.telemetry_rows if any(incident.edge_id == row["edge_id"] for incident in self.incidents)
        ) / max(1, len(self.telemetry_rows))
        return {
            "avg_travel_time_s": round(sum(finished_times) / max(1, len(finished_times)), 2),
            "total_delay_s": round(sum(delays), 2),
            "throughput": len(self.finished),
            "avg_queue_len_m": round(avg_queue_len_m, 2),
            "p95_travel_time_s": round(p95, 2),
            "incident_clearance_impact": round(incident_penalty, 2),
            "completed_trip_count": len(self.finished),
            "total_trip_count": len(self.demand_profile.trips),
        }


def evaluate_candidate_timings(
    network: TrafficNetwork,
    demand_profile: DemandProfile,
    timings: Dict[str, Dict[str, int]],
    duration_s: int,
    seed: int,
    incidents: List[Incident] | None = None,
) -> float:
    controller = GAOptimizedController(timings)
    result = TrafficSimulation(
        network,
        demand_profile,
        controller,
        incidents=incidents,
        duration_s=duration_s,
        seed=seed,
        capture_replay=False,
        capture_telemetry=False,
        capture_control_actions=False,
    ).run()
    return float(result.metrics["avg_travel_time_s"])


def run_simulation(
    network: TrafficNetwork,
    demand_profile: DemandProfile,
    controller: BaseController,
    *,
    incidents: List[Incident] | None = None,
    duration_s: int = 300,
    seed: int = 1,
) -> SimulationResult:
    if controller.mode == "ga_optimized" and not isinstance(controller, GAOptimizedController):
        raise ValueError("Unexpected controller implementation for ga_optimized mode")
    simulation = TrafficSimulation(network, demand_profile, controller, incidents=incidents, duration_s=duration_s, seed=seed)
    return simulation.run()


def optimize_and_run_ga(
    network: TrafficNetwork,
    demand_profile: DemandProfile,
    *,
    incidents: List[Incident] | None = None,
    duration_s: int = 300,
    seed: int = 1,
) -> Tuple[SimulationResult, Dict[str, Dict[str, int]]]:
    signal_count = len(network.signal_node_ids())
    edge_count = len([edge for edge in network.edges.values() if edge.enabled])
    if edge_count > 1500 or signal_count > 80:
        population_size = 3
        generations = 2
        candidate_duration = max(45, min(90, duration_s // 6))
    elif edge_count > 500 or signal_count > 20:
        population_size = 4
        generations = 2
        candidate_duration = max(60, min(120, duration_s // 4))
    else:
        population_size = 6
        generations = 4
        candidate_duration = max(90, duration_s // 3)
    best_timings = optimize_ga_timings(
        network,
        demand_profile,
        lambda timings: evaluate_candidate_timings(
            network,
            demand_profile,
            timings,
            duration_s=candidate_duration,
            seed=seed,
            incidents=incidents,
        ),
        seed=seed,
        population_size=population_size,
        generations=generations,
    )
    controller = GAOptimizedController(best_timings)
    result = run_simulation(network, demand_profile, controller, incidents=incidents, duration_s=duration_s, seed=seed)
    result.controller_config = {"ga_timings": best_timings}
    return result, best_timings
