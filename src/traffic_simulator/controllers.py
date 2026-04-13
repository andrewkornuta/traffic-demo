from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

from traffic_simulator.domain import DemandProfile, PhaseDecision, TrafficNetwork


@dataclass
class ControllerState:
    phase_id: str = "NS"
    remaining_s: int = 0


class BaseController(ABC):
    mode = "base"

    def __init__(self, decision_interval_s: int = 10):
        self.decision_interval_s = decision_interval_s
        self.network: TrafficNetwork | None = None
        self.demand_profile: DemandProfile | None = None
        self.state_by_node: Dict[str, ControllerState] = {}

    def initialize(self, network: TrafficNetwork, demand_profile: DemandProfile, config: Dict | None = None) -> None:
        self.network = network
        self.demand_profile = demand_profile
        self.state_by_node = {node_id: ControllerState() for node_id in network.signal_node_ids()}

    def observe(self, sim_state: Dict) -> Dict:
        return sim_state

    @abstractmethod
    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        raise NotImplementedError

    def objective_metrics(self) -> List[str]:
        return ["avg_travel_time_s", "throughput", "avg_queue_len_m"]


class FixedTimeController(BaseController):
    mode = "fixed_time"

    def __init__(self, ns_green: int = 18, ew_green: int = 18):
        super().__init__(decision_interval_s=1)
        self.ns_green = ns_green
        self.ew_green = ew_green

    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        decisions: List[PhaseDecision] = []
        current_time = sim_state["time_s"]
        cycle = self.ns_green + self.ew_green
        for node_id in self.state_by_node:
            phase = "NS" if current_time % cycle < self.ns_green else "EW"
            decisions.append(PhaseDecision(node_id=node_id, phase_id=phase, duration_s=1))
        return decisions


class ActuatedController(BaseController):
    mode = "actuated"

    def __init__(self, min_green: int = 8, max_green: int = 24):
        super().__init__(decision_interval_s=1)
        self.min_green = min_green
        self.max_green = max_green

    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        decisions: List[PhaseDecision] = []
        for node_id, state in self.state_by_node.items():
            ns_queue = sim_state["node_queues"][node_id]["NS"]
            ew_queue = sim_state["node_queues"][node_id]["EW"]
            phase = state.phase_id
            elapsed = sim_state["time_s"] - sim_state["node_phase_started"][node_id]
            if phase == "NS":
                if elapsed >= self.max_green or (elapsed >= self.min_green and ew_queue > ns_queue * 1.1):
                    phase = "EW"
                    sim_state["node_phase_started"][node_id] = sim_state["time_s"]
            else:
                if elapsed >= self.max_green or (elapsed >= self.min_green and ns_queue > ew_queue * 1.1):
                    phase = "NS"
                    sim_state["node_phase_started"][node_id] = sim_state["time_s"]
            state.phase_id = phase
            decisions.append(
                PhaseDecision(
                    node_id=node_id,
                    phase_id=phase,
                    duration_s=1,
                    inputs={"ns_queue": ns_queue, "ew_queue": ew_queue},
                )
            )
        return decisions


class WebsterController(BaseController):
    mode = "webster"

    def __init__(self):
        super().__init__(decision_interval_s=1)
        self.timings: Dict[str, Dict[str, int]] = {}

    def initialize(self, network: TrafficNetwork, demand_profile: DemandProfile, config: Dict | None = None) -> None:
        super().initialize(network, demand_profile, config)
        self.timings = {}
        trip_paths = defaultdict(lambda: {"NS": 1.0, "EW": 1.0})
        for trip in demand_profile.trips:
            origin = network.nodes[trip.origin]
            destination = network.nodes[trip.destination]
            axis = "EW" if abs(origin.x - destination.x) >= abs(origin.y - destination.y) else "NS"
            for node_id in network.signal_node_ids():
                trip_paths[node_id][axis] += 1.0
        for node_id in network.signal_node_ids():
            flows = trip_paths[node_id]
            y_ns = min(0.45, flows["NS"] / max(flows["NS"] + flows["EW"], 1.0))
            y_ew = min(0.45, flows["EW"] / max(flows["NS"] + flows["EW"], 1.0))
            total_y = min(0.9, y_ns + y_ew)
            lost_time = 8.0
            cycle = int(round((1.5 * lost_time + 5) / max(0.1, 1 - total_y)))
            cycle = max(30, min(cycle, 90))
            effective_green = max(12, cycle - int(lost_time))
            ns_green = max(8, int(round(effective_green * (y_ns / max(total_y, 0.01)))))
            ew_green = max(8, effective_green - ns_green)
            self.timings[node_id] = {"NS": ns_green, "EW": ew_green}

    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        decisions: List[PhaseDecision] = []
        current_time = sim_state["time_s"]
        for node_id in self.state_by_node:
            timing = self.timings[node_id]
            cycle = timing["NS"] + timing["EW"]
            phase = "NS" if current_time % cycle < timing["NS"] else "EW"
            decisions.append(
                PhaseDecision(
                    node_id=node_id,
                    phase_id=phase,
                    duration_s=1,
                    inputs={"ns_green": timing["NS"], "ew_green": timing["EW"]},
                )
            )
        return decisions


class MaxPressureController(BaseController):
    mode = "max_pressure"

    def __init__(self, decision_interval_s: int = 8):
        super().__init__(decision_interval_s=decision_interval_s)

    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        decisions: List[PhaseDecision] = []
        for node_id, state in self.state_by_node.items():
            if state.remaining_s > 0:
                state.remaining_s -= 1
                decisions.append(PhaseDecision(node_id=node_id, phase_id=state.phase_id, duration_s=1))
                continue
            phase_scores = {}
            node_edges = sim_state.get("node_edges", {}).get(node_id, {"NS": [], "EW": []})
            for phase in ("NS", "EW"):
                pressure = 0.0
                for edge_id in node_edges.get(phase, []):
                    downstream = sim_state["downstream_queues"].get(edge_id, 0)
                    pressure += sim_state["edge_queues"].get(edge_id, 0) - downstream
                phase_scores[phase] = pressure
            best_phase = max(phase_scores, key=phase_scores.get)
            state.phase_id = best_phase
            state.remaining_s = self.decision_interval_s - 1
            decisions.append(
                PhaseDecision(
                    node_id=node_id,
                    phase_id=best_phase,
                    duration_s=self.decision_interval_s,
                    score=phase_scores[best_phase],
                    inputs=phase_scores,
                )
            )
        return decisions


class GAOptimizedController(BaseController):
    mode = "ga_optimized"

    def __init__(self, timings: Dict[str, Dict[str, int]]):
        super().__init__(decision_interval_s=1)
        self.timings = timings

    def decide(self, sim_state: Dict) -> List[PhaseDecision]:
        decisions: List[PhaseDecision] = []
        current_time = sim_state["time_s"]
        for node_id in self.state_by_node:
            timing = self.timings[node_id]
            cycle = timing["NS"] + timing["EW"]
            phase = "NS" if current_time % cycle < timing["NS"] else "EW"
            decisions.append(
                PhaseDecision(
                    node_id=node_id,
                    phase_id=phase,
                    duration_s=1,
                    inputs={"ns_green": timing["NS"], "ew_green": timing["EW"]},
                )
            )
        return decisions


def controller_for_mode(mode: str, ga_timings: Dict[str, Dict[str, int]] | None = None) -> BaseController:
    mapping = {
        "fixed_time": FixedTimeController,
        "actuated": ActuatedController,
        "webster": WebsterController,
        "max_pressure": MaxPressureController,
    }
    if mode == "ga_optimized":
        if ga_timings is None:
            raise ValueError("ga_timings are required for ga_optimized mode")
        return GAOptimizedController(ga_timings)
    if mode not in mapping:
        raise ValueError(f"Unsupported controller mode: {mode}")
    return mapping[mode]()


def optimize_ga_timings(
    network: TrafficNetwork,
    demand_profile: DemandProfile,
    evaluator,
    *,
    seed: int = 1,
    population_size: int = 8,
    generations: int = 5,
) -> Dict[str, Dict[str, int]]:
    rng = random.Random(seed)
    node_ids = network.signal_node_ids()

    def random_candidate() -> Dict[str, Dict[str, int]]:
        return {
            node_id: {"NS": rng.randint(8, 28), "EW": rng.randint(8, 28)}
            for node_id in node_ids
        }

    def mutate(candidate: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
        mutated = {node_id: dict(phase_map) for node_id, phase_map in candidate.items()}
        chosen = rng.choice(node_ids)
        axis = rng.choice(["NS", "EW"])
        mutated[chosen][axis] = max(6, min(32, mutated[chosen][axis] + rng.choice([-4, -2, 2, 4])))
        return mutated

    population = [random_candidate() for _ in range(population_size)]
    best_candidate = population[0]
    best_score = math.inf
    for _ in range(generations):
        scored = []
        for candidate in population:
            score = evaluator(candidate)
            scored.append((score, candidate))
            if score < best_score:
                best_score = score
                best_candidate = candidate
        scored.sort(key=lambda item: item[0])
        elites = [candidate for _, candidate in scored[: max(2, population_size // 3)]]
        population = list(elites)
        while len(population) < population_size:
            parent = rng.choice(elites)
            other = rng.choice(elites)
            child = {}
            for node_id in node_ids:
                donor = parent if rng.random() < 0.5 else other
                child[node_id] = dict(donor[node_id])
            if rng.random() < 0.8:
                child = mutate(child)
            population.append(child)
    return best_candidate
