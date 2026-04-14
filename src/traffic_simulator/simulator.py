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
    vehicle_type: str = "car"
    route_name: str | None = None
    size_units: float = 1.0
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
                vehicle_type=trip.vehicle_type,
                route_name=trip.route_name,
                size_units=2.5 if trip.vehicle_type == "bus" else 1.0,
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
            for edge in sorted(allowed_edges, key=lambda entry: self._queue_units(self.edge_queues[entry.id]), reverse=True):
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
        node_bus_queues = defaultdict(lambda: {"NS": 0, "EW": 0})
        node_edges = defaultdict(lambda: {"NS": [], "EW": []})
        downstream_queues = {}
        edge_bus_queues = {}
        for edge_id, queue in self.edge_queues.items():
            edge = self.network.edges[edge_id]
            bucket = "NS" if edge.orientation == "vertical" else "EW"
            queue_units = self._queue_units(queue)
            bus_queue_count = sum(1 for vehicle in queue if vehicle.vehicle_type == "bus")
            node_queues[edge.target][bucket] += queue_units
            node_bus_queues[edge.target][bucket] += bus_queue_count
            node_edges[edge.target][bucket].append(edge_id)
            downstream_queues[edge_id] = sum(self._queue_units(self.edge_queues[outgoing.id]) for outgoing in self.outgoing_edges_by_node.get(edge.target, []))
            edge_bus_queues[edge_id] = bus_queue_count
            if self.capture_telemetry:
                active_units = sum(vehicle.size_units for vehicle in self.edge_active[edge_id])
                self.telemetry_rows.append(
                    {
                        "time_s": time_s,
                        "edge_id": edge_id,
                        "sensor_id": f"sensor-{edge_id}",
                        "speed_mps": edge.length_m / max(self._edge_travel_time(edge_id), 1),
                        "count": len(self.edge_active[edge_id]),
                        "occupancy_pct": min(100.0, 100.0 * active_units / max(1, edge.lane_count * 8)),
                        "queue_len_m": queue_units * 7.5,
                        "quality_score": 1.0,
                    }
                )
        return {
            "time_s": time_s,
            "node_queues": node_queues,
            "node_bus_queues": node_bus_queues,
            "node_edges": node_edges,
            "downstream_queues": downstream_queues,
            "edge_queues": {edge_id: self._queue_units(queue) for edge_id, queue in self.edge_queues.items()},
            "edge_bus_queues": edge_bus_queues,
            "node_phase_started": self.node_phase_started,
        }

    def _record_frame(self, time_s: int) -> None:
        vehicles = []
        for edge_id, active in self.edge_active.items():
            edge = self.network.edges[edge_id]
            visible = active[:18]
            if len(active) > 18:
                step = max(1, math.ceil((len(active) - 18) / 12))
                visible += active[18::step][:12]
            visible_ids = {vehicle.id for vehicle in visible}
            visible += [
                vehicle
                for vehicle in active
                if vehicle.vehicle_type == "bus" and vehicle.id not in visible_ids
            ][:6]
            for vehicle in visible:
                progress = 1.0 - (vehicle.remaining_s / max(self._edge_travel_time(edge_id), 1))
                x, y = self._point_along_geometry(edge.geometry, progress)
                vehicles.append(
                    {
                        "id": vehicle.id,
                        "edge_id": edge_id,
                        "x": x,
                        "y": y,
                        "vehicle_type": vehicle.vehicle_type,
                        "route_name": vehicle.route_name,
                    }
                )
        bus_completed = len([vehicle for vehicle in self.finished if vehicle.vehicle_type == "bus"])
        self.frames.append(
            {
                "time_s": time_s,
                "signals": dict(self.node_current_phase),
                "queues": {edge_id: self._queue_units(queue) for edge_id, queue in self.edge_queues.items()},
                "vehicles": vehicles,
            }
        )
        current_edge_times = [self._edge_travel_time(edge_id) for edge_id, edge in self.network.edges.items() if edge.enabled]
        avg_edge_time = sum(current_edge_times) / max(1, len(current_edge_times))
        avg_queue = sum(self._queue_units(queue) * 7.5 for queue in self.edge_queues.values()) / max(1, len(self.edge_queues))
        completed = len(self.finished)
        travel_time_index_s = round(avg_edge_time * 4 + (avg_queue / 6), 2)
        self.timeline.append(
            {
                "time_s": time_s,
                "travel_time_index_s": travel_time_index_s,
                "avg_queue_len_m": round(avg_queue, 2),
                "cars_through": completed,
                "buses_through": bus_completed,
            }
        )

    def _compute_metrics(self) -> Dict[str, Any]:
        completed_vehicles = [vehicle for vehicle in self.finished if vehicle.finished_at_s is not None]
        in_progress_vehicles = list(self.active_vehicles.values())
        observed_vehicles = completed_vehicles + in_progress_vehicles
        started_trips = [trip for trip in self.demand_profile.trips if trip.departure_s < self.duration_s]
        started_car_trip_count = len([trip for trip in started_trips if trip.vehicle_type == "car"])
        started_bus_trip_count = len([trip for trip in started_trips if trip.vehicle_type == "bus"])
        projected_trip_times = [self._projected_trip_duration(vehicle) for vehicle in observed_vehicles]
        projected_delays = [self._projected_trip_duration(vehicle) - vehicle.total_free_flow_s for vehicle in observed_vehicles]
        bus_observed = [vehicle for vehicle in observed_vehicles if vehicle.vehicle_type == "bus"]
        bus_projected_trip_times = [self._projected_trip_duration(vehicle) for vehicle in bus_observed]
        bus_projected_delays = [self._projected_trip_duration(vehicle) - vehicle.total_free_flow_s for vehicle in bus_observed]
        avg_queue_len_m = 0.0
        if self.telemetry_rows:
            avg_queue_len_m = sum(row["queue_len_m"] for row in self.telemetry_rows) / len(self.telemetry_rows)
        projected_times_sorted = sorted(projected_trip_times)
        p95 = projected_times_sorted[max(0, int(len(projected_times_sorted) * 0.95) - 1)] if projected_times_sorted else 0.0
        incident_penalty = sum(
            row["queue_len_m"] for row in self.telemetry_rows if any(incident.edge_id == row["edge_id"] for incident in self.incidents)
        ) / max(1, len(self.telemetry_rows))
        throughput = len(completed_vehicles)
        bus_throughput = len([vehicle for vehicle in completed_vehicles if vehicle.vehicle_type == "bus"])
        total_trip_count = len(self.demand_profile.trips)
        bus_trip_count = len([trip for trip in self.demand_profile.trips if trip.vehicle_type == "bus"])
        avg_travel_time_s = round(sum(projected_trip_times) / max(1, len(projected_trip_times)), 2)
        total_delay_s = round(sum(projected_delays), 2)
        bus_avg_travel_time_s = round(sum(bus_projected_trip_times) / max(1, len(bus_projected_trip_times)), 2)
        bus_total_delay_s = round(sum(bus_projected_delays), 2)
        completion_ratio_pct = round((throughput / max(1, len(started_trips))) * 100, 1)
        bus_completion_ratio_pct = round((bus_throughput / max(1, started_bus_trip_count)) * 100, 1)
        rail_riders_served = int(self.demand_profile.metadata.get("rail_riders_served", 0))
        cars_removed_from_roads = int(self.demand_profile.metadata.get("mode_shift_removed_cars", 0))
        people_moved = int(round(sum(self._person_movement_units(vehicle) for vehicle in observed_vehicles) + rail_riders_served))
        city_flow_score = self._city_flow_score(
            total_delay_s=total_delay_s,
            avg_queue_len_m=avg_queue_len_m,
            completion_ratio_pct=completion_ratio_pct,
            bus_avg_travel_time_s=bus_avg_travel_time_s,
            bus_completion_ratio_pct=bus_completion_ratio_pct,
            incident_penalty=incident_penalty,
            people_moved=people_moved,
        )
        return {
            "avg_travel_time_s": avg_travel_time_s,
            "total_delay_s": total_delay_s,
            "throughput": throughput,
            "avg_queue_len_m": round(avg_queue_len_m, 2),
            "p95_travel_time_s": round(p95, 2),
            "incident_clearance_impact": round(incident_penalty, 2),
            "completed_trip_count": throughput,
            "total_trip_count": total_trip_count,
            "started_trip_count": len(started_trips),
            "started_car_trip_count": started_car_trip_count,
            "started_bus_trip_count": started_bus_trip_count,
            "bus_avg_travel_time_s": bus_avg_travel_time_s,
            "bus_total_delay_s": bus_total_delay_s,
            "bus_throughput": bus_throughput,
            "bus_trip_count": bus_trip_count,
            "completion_ratio_pct": completion_ratio_pct,
            "bus_completion_ratio_pct": bus_completion_ratio_pct,
            "people_moved": people_moved,
            "rail_riders_served": rail_riders_served,
            "cars_removed_from_roads": cars_removed_from_roads,
            "city_flow_score": city_flow_score,
        }

    def _projected_trip_duration(self, vehicle: Vehicle) -> float:
        if vehicle.finished_at_s is not None:
            return float(vehicle.finished_at_s - vehicle.departed_at_s)
        elapsed_s = max(0, self.duration_s - vehicle.departed_at_s)
        remaining_s = max(vehicle.remaining_s, 0) + self._remaining_free_flow_s(vehicle)
        return float(elapsed_s + remaining_s)

    def _remaining_free_flow_s(self, vehicle: Vehicle) -> int:
        if vehicle.segment_index >= len(vehicle.path) - 2:
            return 0
        total = 0
        for source, target in zip(vehicle.path[vehicle.segment_index + 1 : -1], vehicle.path[vehicle.segment_index + 2 :]):
            total += self._edge_between(source, target).base_travel_time_s
        return total

    def _person_movement_units(self, vehicle: Vehicle) -> float:
        occupancy = 18.0 if vehicle.vehicle_type == "bus" else 1.2
        return occupancy * self._vehicle_progress(vehicle)

    def _vehicle_progress(self, vehicle: Vehicle) -> float:
        if vehicle.finished_at_s is not None:
            return 1.0
        elapsed_s = max(0, self.duration_s - vehicle.departed_at_s)
        projected_duration = max(1.0, self._projected_trip_duration(vehicle))
        progress = elapsed_s / projected_duration
        return max(0.0, min(0.98, progress))

    def _queue_units(self, queue: Deque[Vehicle]) -> float:
        return sum(vehicle.size_units for vehicle in queue)

    def _city_flow_score(
        self,
        *,
        total_delay_s: float,
        avg_queue_len_m: float,
        completion_ratio_pct: float,
        bus_avg_travel_time_s: float,
        bus_completion_ratio_pct: float,
        incident_penalty: float,
        people_moved: float,
    ) -> float:
        delay_score = max(0.0, 28.0 - total_delay_s / max(6.0, len(self.demand_profile.trips) * 0.18))
        queue_score = max(0.0, 18.0 - avg_queue_len_m / 4.5)
        completion_score = min(24.0, completion_ratio_pct * 0.24)
        bus_speed_score = max(0.0, 18.0 - bus_avg_travel_time_s / 9.0) if any(trip.vehicle_type == "bus" for trip in self.demand_profile.trips) else 18.0
        bus_completion_score = min(6.0, bus_completion_ratio_pct * 0.06)
        incident_score = max(0.0, 6.0 - incident_penalty / 8.0)
        people_score = min(10.0, people_moved / max(10.0, len(self.demand_profile.trips) * 0.7))
        return round(delay_score + queue_score + completion_score + bus_speed_score + bus_completion_score + incident_score + people_score, 1)

    def _point_along_geometry(self, geometry: List[tuple[float, float]], progress: float) -> tuple[float, float]:
        if not geometry:
            return (0.0, 0.0)
        if len(geometry) == 1:
            return geometry[0]
        progress = max(0.0, min(1.0, progress))
        segment_lengths = []
        total_length = 0.0
        for start, end in zip(geometry[:-1], geometry[1:]):
            length = math.dist(start, end)
            segment_lengths.append(length)
            total_length += length
        if total_length <= 0:
            return geometry[-1]
        distance_target = total_length * progress
        traversed = 0.0
        for length, start, end in zip(segment_lengths, geometry[:-1], geometry[1:]):
            if traversed + length >= distance_target:
                local = 0.0 if length == 0 else (distance_target - traversed) / length
                x = start[0] + (end[0] - start[0]) * local
                y = start[1] + (end[1] - start[1]) * local
                return (x, y)
            traversed += length
        return geometry[-1]


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
    return float(
        result.metrics["avg_travel_time_s"]
        + result.metrics.get("bus_avg_travel_time_s", 0.0) * 0.35
        + result.metrics.get("avg_queue_len_m", 0.0) * 0.08
        - result.metrics.get("people_moved", 0.0) * 0.02
        - result.metrics.get("city_flow_score", 0.0) * 0.15
    )


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
