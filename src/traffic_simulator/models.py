from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from traffic_simulator.db import Base


class NetworkModel(Base):
    __tablename__ = "networks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    source_type: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    nodes: Mapped[list["RoadNodeModel"]] = relationship(back_populates="network", cascade="all, delete-orphan")
    edges: Mapped[list["RoadEdgeModel"]] = relationship(back_populates="network", cascade="all, delete-orphan")


class RoadNodeModel(Base):
    __tablename__ = "road_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    control_type: Mapped[str] = mapped_column(String, default="signal")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    network: Mapped[NetworkModel] = relationship(back_populates="nodes")


class RoadEdgeModel(Base):
    __tablename__ = "road_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    source: Mapped[str] = mapped_column(String, index=True)
    target: Mapped[str] = mapped_column(String, index=True)
    orientation: Mapped[str] = mapped_column(String)
    length_m: Mapped[float] = mapped_column(Float)
    speed_limit_mps: Mapped[float] = mapped_column(Float)
    lane_count: Mapped[int] = mapped_column(Integer, default=1)
    capacity_vph: Mapped[float] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    geometry_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    network: Mapped[NetworkModel] = relationship(back_populates="edges")


class SensorModel(Base):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    edge_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sensor_type: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class DemandProfileModel(Base):
    __tablename__ = "demand_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    seed: Mapped[int] = mapped_column(Integer)
    horizon_s: Mapped[int] = mapped_column(Integer)
    trips_json: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class IncidentModel(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    edge_id: Mapped[str] = mapped_column(String)
    start_s: Mapped[int] = mapped_column(Integer)
    end_s: Mapped[int] = mapped_column(Integer)
    capacity_multiplier: Mapped[float] = mapped_column(Float, default=0.5)
    speed_multiplier: Mapped[float] = mapped_column(Float, default=0.6)
    lanes_blocked: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(Text, default="")


class ScenarioModel(Base):
    __tablename__ = "scenario_defs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    title: Mapped[str] = mapped_column(String)
    intent: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(String)
    target_area_json: Mapped[str] = mapped_column(Text, default="{}")
    mutations_json: Mapped[str] = mapped_column(Text)
    evaluation_horizon_s: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SimulationRunModel(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    network_id: Mapped[str] = mapped_column(ForeignKey("networks.id"), index=True)
    demand_profile_id: Mapped[str] = mapped_column(ForeignKey("demand_profiles.id"), index=True)
    scenario_id: Mapped[Optional[str]] = mapped_column(ForeignKey("scenario_defs.id"), nullable=True)
    controller_mode: Mapped[str] = mapped_column(String)
    seed: Mapped[int] = mapped_column(Integer)
    duration_s: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="completed")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    replay_path: Mapped[str] = mapped_column(String, default="")
    controller_config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TelemetryEventModel(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    time_s: Mapped[int] = mapped_column(Integer, index=True)
    sensor_id: Mapped[Optional[str]] = mapped_column(ForeignKey("sensors.id"), nullable=True)
    edge_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    speed_mps: Mapped[float] = mapped_column(Float, default=0.0)
    count: Mapped[int] = mapped_column(Integer, default=0)
    occupancy_pct: Mapped[float] = mapped_column(Float, default=0.0)
    queue_len_m: Mapped[float] = mapped_column(Float, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, default=1.0)


class ControlActionModel(Base):
    __tablename__ = "control_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id"), index=True)
    time_s: Mapped[int] = mapped_column(Integer, index=True)
    node_id: Mapped[str] = mapped_column(String, index=True)
    controller: Mapped[str] = mapped_column(String)
    phase_id: Mapped[str] = mapped_column(String)
    duration_s: Mapped[int] = mapped_column(Integer)
    inputs_json: Mapped[str] = mapped_column(Text, default="{}")
