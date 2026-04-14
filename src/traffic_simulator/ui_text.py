from __future__ import annotations

from typing import Any, Dict, List

from traffic_simulator.domain import Mutation, ScenarioProposal


APP_TITLE = "Andrew's Traffic Analyzer - City Traffic Flow Optimizer"
APP_SUBTITLE = "See how different smart controllers improve traffic"


CONTROLLER_COPY: Dict[str, Dict[str, str]] = {
    "fixed_time": {
        "display": "Basic Fixed-Time Controller",
        "short": "Basic Fixed-Time",
        "description": "Lights follow a fixed schedule, no matter how busy traffic is.",
        "badge_color": "#94A3B8",
        "accent_color": "#64748B",
    },
    "max_pressure": {
        "display": "Real-Time Smart Controller",
        "short": "Real-Time Smart",
        "description": "Changes lights every few seconds based on actual car counts and queues.",
        "badge_color": "#22D3EE",
        "accent_color": "#06B6D4",
    },
    "ga_optimized": {
        "display": "Evolution-Optimized Controller",
        "short": "Evolution-Optimized",
        "description": "Tests thousands of timing plans in simulation and picks the winner.",
        "badge_color": "#A855F7",
        "accent_color": "#8B5CF6",
    },
    "actuated": {
        "display": "Reactive Signal Test Controller",
        "short": "Reactive Test",
        "description": "Extends green lights when one direction suddenly gets busier.",
        "badge_color": "#60A5FA",
        "accent_color": "#3B82F6",
    },
    "webster": {
        "display": "Balanced Timing Controller",
        "short": "Balanced Timing",
        "description": "Builds a more balanced fixed schedule from the expected traffic mix.",
        "badge_color": "#34D399",
        "accent_color": "#10B981",
    },
}

VISIBLE_CONTROLLER_MODES = ["fixed_time", "max_pressure", "ga_optimized"]

METRIC_COPY = {
    "avg_travel_time_s": {"label": "Average Travel Time", "unit": "s", "better": "lower"},
    "total_delay_s": {"label": "Total Delay", "unit": "s", "better": "lower"},
    "throughput": {"label": "Cars That Finished", "unit": "", "better": "higher"},
    "started_trip_count": {"label": "Trips Started", "unit": "", "better": "higher"},
    "started_car_trip_count": {"label": "Cars Entered The Map", "unit": "", "better": "higher"},
    "started_bus_trip_count": {"label": "Buses Entered The Map", "unit": "", "better": "higher"},
    "people_moved": {"label": "People Moved", "unit": "", "better": "higher"},
    "bus_avg_travel_time_s": {"label": "Average Bus Travel Time", "unit": "s", "better": "lower"},
    "bus_total_delay_s": {"label": "Total Bus Delay", "unit": "s", "better": "lower"},
    "bus_throughput": {"label": "Buses That Finished", "unit": "", "better": "higher"},
    "rail_riders_served": {"label": "Rail Riders Served", "unit": "", "better": "higher"},
    "cars_removed_from_roads": {"label": "Cars Taken Off The Road", "unit": "", "better": "higher"},
    "avg_queue_len_m": {"label": "Average Queue Length", "unit": "m", "better": "lower"},
    "p95_travel_time_s": {"label": "Worst-Case Travel Time", "unit": "s", "better": "lower"},
    "incident_clearance_impact": {"label": "Accident Impact", "unit": "", "better": "lower"},
    "completion_ratio_pct": {"label": "Trip Completion", "unit": "%", "better": "higher"},
    "bus_completion_ratio_pct": {"label": "Bus Trip Completion", "unit": "%", "better": "higher"},
    "city_flow_score": {"label": "City Flow Score", "unit": "", "better": "higher"},
}


def controller_copy(mode: str) -> Dict[str, str]:
    return CONTROLLER_COPY.get(mode, {
        "display": mode.replace("_", " ").title(),
        "short": mode.replace("_", " ").title(),
        "description": "Traffic signal controller.",
        "badge_color": "#94A3B8",
        "accent_color": "#64748B",
    })


def summarize_mutation(mutation: Mutation) -> str:
    params = mutation.params
    if mutation.mutation_type == "replace_signal_with_roundabout":
        return "Replace the selected busy traffic light with a roundabout."
    if mutation.mutation_type == "add_connector":
        lane_count = params.get("lane_count", 1)
        connector_label = "high-capacity ramp" if lane_count >= 2 else "road connector"
        return f"Add a new {connector_label} between two outer edges of the city grid."
    if mutation.mutation_type == "remove_connector":
        return "Remove one road connection from the current layout."
    if mutation.mutation_type == "close_edge":
        return "Close one busy road segment to simulate a disruption."
    if mutation.mutation_type == "change_speed_limit":
        return "Change the speed limit on a nearby corridor."
    if mutation.mutation_type == "change_lane_count":
        return f"Add capacity by changing a nearby road to {params['lane_count']} lane(s)."
    if mutation.mutation_type == "change_signal_plan":
        if params.get("mode") == "bus_priority":
            return "Give buses extra green-light priority at the selected intersection."
        return "Change the light timing plan at the selected intersection."
    if mutation.mutation_type == "increase_bus_service":
        return "Add more bus service on the busiest cross-town corridor to take cars off the road."
    if mutation.mutation_type == "build_light_rail_line":
        return "Add a light-rail corridor across the city to absorb busy car trips."
    return mutation.mutation_type.replace("_", " ").title()


def summarize_scenario(proposal: ScenarioProposal | None) -> Dict[str, Any]:
    if proposal is None:
        return {
            "title": "No layout change",
            "summary": "This run compares controllers on the same road network without changing the streets.",
            "bullets": ["No structural change was applied before running the controller."],
        }
    bullets = [summarize_mutation(mutation) for mutation in proposal.mutations]
    return {
        "title": proposal.title,
        "summary": proposal.intent,
        "bullets": bullets,
    }


def metric_delta(metric_name: str, value: float, baseline_value: float | None) -> Dict[str, Any]:
    if baseline_value in (None, 0):
        return {"direction": "neutral", "delta": None}
    better = METRIC_COPY.get(metric_name, {}).get("better", "lower")
    raw_delta = value - baseline_value
    if better == "higher":
        improved = raw_delta > 0
        pct = (raw_delta / baseline_value) * 100
    else:
        improved = raw_delta < 0
        pct = (-raw_delta / baseline_value) * 100
    return {
        "direction": "improved" if improved else "worse" if raw_delta != 0 else "neutral",
        "delta": round(pct, 1),
    }


def default_viewer_message() -> str:
    return "Run a few controllers first to see the comparison here."


def how_it_works_items() -> List[Dict[str, str]]:
    return [
        {
            "label": controller_copy(mode)["display"],
            "short": controller_copy(mode)["short"],
            "description": controller_copy(mode)["description"],
            "badge_color": controller_copy(mode)["badge_color"],
        }
        for mode in VISIBLE_CONTROLLER_MODES
    ]
