from __future__ import annotations

from traffic_simulator.controllers import MaxPressureController, WebsterController, optimize_ga_timings
from traffic_simulator.domain import Incident
from traffic_simulator.networks import build_synthetic_grid, generate_demand_profile
from traffic_simulator.simulator import evaluate_candidate_timings


def test_webster_produces_viable_cycle_splits():
    network = build_synthetic_grid(seed=3)
    demand = generate_demand_profile(network, seed=3, horizon_s=240, trip_count=120)
    controller = WebsterController()
    controller.initialize(network, demand)

    assert controller.timings
    sample = next(iter(controller.timings.values()))
    assert 8 <= sample["NS"] <= 90
    assert 8 <= sample["EW"] <= 90
    assert sample["NS"] + sample["EW"] >= 16


def test_max_pressure_prefers_higher_pressure_phase():
    network = build_synthetic_grid(seed=2)
    demand = generate_demand_profile(network, seed=2, horizon_s=180, trip_count=80)
    controller = MaxPressureController(decision_interval_s=6)
    controller.initialize(network, demand)
    node_id = network.signal_node_ids()[0]
    incoming = network.incoming_edges(node_id)
    vertical = [edge.id for edge in incoming if edge.orientation == "vertical"]
    horizontal = [edge.id for edge in incoming if edge.orientation == "horizontal"]

    decisions = controller.decide(
        {
            "time_s": 0,
            "node_queues": {node_id: {"NS": 5, "EW": 2}},
            "node_edges": {node_id: {"NS": vertical, "EW": horizontal}},
            "downstream_queues": {edge_id: 1 for edge_id in vertical + horizontal},
            "edge_queues": {edge_id: (8 if edge_id in vertical else 1) for edge_id in vertical + horizontal},
            "node_phase_started": {node_id: 0},
        }
    )

    assert decisions[0].phase_id == "NS"


def test_ga_optimizer_returns_timing_map():
    network = build_synthetic_grid(seed=4)
    demand = generate_demand_profile(network, seed=4, horizon_s=180, trip_count=90)
    incident = Incident(id="i1", edge_id=sorted(network.edges)[0], start_s=60, end_s=120)
    timings = optimize_ga_timings(
        network,
        demand,
        lambda candidate: evaluate_candidate_timings(network, demand, candidate, duration_s=120, seed=4, incidents=[incident]),
        seed=4,
        population_size=4,
        generations=2,
    )

    assert set(timings.keys()) == set(network.signal_node_ids())
    assert all(6 <= phase_map["NS"] <= 32 and 6 <= phase_map["EW"] <= 32 for phase_map in timings.values())

