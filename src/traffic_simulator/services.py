from __future__ import annotations

import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

from PIL import Image, ImageDraw

from traffic_simulator.controllers import controller_for_mode
from traffic_simulator.db import Base, engine, session_scope
from traffic_simulator.domain import Incident, Mutation, ScenarioProposal
from traffic_simulator.networks import build_synthetic_grid, generate_demand_profile, load_osm_network
from traffic_simulator.persistence import (
    get_demand_profile,
    get_incidents,
    get_network,
    get_run,
    get_scenario,
    list_runs,
    save_control_actions,
    save_demand_profile,
    save_incidents,
    save_network,
    save_run,
    save_scenario,
    save_telemetry,
)
from traffic_simulator.scenarios import apply_scenario, parse_proposal_text
from traffic_simulator.simulator import optimize_and_run_ga, run_simulation
from traffic_simulator.ui_text import (
    APP_SUBTITLE,
    APP_TITLE,
    METRIC_COPY,
    controller_copy,
    how_it_works_items,
    summarize_scenario,
)


Base.metadata.create_all(bind=engine)


def initialize_demo_seed_data() -> None:
    seeded_network_id = None
    seeded_demand_id = None
    with session_scope() as session:
        if list_runs(session):
            return
        network = build_synthetic_grid()
        save_network(session, network)
        demand = generate_demand_profile(network)
        save_demand_profile(session, network.id, demand)
        seeded_network_id = network.id
        seeded_demand_id = demand.id
        incidents = [
            Incident(
                id="incident-demo",
                edge_id=sorted(network.edges)[3],
                start_s=120,
                end_s=220,
                capacity_multiplier=0.5,
                speed_multiplier=0.6,
                lanes_blocked=1,
                notes="Seeded demo lane blockage",
            )
        ]
        save_incidents(session, network.id, incidents)
    if seeded_network_id and seeded_demand_id:
        for controller_mode in ("fixed_time", "max_pressure", "ga_optimized"):
            run_network_simulation(
                seeded_network_id,
                controller_mode,
                seed=7,
                duration_s=240,
                demand_profile_id=seeded_demand_id,
            )


def load_network(payload) -> Dict[str, Any]:
    if payload.source_type == "synthetic":
        rows = payload.grid_config.rows if payload.grid_config else 4
        cols = payload.grid_config.cols if payload.grid_config else 4
        network = build_synthetic_grid(rows=rows, cols=cols, seed=payload.seed)
    else:
        if payload.osm_area is None:
            raise ValueError("osm_area is required for source_type=osm")
        network = load_osm_network(payload.name, payload.osm_area.place_query)
    network.name = payload.name
    demand = generate_demand_profile(network, seed=payload.seed)
    with session_scope() as session:
        save_network(session, network)
        save_demand_profile(session, network.id, demand)
        if network.source_type == "synthetic" and not get_incidents(session, network.id):
            incidents = [
                Incident(
                    id=f"incident-{network.id}",
                    edge_id=sorted(network.edges)[0],
                    start_s=90,
                    end_s=180,
                    capacity_multiplier=0.4,
                    speed_multiplier=0.55,
                    lanes_blocked=1,
                    notes="Seeded incident for controller comparison",
                )
            ]
            save_incidents(session, network.id, incidents)
    return {
        "network_id": network.id,
        "network_version": network.version,
        "name": network.name,
        "source_type": network.source_type,
        "node_count": len(network.nodes),
        "edge_count": len([edge for edge in network.edges.values() if edge.enabled]),
        "demand_profile_id": demand.id,
    }


def create_scenario(network_id: str, title: str, intent: str, target_area: Dict[str, Any], mutations: List[Dict[str, Any]], evaluation_horizon_s: int, objective: str) -> ScenarioProposal:
    with session_scope() as session:
        network = get_network(session, network_id)
        proposal = ScenarioProposal(
            id=f"scenario-{network_id[:8]}-{abs(hash(title)) % 100000}",
            title=title,
            intent=intent,
            target_area=target_area,
            mutations=[Mutation(mutation_type=item["mutation_type"], params=item["params"]) for item in mutations],
            evaluation_horizon_s=evaluation_horizon_s,
            objective=objective,
        )
        save_scenario(session, network.id, proposal)
        return proposal


def parse_scenario(network_id: str, proposal_text: str, demand_profile_id: str | None = None) -> ScenarioProposal:
    with session_scope() as session:
        network = get_network(session, network_id)
        demand_profile = get_demand_profile(session, demand_profile_id or _default_demand_profile_id(session, network_id))
        proposal = parse_proposal_text(proposal_text, network, demand_profile)
        save_scenario(session, network.id, proposal)
        return proposal


def _default_demand_profile_id(session, network_id: str) -> str:
    from traffic_simulator.models import DemandProfileModel
    demand = (
        session.query(DemandProfileModel)
        .filter(DemandProfileModel.network_id == network_id)
        .order_by(DemandProfileModel.name.asc())
        .first()
    )
    if demand is None:
        raise KeyError(f"No demand profile for network {network_id}")
    return demand.id


def run_network_simulation(network_id: str, controller_mode: str, seed: int, duration_s: int, demand_profile_id: str | None = None, scenario_id: str | None = None) -> Dict[str, Any]:
    with session_scope() as session:
        network = get_network(session, network_id)
        if demand_profile_id is None:
            from traffic_simulator.models import DemandProfileModel
            demand_model = session.query(DemandProfileModel).filter(DemandProfileModel.network_id == network_id).first()
            if demand_model is None:
                raise KeyError("Missing demand profile")
            demand_profile_id = demand_model.id
        demand_profile = get_demand_profile(session, demand_profile_id)
        incidents = get_incidents(session, network_id)
        scenario = get_scenario(session, scenario_id) if scenario_id else None
        if scenario is not None:
            network = apply_scenario(network, scenario)
        if controller_mode == "ga_optimized":
            result, best_timings = optimize_and_run_ga(network, demand_profile, incidents=incidents, duration_s=duration_s, seed=seed)
            controller_config = {"ga_timings": best_timings}
        else:
            controller = controller_for_mode(controller_mode)
            result = run_simulation(network, demand_profile, controller, incidents=incidents, duration_s=duration_s, seed=seed)
            controller_config = {}
        save_run(
            session,
            run_id=result.run_id,
            network_id=network_id,
            demand_profile_id=demand_profile_id,
            scenario_id=scenario_id,
            controller_mode=controller_mode,
            seed=seed,
            duration_s=duration_s,
            metrics=result.metrics,
            replay_path=result.replay_path,
            controller_config=controller_config,
        )
        save_telemetry(session, result.run_id, result.telemetry_rows)
        save_control_actions(session, result.run_id, result.control_actions)
        return {"run_id": result.run_id, "status": "completed", "controller_mode": controller_mode, "metrics": result.metrics}


def get_run_metrics(run_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        run = get_run(session, run_id)
        return json.loads(run.metrics_json)


def get_run_replay(run_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        run = get_run(session, run_id)
        network = get_network(session, run.network_id)
        replay_path = Path(run.replay_path)
        payload = json.loads(replay_path.read_text())
        scenario = get_scenario(session, run.scenario_id) if run.scenario_id else None
        return {
            "run_id": run_id,
            "replay_path": str(replay_path),
            "frames": payload["frames"],
            "timeline": payload.get("timeline") or _timeline_from_frames(payload["frames"]),
            "network_geojson": network.to_geojson(),
            "metrics": json.loads(run.metrics_json or "{}"),
            "controller": controller_copy(run.controller_mode),
            "scenario": summarize_scenario(scenario),
        }


def list_recent_runs() -> List[Dict[str, Any]]:
    with session_scope() as session:
        runs = list_runs(session)
        return [
            _run_card_payload(session, run)
            for run in runs
        ]


def run_scenario_batch(network_id: str, scenario_id: str, controller_mode: str, duration_s: int, seeds: List[int], demand_profile_id: str | None = None) -> Dict[str, Any]:
    results = [run_network_simulation(network_id, controller_mode, seed, duration_s, demand_profile_id=demand_profile_id, scenario_id=scenario_id) for seed in seeds]
    metric_names = results[0]["metrics"].keys()
    aggregate = {
        metric_name: round(mean(result["metrics"][metric_name] for result in results), 2)
        for metric_name in metric_names
        if isinstance(results[0]["metrics"][metric_name], (int, float))
    }
    return {"scenario_id": scenario_id, "controller_mode": controller_mode, "run_ids": [result["run_id"] for result in results], "aggregate_metrics": aggregate}


def ui_config_payload() -> Dict[str, Any]:
    return {
        "app_title": APP_TITLE,
        "app_subtitle": APP_SUBTITLE,
        "controllers": how_it_works_items(),
        "metric_copy": METRIC_COPY,
    }


def export_comparison_gif(primary_run_id: str, comparison_run_id: str | None = None) -> Path:
    primary = get_run_replay(primary_run_id)
    comparison = get_run_replay(comparison_run_id) if comparison_run_id else None
    path = Path(primary["replay_path"]).with_name(f"comparison-{primary_run_id}-{comparison_run_id or 'solo'}.gif")
    frames = _build_comparison_gif_frames(primary, comparison)
    if not frames:
        raise ValueError("No replay frames available for GIF export.")
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return path


def _run_card_payload(session, run) -> Dict[str, Any]:
    scenario = get_scenario(session, run.scenario_id) if run.scenario_id else None
    return {
        "run_id": run.id,
        "network_id": run.network_id,
        "controller_mode": run.controller_mode,
        "controller": controller_copy(run.controller_mode),
        "scenario_id": run.scenario_id,
        "scenario": summarize_scenario(scenario),
        "metrics": json.loads(run.metrics_json or "{}"),
        "created_at": run.created_at.isoformat(),
    }


def _timeline_from_frames(frames: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    timeline = []
    for frame in frames:
        queue_lengths = list(frame.get("queues", {}).values())
        avg_queue_len_m = (sum(queue_lengths) / max(1, len(queue_lengths))) * 7.5 if queue_lengths else 0.0
        timeline.append(
            {
                "time_s": frame.get("time_s", 0),
                "travel_time_index_s": round(18 + avg_queue_len_m / 5, 2),
                "avg_queue_len_m": round(avg_queue_len_m, 2),
                "cars_through": 0,
            }
        )
    return timeline


def _build_comparison_gif_frames(primary: Dict[str, Any], comparison: Dict[str, Any] | None) -> List[Image.Image]:
    frame_count = min(150, len(primary["frames"]))
    step = max(1, len(primary["frames"]) // max(1, frame_count))
    indices = list(range(0, len(primary["frames"]), step))[:frame_count]
    frames: List[Image.Image] = []
    for frame_index in indices:
        canvas = Image.new("RGB", (1200, 520), "#07111f")
        draw = ImageDraw.Draw(canvas)
        _draw_replay_panel(draw, primary, frame_index, (20, 20, 580, 500))
        if comparison:
            _draw_replay_panel(draw, comparison, frame_index if frame_index < len(comparison["frames"]) else len(comparison["frames"]) - 1, (620, 20, 1180, 500))
        else:
            draw.text((640, 250), "No comparison run selected", fill="#94A3B8")
        frames.append(canvas)
    return frames


def _draw_replay_panel(draw: ImageDraw.ImageDraw, replay: Dict[str, Any], frame_index: int, bounds: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = bounds
    draw.rounded_rectangle(bounds, radius=24, outline="#153043", fill="#081525")
    draw.text((left + 20, top + 16), replay["controller"]["display"], fill=replay["controller"]["badge_color"])
    frame = replay["frames"][frame_index]
    line_features = [feature for feature in replay["network_geojson"]["features"] if feature["geometry"]["type"] == "LineString"]
    point_features = [feature for feature in replay["network_geojson"]["features"] if feature["geometry"]["type"] == "Point"]
    coords = [coord for feature in line_features for coord in feature["geometry"]["coordinates"]]
    coords.extend(feature["geometry"]["coordinates"] for feature in point_features)
    xs = [coord[0] for coord in coords]
    ys = [coord[1] for coord in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    width = right - left
    height = bottom - top
    pad = 48
    scale_x = lambda value: left + pad + ((value - min_x) / max(0.001, max_x - min_x)) * (width - pad * 2)
    scale_y = lambda value: bottom - pad - ((value - min_y) / max(0.001, max_y - min_y)) * (height - pad * 2)
    for feature in line_features:
        queue = frame["queues"].get(feature["properties"]["id"], 0)
        color = "#ff4d4d" if queue >= 10 else "#f59e0b" if queue >= 4 else "#22d3ee"
        points = [(scale_x(x), scale_y(y)) for x, y in feature["geometry"]["coordinates"]]
        draw.line(points, fill=color, width=int(3 + min(queue, 10) * 0.4))
    for feature in point_features:
        signal = frame["signals"].get(feature["properties"]["id"], "NS")
        color = "#22d3ee" if signal == "NS" else "#a855f7"
        x, y = feature["geometry"]["coordinates"]
        px, py = scale_x(x), scale_y(y)
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=color, outline="#ffffff")
    for vehicle in frame.get("vehicles", []):
        px, py = scale_x(vehicle["x"]), scale_y(vehicle["y"])
        draw.ellipse((px - 2, py - 2, px + 2, py + 2), fill="#d7fbff")
