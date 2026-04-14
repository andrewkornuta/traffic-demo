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
    traffic_scale: float = Field(default=1.0, ge=0.5, le=4.0)
    grid_config: Optional[GridConfig] = None
    osm_area: Optional[OSMArea] = None


class NetworkSummary(BaseModel):
    network_id: str
    network_version: int
    name: str
    source_type: str
    place_query: Optional[str] = None
    node_count: int
    edge_count: int
    demand_profile_id: str
    bus_route_count: int = 0
    city_input_count: int = 0
    planned_car_trip_count: int = 0
    planned_bus_trip_count: int = 0
    traffic_scale: float = 1.0


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


class ScenarioStudyRequest(BaseModel):
    network_id: str
    demand_profile_id: Optional[str] = None
    controller_modes: List[str] = Field(default_factory=lambda: ["fixed_time", "max_pressure", "ga_optimized"])
    seeds: List[int] = Field(default_factory=lambda: [1, 2, 3])
    duration_s: int = 300


class AnalystStudyRequest(BaseModel):
    study: Dict[str, Any]
    question: str = "Summarize this city study in plain English and tell me what the city should do."
    network_name: Optional[str] = None


class AnalystRunRequest(BaseModel):
    run_ids: List[str]
    question: str = "In plain English, what happened here and which controller should I pay attention to?"


class AnalystResponse(BaseModel):
    answer: str
    used_ai: bool
    provider: str
    model: str
    fallback_reason: Optional[str] = None


class ReplayResponse(BaseModel):
    run_id: str
    replay_path: str
    frames: List[Dict[str, Any]]
    timeline: List[Dict[str, Any]]
    network_geojson: Dict[str, Any]
    network_summary: Dict[str, Any]
    metrics: Dict[str, Any]
    controller: Dict[str, Any]
    scenario: Dict[str, Any]


class MetricsResponse(BaseModel):
    run_id: str
    metrics: Dict[str, Any]
