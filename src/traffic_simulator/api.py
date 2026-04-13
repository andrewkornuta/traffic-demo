from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from traffic_simulator.schemas import (
    MetricsResponse,
    NetworkLoadRequest,
    NetworkSummary,
    ProposalParseRequest,
    ReplayResponse,
    ScenarioCreateRequest,
    ScenarioResponse,
    ScenarioRunRequest,
    SimulationRunRequest,
    SimulationRunResponse,
)
from traffic_simulator.services import (
    create_scenario,
    get_run_metrics,
    get_run_replay,
    initialize_demo_seed_data,
    list_recent_runs,
    load_network,
    parse_scenario,
    run_network_simulation,
    run_scenario_batch,
    ui_config_payload,
    export_comparison_gif,
)


app = FastAPI(title="Traffic Digital Twin", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dir = Path(__file__).resolve().parent / "frontend"
app.mount("/demo", StaticFiles(directory=frontend_dir, html=True), name="demo")


@app.on_event("startup")
def startup() -> None:
    initialize_demo_seed_data()


@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/demo/")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/runs")
def runs() -> list[dict]:
    return list_recent_runs()


@app.get("/ui-config")
def ui_config() -> dict:
    return ui_config_payload()


@app.post("/networks/load", response_model=NetworkSummary)
def load_network_endpoint(payload: NetworkLoadRequest) -> NetworkSummary:
    try:
        result = load_network(payload)
        return NetworkSummary(**result)
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/scenarios", response_model=ScenarioResponse)
def create_scenario_endpoint(payload: ScenarioCreateRequest) -> ScenarioResponse:
    try:
        proposal = create_scenario(
            payload.network_id,
            payload.title,
            payload.intent,
            payload.target_area,
            [mutation.model_dump() for mutation in payload.mutations],
            payload.evaluation_horizon_s,
            payload.objective,
        )
        return ScenarioResponse(
            scenario_id=proposal.id,
            title=proposal.title,
            mutations=[{"mutation_type": mutation.mutation_type, "params": mutation.params} for mutation in proposal.mutations],
            objective=proposal.objective,
            evaluation_horizon_s=proposal.evaluation_horizon_s,
            target_area=proposal.target_area,
        )
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/scenarios/parse-proposal", response_model=ScenarioResponse)
def parse_proposal_endpoint(payload: ProposalParseRequest) -> ScenarioResponse:
    try:
        proposal = parse_scenario(payload.network_id, payload.proposal_text, payload.demand_profile_id)
        return ScenarioResponse(
            scenario_id=proposal.id,
            title=proposal.title,
            mutations=[{"mutation_type": mutation.mutation_type, "params": mutation.params} for mutation in proposal.mutations],
            objective=proposal.objective,
            evaluation_horizon_s=proposal.evaluation_horizon_s,
            target_area=proposal.target_area,
        )
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/scenarios/{scenario_id}/run")
def run_scenario_endpoint(scenario_id: str, payload: ScenarioRunRequest) -> dict:
    try:
        return run_scenario_batch(
            payload.network_id,
            scenario_id,
            payload.controller_mode,
            payload.duration_s,
            payload.seeds,
            payload.demand_profile_id,
        )
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/simulations/run", response_model=SimulationRunResponse)
def run_simulation_endpoint(payload: SimulationRunRequest) -> SimulationRunResponse:
    try:
        result = run_network_simulation(
            payload.network_id,
            payload.controller_mode,
            payload.seed,
            payload.duration_s,
            payload.demand_profile_id,
            payload.scenario_id,
        )
        return SimulationRunResponse(**result)
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/runs/{run_id}/metrics", response_model=MetricsResponse)
def metrics_endpoint(run_id: str) -> MetricsResponse:
    try:
        return MetricsResponse(run_id=run_id, metrics=get_run_metrics(run_id))
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/{run_id}/replay", response_model=ReplayResponse)
def replay_endpoint(run_id: str) -> ReplayResponse:
    try:
        return ReplayResponse(**get_run_replay(run_id))
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/runs/export-gif")
def export_gif(primary: str, comparison: Optional[str] = None) -> FileResponse:
    try:
        path = export_comparison_gif(primary, comparison)
        return FileResponse(path, filename=path.name, media_type="image/gif")
    except Exception as exc:  # pragma: no cover - API wrapper
        raise HTTPException(status_code=400, detail=str(exc)) from exc
