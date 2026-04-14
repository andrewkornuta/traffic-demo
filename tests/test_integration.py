from __future__ import annotations

from fastapi.testclient import TestClient

from traffic_simulator.api import app


def test_end_to_end_api_flow():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "integration-grid", "seed": 11, "traffic_scale": 1.5, "grid_config": {"rows": 4, "cols": 4}},
        ).json()
        assert network["node_count"] == 16
        assert network["bus_route_count"] >= 1
        assert network["city_input_count"] >= 1
        assert network["planned_car_trip_count"] > 0

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
        assert ga["metrics"]["avg_travel_time_s"] <= fixed["metrics"]["avg_travel_time_s"] + 1.5
        assert "city_flow_score" in adaptive["metrics"]
        assert "bus_avg_travel_time_s" in adaptive["metrics"]
        assert "people_moved" in adaptive["metrics"]
        assert adaptive["metrics"]["started_car_trip_count"] >= adaptive["metrics"]["throughput"]

        replay = client.get(f"/runs/{adaptive['run_id']}/replay").json()
        assert replay["frames"]
        assert replay["network_geojson"]["features"]
        assert replay["network_summary"]["bus_route_count"] >= 1
        assert replay["network_summary"]["city_inputs"]
        assert replay["network_summary"]["planned_car_trip_count"] >= adaptive["metrics"]["started_car_trip_count"]


def test_scenario_replay_includes_transit_overlays_and_mode_shift():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "transit-grid", "seed": 13, "grid_config": {"rows": 4, "cols": 4}},
        ).json()
        scenario = client.post(
            "/scenarios/parse-proposal",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "proposal_text": "add a light rail line across the city and compare how many cars come off the road",
            },
        ).json()

        run = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "max_pressure",
                "scenario_id": scenario["scenario_id"],
                "seed": 13,
                "duration_s": 180,
            },
        ).json()

        replay = client.get(f"/runs/{run['run_id']}/replay").json()
        assert replay["network_summary"]["rail_line_count"] >= 1
        assert replay["network_summary"]["cars_removed_from_roads"] > 0
        assert any(overlay["type"] == "rail" for overlay in replay["network_summary"]["transit_overlays"])
        assert run["metrics"]["people_moved"] > 0


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


def test_reloading_same_network_and_proposal_reuses_stable_ids():
    with TestClient(app) as client:
        payload = {"source_type": "synthetic", "name": "stable-grid", "seed": 31, "grid_config": {"rows": 4, "cols": 4}}
        first_network = client.post("/networks/load", json=payload).json()
        second_network = client.post("/networks/load", json=payload).json()

        assert first_network["network_id"] == second_network["network_id"]
        assert first_network["demand_profile_id"] == second_network["demand_profile_id"]

        proposal_payload = {
            "network_id": first_network["network_id"],
            "demand_profile_id": first_network["demand_profile_id"],
            "proposal_text": "replace the traffic light at the busy intersection with a roundabout",
        }
        first_scenario = client.post("/scenarios/parse-proposal", json=proposal_payload).json()
        second_scenario = client.post("/scenarios/parse-proposal", json=proposal_payload).json()

        assert first_scenario["scenario_id"] == second_scenario["scenario_id"]


def test_templates_and_study_api_cover_macro_and_incident_workflows():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "study-grid", "seed": 23, "grid_config": {"rows": 4, "cols": 4}},
        ).json()

        templates = client.get(
            f"/scenarios/templates?network_id={network['network_id']}&demand_profile_id={network['demand_profile_id']}"
        ).json()

        keys = {template["key"] for template in templates}
        assert {"roundabout_hotspot", "incident_detour", "ramp_connector", "bus_upgrade", "light_rail"} <= keys

        incident_template = next(template for template in templates if template["key"] == "incident_detour")
        scenario = client.post(
            "/scenarios",
            json={
                "network_id": network["network_id"],
                "title": incident_template["title"],
                "intent": incident_template["intent"],
                "target_area": incident_template["target_area"],
                "mutations": incident_template["mutations"],
                "evaluation_horizon_s": 180,
                "objective": incident_template["objective"],
            },
        ).json()

        study = client.post(
            f"/scenarios/{scenario['scenario_id']}/study",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_modes": ["fixed_time", "max_pressure"],
                "seeds": [23, 27, 32],
                "duration_s": 180,
            },
        ).json()

        assert len(study["controllers"]) == 2
        assert study["recommended_viewer"]["primary"]
        assert study["recommended_viewer"]["comparison"]
        for summary in study["controllers"]:
            assert summary["baseline_run_ids"]
            assert summary["proposal_run_ids"]
            assert "avg_travel_time_s" in summary["baseline_aggregate_metrics"]
            assert "avg_travel_time_s" in summary["proposal_aggregate_metrics"]


def test_ai_analyst_endpoints_return_plain_english_summaries():
    with TestClient(app) as client:
        network = client.post(
            "/networks/load",
            json={"source_type": "synthetic", "name": "analyst-grid", "seed": 29, "grid_config": {"rows": 4, "cols": 4}},
        ).json()

        fixed = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "fixed_time",
                "seed": 29,
                "duration_s": 180,
            },
        ).json()
        smart = client.post(
            "/simulations/run",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_mode": "max_pressure",
                "seed": 29,
                "duration_s": 180,
            },
        ).json()

        run_summary = client.post(
            "/analysis/run-summary",
            json={
                "run_ids": [fixed["run_id"], smart["run_id"]],
                "question": "In plain English, what happened here?",
            },
        ).json()
        assert run_summary["answer"]
        assert "Recommendation:" in run_summary["answer"]

        scenario = client.post(
            "/scenarios/parse-proposal",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "proposal_text": "build a light rail line across the city and compare how many people we can move",
            },
        ).json()
        study = client.post(
            f"/scenarios/{scenario['scenario_id']}/study",
            json={
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "controller_modes": ["fixed_time", "ga_optimized"],
                "seeds": [29, 33, 38],
                "duration_s": 180,
            },
        ).json()
        study_summary = client.post(
            "/analysis/study-summary",
            json={
                "study": study,
                "network_name": network["name"],
                "question": "What should the city do based on these results?",
            },
        ).json()
        assert study_summary["answer"]
        assert "Recommendation:" in study_summary["answer"]
