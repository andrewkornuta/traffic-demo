from __future__ import annotations

import pytest

from traffic_simulator.domain import Mutation
from traffic_simulator.networks import build_synthetic_grid, generate_demand_profile
from traffic_simulator.scenarios import apply_demand_changes, apply_scenario, parse_proposal_text, validate_mutations


def test_parse_proposal_creates_roundabout_mutation():
    network = build_synthetic_grid(seed=5)
    demand = generate_demand_profile(network, seed=5, horizon_s=200, trip_count=100)

    proposal = parse_proposal_text(
        "replace this signal with a roundabout near the busiest destination and compare travel times",
        network,
        demand,
    )

    assert proposal.mutations
    assert proposal.mutations[0].mutation_type == "replace_signal_with_roundabout"
    mutated = apply_scenario(network, proposal)
    assert mutated.nodes[proposal.mutations[0].params["node_id"]].control_type == "roundabout"


def test_demand_profile_contains_scheduled_buses():
    network = build_synthetic_grid(seed=9)
    demand = generate_demand_profile(network, seed=9, horizon_s=240, trip_count=100)

    assert demand.metadata["bus_lines"]
    assert any(trip.vehicle_type == "bus" for trip in demand.trips)
    assert any(trip.route_name for trip in demand.trips if trip.vehicle_type == "bus")


def test_heavier_traffic_scale_creates_more_car_trips():
    network = build_synthetic_grid(seed=10)
    light = generate_demand_profile(network, seed=10, traffic_scale=0.75)
    heavy = generate_demand_profile(network, seed=10, traffic_scale=2.2)

    light_cars = len([trip for trip in light.trips if trip.vehicle_type == "car"])
    heavy_cars = len([trip for trip in heavy.trips if trip.vehicle_type == "car"])

    assert heavy_cars > light_cars


def test_parse_proposal_creates_ramp_connector_mutation():
    network = build_synthetic_grid(seed=6)
    demand = generate_demand_profile(network, seed=6, horizon_s=200, trip_count=100)

    proposal = parse_proposal_text(
        "add a new off-ramp near the busiest destination to reduce backups",
        network,
        demand,
    )

    connector = next((mutation for mutation in proposal.mutations if mutation.mutation_type == "add_connector"), None)
    assert connector is not None
    assert connector.params["lane_count"] == 2


def test_transit_proposal_adds_light_rail_and_mode_shift():
    network = build_synthetic_grid(seed=12)
    demand = generate_demand_profile(network, seed=12, horizon_s=240, trip_count=120)

    proposal = parse_proposal_text(
        "build a light rail line across the city and compare how many people we can move",
        network,
        demand,
    )

    rail = next((mutation for mutation in proposal.mutations if mutation.mutation_type == "build_light_rail_line"), None)
    assert rail is not None
    adjusted = apply_demand_changes(apply_scenario(network, proposal), demand, proposal)
    assert adjusted.metadata["rail_riders_served"] > 0
    assert adjusted.metadata["mode_shift_removed_cars"] > 0


def test_validate_rejects_unsupported_mutation():
    network = build_synthetic_grid(seed=1)
    with pytest.raises(ValueError):
        validate_mutations(network, [Mutation("explode_city", {"node_id": "x"})])
