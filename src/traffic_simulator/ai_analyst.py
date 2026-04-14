from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import httpx

from traffic_simulator.config import BASE_DIR
from traffic_simulator.ui_text import METRIC_COPY


ANALYST_METRICS = [
    "city_flow_score",
    "avg_travel_time_s",
    "throughput",
    "people_moved",
    "avg_queue_len_m",
    "bus_throughput",
    "cars_removed_from_roads",
    "rail_riders_served",
]

XAI_MODEL_FALLBACKS = ("grok-4.20-reasoning", "grok-4-fast-reasoning")


def analyst_status() -> Dict[str, Any]:
    settings = _resolve_ai_settings()
    return {
        "label": "AI Traffic Analyst",
        "provider": "xAI",
        "model": settings["model"],
        "available": bool(settings["api_key"]),
        "using_seldon_key": settings["using_seldon_key"],
    }


def summarize_study_with_ai(study: Dict[str, Any], question: str, network_name: str | None = None) -> Dict[str, Any]:
    prompt = (question or "").strip() or "Summarize this city study in plain English and tell me what the city should do."
    context = _compact_study_context(study, network_name)
    fallback = _fallback_study_summary(context, prompt)
    return _complete_summary(
        prompt=prompt,
        context=context,
        fallback_text=fallback,
        system_prompt=(
            "You are the AI Traffic Analyst for a city traffic demo. "
            "Explain results in plain English for a non-expert. "
            "Be decisive, concise, and evidence-based. "
            "Start with the recommendation, then give 2-4 short bullets or sentences of evidence. "
            "Do not mention raw JSON, APIs, or internal implementation details. "
            "If the evidence is mixed, say so clearly."
        ),
    )


def summarize_runs_with_ai(run_payloads: List[Dict[str, Any]], question: str) -> Dict[str, Any]:
    prompt = (question or "").strip() or "In plain English, what happened here and which controller should I pay attention to?"
    context = _compact_run_context(run_payloads)
    fallback = _fallback_run_summary(context, prompt)
    return _complete_summary(
        prompt=prompt,
        context=context,
        fallback_text=fallback,
        system_prompt=(
            "You are the AI Traffic Analyst for a city traffic demo. "
            "Explain a controller comparison in plain English for a non-expert. "
            "Keep it short, concrete, and immediately useful. "
            "Say which controller looks best, what changed on the streets or transit side, and what the user should notice in the replay. "
            "Avoid jargon and do not invent certainty."
        ),
    )


def _complete_summary(
    *,
    prompt: str,
    context: Dict[str, Any],
    fallback_text: str,
    system_prompt: str,
) -> Dict[str, Any]:
    settings = _resolve_ai_settings()
    if not settings["api_key"] or settings["external_disabled"]:
        return {
            "answer": fallback_text,
            "used_ai": False,
            "provider": "fallback",
            "model": "deterministic-summary",
            "fallback_reason": "external_ai_disabled" if settings["external_disabled"] else "missing_api_key",
        }

    try:
        answer, model = _call_xai_summary(prompt=prompt, context=context, settings=settings, system_prompt=system_prompt)
        return {
            "answer": answer,
            "used_ai": True,
            "provider": "xai",
            "model": model,
            "fallback_reason": None,
        }
    except Exception:
        return {
            "answer": fallback_text,
            "used_ai": False,
            "provider": "fallback",
            "model": "deterministic-summary",
            "fallback_reason": "upstream_request_failed",
        }


def _call_xai_summary(*, prompt: str, context: Dict[str, Any], settings: Dict[str, Any], system_prompt: str) -> tuple[str, str]:
    url = f"{settings['base_url'].rstrip('/')}/chat/completions"
    last_error: Exception | None = None
    candidate_models = list(dict.fromkeys([settings["model"], *XAI_MODEL_FALLBACKS]))
    for model in candidate_models:
        payload = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": 420,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{prompt}\n\n"
                        "Traffic context:\n"
                        f"{json.dumps(context, indent=2)}"
                    ),
                },
            ],
            "stream": False,
        }
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=12.0,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if response.status_code == 400 and "model not found" in response.text.lower():
                continue
            raise
        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            raise RuntimeError("No completion choices returned.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip(), model
        if isinstance(content, list):
            text_parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            text = "\n".join(part for part in text_parts if part).strip()
            if text:
                return text, model
        raise RuntimeError("No summary text returned.")
    if last_error is not None:
        raise last_error
    raise RuntimeError("No usable xAI model was available.")


@lru_cache(maxsize=1)
def _resolve_ai_settings() -> Dict[str, Any]:
    env = _read_env_file(_seldon_env_path())
    api_key = _first_non_empty(
        os.getenv("TRAFFIC_XAI_API_KEY"),
        os.getenv("XAI_API_KEY"),
        env.get("XAI_API_KEY"),
        env.get("SELDON_VALIDATOR_API_KEY"),
    )
    model = _first_non_empty(
        os.getenv("TRAFFIC_AI_MODEL"),
        os.getenv("SELDON_VALIDATOR_MODEL"),
        env.get("SELDON_VALIDATOR_MODEL"),
        "grok-4.20-reasoning",
    )
    base_url = _first_non_empty(
        os.getenv("TRAFFIC_AI_BASE_URL"),
        env.get("SELDON_MODEL_API_BASE"),
        "https://api.x.ai/v1",
    )
    using_seldon_key = bool(not os.getenv("TRAFFIC_XAI_API_KEY") and not os.getenv("XAI_API_KEY") and api_key)
    return {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "using_seldon_key": using_seldon_key,
        "external_disabled": bool(os.getenv("PYTEST_CURRENT_TEST")),
    }


def _seldon_env_path() -> Path:
    return BASE_DIR.parents[1] / "seldon" / ".env"


def _read_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metric_copy(metric_name: str) -> str:
    return METRIC_COPY.get(metric_name, {}).get("label", metric_name.replace("_", " ").title())


def _featured_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return {
        metric_name: round(float(metrics[metric_name]), 2)
        for metric_name in ANALYST_METRICS
        if metric_name in metrics and isinstance(metrics[metric_name], (int, float))
    }


def _compact_study_context(study: Dict[str, Any], network_name: str | None = None) -> Dict[str, Any]:
    controllers = []
    for summary in study.get("controllers", []):
        controllers.append(
            {
                "controller": summary["controller"]["display"],
                "baseline": _featured_metrics(summary.get("baseline_aggregate_metrics", {})),
                "proposal": _featured_metrics(summary.get("proposal_aggregate_metrics", {})),
                "delta": _featured_metrics(summary.get("delta_metrics", {})),
            }
        )
    return {
        "network_name": network_name,
        "scenario_title": study.get("scenario_title"),
        "objective": _metric_copy(study.get("objective", "avg_travel_time_s")),
        "seeds": study.get("seeds", []),
        "controllers": controllers,
    }


def _compact_run_context(run_payloads: List[Dict[str, Any]]) -> Dict[str, Any]:
    network_summary = run_payloads[0].get("network_summary", {}) if run_payloads else {}
    scenario = run_payloads[0].get("scenario", {}) if run_payloads else {}
    runs = []
    for payload in run_payloads:
        runs.append(
            {
                "controller": payload["controller"]["display"],
                "metrics": _featured_metrics(payload.get("metrics", {})),
                "scenario_title": payload.get("scenario", {}).get("title"),
            }
        )
    return {
        "network_name": network_summary.get("name"),
        "map_type": network_summary.get("source_type"),
        "planned_car_trips": network_summary.get("planned_car_trip_count"),
        "planned_bus_trips": network_summary.get("planned_bus_trip_count"),
        "bus_routes": network_summary.get("bus_route_count"),
        "rail_corridors": network_summary.get("rail_line_count"),
        "scenario_title": scenario.get("title"),
        "scenario_summary": scenario.get("summary"),
        "scenario_bullets": scenario.get("bullets", []),
        "runs": runs,
    }


def _fallback_study_summary(context: Dict[str, Any], question: str) -> str:
    controllers = context.get("controllers", [])
    if not controllers:
        return "I do not have enough study data yet. Run a baseline-versus-proposal study first, then ask again."
    objective = context.get("objective") or "Average Travel Time"
    best = _best_controller_for_study(controllers, objective)
    if best is None:
        return "The study ran, but I could not identify a clear winner from the recorded metrics."
    proposal = best["proposal"]
    baseline = best["baseline"]
    lines = [
        f"Recommendation: {best['controller']} is the clearest choice for this study.",
        f"It performed best on {objective.lower()} when the city switched from the baseline layout to {context.get('scenario_title', 'the proposal')}.",
    ]
    if "avg_travel_time_s" in proposal and "avg_travel_time_s" in baseline:
        delta = proposal["avg_travel_time_s"] - baseline["avg_travel_time_s"]
        direction = "down" if delta < 0 else "up"
        lines.append(f"Average travel time moved {direction} by {abs(delta):.1f} seconds under that controller.")
    if "people_moved" in proposal:
        lines.append(f"People moved reached about {proposal['people_moved']:.0f} in the proposal runs.")
    if "cars_removed_from_roads" in proposal and proposal["cars_removed_from_roads"] > 0:
        lines.append(f"The proposal also took roughly {proposal['cars_removed_from_roads']:.0f} cars off the road.")
    if "takeaway" in question.lower():
        lines.append("The clearest takeaway is whether the proposal improved travel times without giving up how many people the network can move.")
    return " ".join(lines)


def _fallback_run_summary(context: Dict[str, Any], question: str) -> str:
    runs = context.get("runs", [])
    if not runs:
        return "I do not have enough replay data yet. Pick a few completed runs, then ask again."
    best = _best_run_for_comparison(runs)
    question_lower = question.lower()
    if "what should the city do" in question_lower or "do next" in question_lower:
        recommendation = f"Recommendation: The city should use {best['controller']} for this setup."
    else:
        recommendation = f"Recommendation: {best['controller']} looks strongest in this comparison."
    lines = [
        recommendation,
    ]
    if context.get("scenario_title") and context["scenario_title"] != "No layout change":
        lines.append(f"The street change being tested is {context['scenario_title'].lower()}.")
    if "city_flow_score" in best["metrics"]:
        lines.append(f"It has the best traffic flow score at {best['metrics']['city_flow_score']:.1f}.")
    if "avg_travel_time_s" in best["metrics"]:
        lines.append(f"Its average travel time is {best['metrics']['avg_travel_time_s']:.1f} seconds.")
    if "throughput" in best["metrics"]:
        lines.append(f"It finishes about {best['metrics']['throughput']:.0f} car trips in the run window.")
    if "takeaway" in question_lower:
        lines.append("The clearest takeaway is that the winner is moving more traffic with less delay than the alternatives.")
    if "what should i notice" in question_lower or "replay" in question_lower:
        lines.append("In the replay, watch for the winning controller keeping more roads cool-colored and clearing the heaviest queue pockets faster.")
    return " ".join(lines)


def _best_controller_for_study(controllers: List[Dict[str, Any]], objective_label: str) -> Dict[str, Any] | None:
    if not controllers:
        return None
    lower_is_better = objective_label.lower() in {
        "average travel time",
        "total delay",
        "average queue length",
        "worst-case travel time",
    }

    def score(summary: Dict[str, Any]) -> float:
        objective_key = _objective_metric_key(objective_label)
        proposal_value = summary["proposal"].get(objective_key)
        baseline_value = summary["baseline"].get(objective_key)
        if proposal_value is None:
            return float("-inf")
        if baseline_value is None:
            return -proposal_value if lower_is_better else proposal_value
        delta = baseline_value - proposal_value if lower_is_better else proposal_value - baseline_value
        return delta

    return max(controllers, key=score)


def _best_run_for_comparison(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    if any("city_flow_score" in run["metrics"] for run in runs):
        return max(runs, key=lambda run: (run["metrics"].get("city_flow_score", float("-inf")), -run["metrics"].get("avg_travel_time_s", 0.0)))
    return min(runs, key=lambda run: run["metrics"].get("avg_travel_time_s", float("inf")))


def _objective_metric_key(objective_label: str) -> str:
    normalized = objective_label.lower()
    reverse = {
        "average travel time": "avg_travel_time_s",
        "cars that finished": "throughput",
        "people moved": "people_moved",
        "total delay": "total_delay_s",
        "average queue length": "avg_queue_len_m",
        "worst-case travel time": "p95_travel_time_s",
        "city flow score": "city_flow_score",
    }
    return reverse.get(normalized, "avg_travel_time_s")
