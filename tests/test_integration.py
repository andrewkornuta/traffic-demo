from __future__ import annotations

from fastapi.testclient import TestClient

from traffic_simulator.api import app


def test_end_to_end_api_flow():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "integration-grid", "seed": 11, "grid_config": {"rows": 4, "cols": 4}},
        ).json()
        assert network["node_count"] == 16

        scenario = client.post(
            "/scenarios/parse-proposal",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "proposal_text": "replace this signal with a roundabout near the busiest destination and compare travel times",
            },
        ).json()
        assert scenario["mutations"]

        fixed = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "fixed_time",
                "seed": 11,
                "duration_s": 240,
            },
        ).json()
        adaptive = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "max_pressure",
                "seed": 11,
                "duration_s": 240,
            },
        ).json()
        ga = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "ga_optimized",
                "seed": 11,
                "duration_s": 240,
            },
        ).json()

        assert fixed["metrics"]["avg_travel_time_s"] > adaptive["metrics"]["avg_travel_time_s"]
        assert ga["metrics"]["avg_travel_time_s"] <= fixed["metrics"]["avg_travel_time_s"]

        replay = client.get(f"/runs/{adaptive['run_id']}/replay").json()
        assert replay["frames"]
        assert replay["network_geojson"]["features"]


def test_repeat_runs_are_deterministic_for_same_seed():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "deterministic-grid", "seed": 19, "grid_config": {"rows": 4, "cols": 4}},
        ).json()
        payload = {
            "network_id": network["network_id"],
            "demand_profile_id": network["demand_profile_id"],
            "controller_mode": "max_pressure",
            "seed": 19,
            "duration_s": 240,
        }

        first = client.post("/simulations/run", json=payload).json()
        second = client.post("/simulations/run", json=payload).json()

        assert first["metrics"] == second["metrics"]
