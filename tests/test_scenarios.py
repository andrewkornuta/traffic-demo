from __future__ import annotations

import pytest

from traffic_simulator.domain import Mutation
from traffic_simulator.networks import build_synthetic_grid, generate_demand_profile
from traffic_simulator.scenarios import apply_scenario, parse_proposal_text, validate_mutations


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


def test_validate_rejects_unsupported_mutation():
    network = build_synthetic_grid(seed=1)
    with pytest.raises(ValueError):
        validate_mutations(network, [Mutation("explode_city", {"node_id": "x"})])

