from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Tuple


Coordinate = Tuple[float, float]


@dataclass
class RoadNode:
    id: str
    x: float
    y: float
    control_type: str = "signal"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RoadEdge:
    id: str
    source: str
    target: str
    orientation: str
    length_m: float
    speed_limit_mps: float
    lane_count: int
    capacity_vph: float
    geometry: List[Coordinate]
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def base_travel_time_s(self) -> int:
        return max(1, int(round(self.length_m / max(self.speed_limit_mps, 0.1))))


@dataclass
class TripRequest:
    id: str
    origin: str
    destination: str
    departure_s: int


@dataclass
class DemandProfile:
    id: str
    name: str
    seed: int
    horizon_s: int
    trips: List[TripRequest]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Incident:
    id: str
    edge_id: str
    start_s: int
    end_s: int
    capacity_multiplier: float = 0.5
    speed_multiplier: float = 0.6
    lanes_blocked: int = 1
    notes: str = ""


@dataclass
class Mutation:
    mutation_type: str
    params: Dict[str, Any]


@dataclass
class ScenarioProposal:
    id: str
    title: str
    intent: str
    target_area: Dict[str, Any]
    mutations: List[Mutation]
    evaluation_horizon_s: int
    objective: str


@dataclass
class PhaseDecision:
    node_id: str
    phase_id: str
    duration_s: int
    score: float = 0.0
    inputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrafficNetwork:
    id: str
    name: str
    version: int
    source_type: str
    nodes: Dict[str, RoadNode]
    edges: Dict[str, RoadEdge]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def incoming_edges(self, node_id: str) -> List[RoadEdge]:
        return [edge for edge in self.edges.values() if edge.enabled and edge.target == node_id]

    def outgoing_edges(self, node_id: str) -> List[RoadEdge]:
        return [edge for edge in self.edges.values() if edge.enabled and edge.source == node_id]

    def signal_node_ids(self) -> List[str]:
        return sorted([node.id for node in self.nodes.values() if node.control_type == "signal"])

    def serialize(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "source_type": self.source_type,
            "metadata": self.metadata,
            "nodes": {node_id: asdict(node) for node_id, node in self.nodes.items()},
            "edges": {edge_id: asdict(edge) for edge_id, edge in self.edges.items()},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TrafficNetwork":
        nodes = {node_id: RoadNode(**node_data) for node_id, node_data in payload["nodes"].items()}
        edges = {edge_id: RoadEdge(**edge_data) for edge_id, edge_data in payload["edges"].items()}
        return cls(
            id=payload["id"],
            name=payload["name"],
            version=payload["version"],
            source_type=payload["source_type"],
            nodes=nodes,
            edges=edges,
            metadata=payload.get("metadata", {}),
        )

    def copy(self, version: int | None = None) -> "TrafficNetwork":
        payload = self.serialize()
        if version is not None:
            payload["version"] = version
        return TrafficNetwork.from_dict(payload)

    def boundary_nodes(self) -> List[RoadNode]:
        coords = [(node.x, node.y) for node in self.nodes.values()]
        xs = [xy[0] for xy in coords]
        ys = [xy[1] for xy in coords]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        return [
            node
            for node in self.nodes.values()
            if node.x in (min_x, max_x) or node.y in (min_y, max_y)
        ]

    def to_geojson(self) -> Dict[str, Any]:
        features: List[Dict[str, Any]] = []
        for edge in self.edges.values():
            if not edge.enabled:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": edge.geometry},
                    "properties": {
                        "id": edge.id,
                        "orientation": edge.orientation,
                        "lane_count": edge.lane_count,
                        "speed_limit_mps": edge.speed_limit_mps,
                    },
                }
            )
        for node in self.nodes.values():
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [node.x, node.y]},
                    "properties": {
                        "id": node.id,
                        "control_type": node.control_type,
                        "kind": "node",
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}


def flatten(iterable: Iterable[Iterable[Any]]) -> List[Any]:
    return [item for group in iterable for item in group]

