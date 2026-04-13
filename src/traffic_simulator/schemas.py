from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GridConfig(BaseModel):
    rows: int = 4
    cols: int = 4


class OSMArea(BaseModel):
    place_query: str


class NetworkLoadRequest(BaseModel):
    source_type: str = Field(pattern="^(synthetic|osm)$")
    name: str = "traffic-network"
    seed: int = 1
    grid_config: Optional[GridConfig] = None
    osm_area: Optional[OSMArea] = None


class NetworkSummary(BaseModel):
    network_id: str
    network_version: int
    name: str
    source_type: str
    node_count: int
    edge_count: int
    demand_profile_id: str


class MutationPayload(BaseModel):
    mutation_type: str
    params: Dict[str, Any]


class ScenarioCreateRequest(BaseModel):
    network_id: str
    title: str
    intent: str
    target_area: Dict[str, Any] = Field(default_factory=dict)
    mutations: List[MutationPayload]
    evaluation_horizon_s: int = 300
    objective: str = "avg_travel_time_s"


class ProposalParseRequest(BaseModel):
    network_id: str
    proposal_text: str
    demand_profile_id: Optional[str] = None


class ScenarioResponse(BaseModel):
    scenario_id: str
    title: str
    mutations: List[MutationPayload]
    objective: str
    evaluation_horizon_s: int
    target_area: Dict[str, Any]


class SimulationRunRequest(BaseModel):
    network_id: str
    network_version: Optional[int] = None
    controller_mode: str
    demand_profile_id: Optional[str] = None
    scenario_id: Optional[str] = None
    seed: int = 1
    duration_s: int = 300


class SimulationRunResponse(BaseModel):
    run_id: str
    status: str
    controller_mode: str
    metrics: Dict[str, Any]


class ScenarioRunRequest(BaseModel):
    network_id: str
    demand_profile_id: Optional[str] = None
    controller_mode: str = "max_pressure"
    seeds: List[int] = Field(default_factory=lambda: [1, 2, 3])
    duration_s: int = 300


class ReplayResponse(BaseModel):
    run_id: str
    replay_path: str
    frames: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    network_geojson: Dict[str, Any]
    metrics: Dict[str, Any]
    controller: Dict[str, Any]
    scenario: Dict[str, Any]


class MetricsResponse(BaseModel):
    run_id: str
    metrics: Dict[str, Any]
