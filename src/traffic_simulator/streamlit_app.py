from __future__ import annotations

from io import BytesIO
import importlib.util
import time
from types import SimpleNamespace
from typing import Any, Dict, List
from urllib.parse import urlencode

import httpx
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw

from traffic_simulator.config import API_URL
from traffic_simulator.ui_text import (
    APP_SUBTITLE,
    APP_TITLE,
    VISIBLE_CONTROLLER_MODES,
    controller_copy,
    how_it_works_items,
    summarize_mutation,
)

NETWORK_TYPE_OPTIONS = {
    "synthetic": "Built-In Demo Grid",
    "osm": "Real Neighborhood Map",
}

TRAFFIC_LEVEL_OPTIONS = {
    "Light": 0.75,
    "City Rush": 1.0,
    "Heavy": 1.5,
    "Gridlock": 2.2,
}


def post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        response = httpx.post(f"{API_URL}{path}", json=payload, timeout=600.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(api_error_message(exc)) from exc
    except httpx.ReadTimeout as exc:
        raise RuntimeError("This run took too long to finish. Try the Built-In Demo Grid or fewer controllers.") from exc


def get_json(path: str) -> Any:
    try:
        response = httpx.get(f"{API_URL}{path}", timeout=180.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(api_error_message(exc)) from exc


def api_error_message(exc: httpx.HTTPStatusError) -> str:
    response = exc.response
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])
    return f"Request failed with status {response.status_code}."


def is_stale_context_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "unknown network:",
            "unknown demand profile:",
            "no demand profile for network",
            "unknown scenario:",
        )
    )


def real_map_available() -> bool:
    return importlib.util.find_spec("osmnx") is not None


def preview_for_payload(payload: Dict[str, Any]) -> bytes | None:
    if payload.get("source_type") != "synthetic":
        return None
    grid = payload.get("grid_config") or {}
    return make_grid_preview(int(grid.get("rows", 4)), int(grid.get("cols", 4)))


def restore_scenario_for_network(network: Dict[str, Any]) -> Dict[str, Any] | None:
    selected_template_key = st.session_state.get("selected_template_key")
    if not selected_template_key:
        st.session_state["scenario"] = None
        st.session_state["scenario_study"] = None
        return None
    if selected_template_key == "custom_helper":
        proposal_text = (st.session_state.get("proposal_text_input") or "").strip()
        if not proposal_text:
            st.session_state["scenario"] = None
            st.session_state["scenario_study"] = None
            return None
        scenario = post_json(
            "/scenarios/parse-proposal",
            {
                "network_id": network["network_id"],
                "demand_profile_id": network["demand_profile_id"],
                "proposal_text": proposal_text,
            },
        )
    else:
        templates = get_json(
            f"/scenarios/templates?network_id={network['network_id']}&demand_profile_id={network['demand_profile_id']}"
        )
        template = find_template(templates, selected_template_key)
        if template is None:
            st.session_state["scenario"] = None
            st.session_state["scenario_study"] = None
            return None
        scenario = create_scenario_from_template(network, template)
    st.session_state["scenario"] = scenario
    st.session_state["scenario_study"] = None
    return scenario


def recover_simulator_context(keep_scenario: bool = False) -> bool:
    payload = st.session_state.get("network_load_payload")
    if not payload:
        return False
    network = post_json("/networks/load", payload)
    st.session_state["network"] = network
    st.session_state["network_preview"] = preview_for_payload(payload)
    if keep_scenario:
        restore_scenario_for_network(network)
    else:
        st.session_state["scenario"] = None
        st.session_state["scenario_study"] = None
    st.session_state["ui_notice"] = {
        "kind": "info",
        "message": "The simulator restarted, so the city network was refreshed automatically.",
    }
    return True


def get_templates_with_recovery(network: Dict[str, Any], keep_scenario: bool = False) -> List[Dict[str, Any]]:
    path = f"/scenarios/templates?network_id={network['network_id']}&demand_profile_id={network['demand_profile_id']}"
    try:
        return get_json(path)
    except RuntimeError as exc:
        if is_stale_context_error(str(exc)) and recover_simulator_context(keep_scenario=keep_scenario):
            refreshed = st.session_state["network"]
            return get_json(
                f"/scenarios/templates?network_id={refreshed['network_id']}&demand_profile_id={refreshed['demand_profile_id']}"
            )
        raise


def inject_styles() -> None:
    st.markdown(
        """
        <style>
          .stApp {
            background:
              radial-gradient(circle at top left, rgba(34,211,238,0.08), transparent 28%),
              linear-gradient(180deg, #eef5fb 0%, #f8fbff 100%);
            color: #0f172a;
            font-family: "Avenir Next", "Inter", "Segoe UI", sans-serif;
          }
          .block-container {
            padding-top: 1.2rem;
            max-width: 1380px;
          }
          [data-testid="stHeader"] {
            background: transparent;
          }
          [data-testid="stSidebar"] {
            background: #f7fbff;
            border-left: 1px solid #d8e5f1;
          }
          [data-testid="stSidebar"] * {
            color: #0f172a;
          }
          .stMarkdown, .stText, label, .stCaption, .stAlert {
            color: #0f172a;
          }
          .stTextInput input,
          .stTextArea textarea,
          .stNumberInput input,
          div[data-baseweb="select"] > div,
          div[data-baseweb="input"] > div {
            background: #ffffff !important;
            color: #0f172a !important;
            border-radius: 14px !important;
            border: 1px solid #cbd5e1 !important;
            box-shadow: none !important;
          }
          .stTextArea textarea {
            min-height: 120px;
          }
          .stButton > button {
            width: 100%;
            min-height: 46px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 14px;
            border: 1px solid rgba(14, 165, 233, 0.36);
            background: linear-gradient(135deg, #0ea5e9, #22c55e);
            color: #ffffff;
            font-weight: 700;
            box-shadow: 0 10px 24px rgba(14, 165, 233, 0.16);
          }
          .stButton > button:hover {
            border-color: rgba(14, 165, 233, 0.48);
            filter: brightness(1.02);
          }
          .stButton > button:disabled {
            background: #cbd5e1;
            border-color: #cbd5e1;
            color: #64748b;
            box-shadow: none;
          }
          .stLinkButton a {
            width: 100%;
            min-height: 46px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 14px;
            border: 1px solid #cbd5e1;
            background: #ffffff;
            color: #0f172a;
            font-weight: 700;
            text-decoration: none;
          }
          .product-shell {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 16px 18px;
            border-radius: 24px;
            border: 1px solid rgba(103,232,249,0.14);
            background: linear-gradient(180deg, rgba(8,20,35,0.96), rgba(5,12,24,0.98));
            box-shadow: 0 20px 48px rgba(15,23,42,0.18);
            margin-bottom: 18px;
          }
          .product-title {
            font-family: "Iowan Old Style", "Palatino Linotype", serif;
            font-size: 2rem;
            font-weight: 700;
            color: #f0fbff;
          }
          .product-subtitle {
            color: #8fb2c7;
            margin-top: 4px;
          }
          .nav-pills {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
          }
          .nav-pill {
            text-decoration: none;
            color: #e6fbff;
            padding: 10px 14px;
            border-radius: 999px;
            border: 1px solid rgba(148,163,184,0.18);
            background: rgba(255,255,255,0.03);
          }
          .nav-pill.active {
            border-color: rgba(34,211,238,0.42);
            box-shadow: 0 0 18px rgba(34,211,238,0.12);
          }
          .hero-card, .glass-card {
            border-radius: 22px;
            border: 1px solid #dbe7f3;
            background: rgba(255,255,255,0.96);
            box-shadow: 0 18px 42px rgba(15,23,42,0.08);
            padding: 18px 20px;
          }
          .hero-eyebrow, .mini-eyebrow {
            color: #0ea5e9;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            font-size: 0.72rem;
            margin-bottom: 10px;
          }
          .hero-heading {
            font-family: "Iowan Old Style", "Palatino Linotype", serif;
            font-size: 2.5rem;
            line-height: 1.02;
            color: #0f172a;
            margin-bottom: 12px;
          }
          .hero-copy, .small-copy {
            color: #475569;
            line-height: 1.55;
          }
          .legend-grid {
            display: grid;
            gap: 12px;
          }
          .legend-row {
            display: grid;
            grid-template-columns: 12px 1fr;
            gap: 12px;
            align-items: start;
            padding: 10px 12px;
            border-radius: 16px;
            background: #f8fbff;
            border: 1px solid #e2e8f0;
          }
          .legend-dot {
            width: 12px;
            height: 12px;
            border-radius: 999px;
            margin-top: 5px;
          }
          .legend-label {
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 4px;
          }
          .run-card {
            border-radius: 18px;
            padding: 14px;
            background: #ffffff;
            border: 1px solid #e2e8f0;
            margin-bottom: 12px;
          }
          .run-title {
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 6px;
          }
          .run-meta {
            color: #475569;
            font-size: 0.92rem;
          }
          .metric-mini-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 12px;
          }
          .metric-mini {
            padding: 10px;
            border-radius: 14px;
            background: #f8fbff;
            border: 1px solid #e2e8f0;
          }
          .metric-mini-label {
            color: #64748b;
            font-size: 0.72rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
          }
          .metric-mini-value {
            font-size: 1.3rem;
            font-weight: 700;
            margin-top: 6px;
            color: #0f172a;
          }
          .improved {
            color: #15803d;
            font-weight: 700;
          }
          .worse {
            color: #b91c1c;
            font-weight: 700;
          }
          .neutral {
            color: #64748b;
            font-weight: 700;
          }
          .scenario-card {
            padding: 14px 16px;
            border-radius: 18px;
            background: #f8fbff;
            border: 1px solid #dbeafe;
            margin-top: 12px;
          }
          .scenario-title {
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 8px;
          }
          .preview-wrap {
            display: grid;
            place-items: center;
            border-radius: 18px;
            padding: 12px;
            border: 1px solid #e2e8f0;
            background: #f8fbff;
          }
          .helper-note {
            margin-top: 10px;
            color: #475569;
            line-height: 1.55;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def network_type_label(value: str) -> str:
    return NETWORK_TYPE_OPTIONS.get(value, value.replace("_", " ").title())


def traffic_level_label(scale: float) -> str:
    for label, value in TRAFFIC_LEVEL_OPTIONS.items():
        if abs(value - scale) < 1e-9:
            return label
    return f"{scale:.1f}x"


def render_header() -> None:
    st.markdown(
        f"""
        <div class="product-shell">
          <div>
            <div class="product-title">{APP_TITLE}</div>
            <div class="product-subtitle">{APP_SUBTITLE}</div>
          </div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <div class="nav-pills">
              <a class="nav-pill active" href="http://127.0.0.1:8501/">Operator Console</a>
              <a class="nav-pill" href="{API_URL}/demo/" target="_blank">Traffic Comparison Viewer</a>
              <a class="nav-pill" href="{API_URL}/demo/architecture.html" target="_blank">Overview and Documentation</a>
            </div>
            <a class="nav-pill active" href="{API_URL}/demo/" target="_blank" style="background:linear-gradient(135deg, rgba(34,211,238,0.18), rgba(34,197,94,0.18));border-color:rgba(34,211,238,0.32)">Open Traffic Comparison Viewer</a>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_legend_card() -> None:
    legend = "".join(
        f"""
        <div class="legend-row">
          <span class="legend-dot" style="background:{item['badge_color']}"></span>
          <div>
            <div class="legend-label">{item['label']}</div>
            <div class="small-copy">{item['description']}</div>
          </div>
        </div>
        """
        for item in how_it_works_items()
    )
    st.markdown(
        f"""
        <div class="glass-card">
          <div class="mini-eyebrow">How This Works</div>
          <div class="legend-grid">{legend}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def make_grid_preview(rows: int, cols: int) -> bytes:
    image = Image.new("RGB", (280, 220), "#071827")
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 36, 28, 244, 192
    for row in range(rows):
        y = top + (bottom - top) * row / max(1, rows - 1)
        draw.line((left, y, right, y), fill="#22D3EE", width=2)
    for col in range(cols):
        x = left + (right - left) * col / max(1, cols - 1)
        draw.line((x, top, x, bottom), fill="#22D3EE", width=2)
    for row in range(rows):
        for col in range(cols):
            x = left + (right - left) * col / max(1, cols - 1)
            y = top + (bottom - top) * row / max(1, rows - 1)
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#22C55E", outline="#E6FBFF")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def viewer_url(primary_run_id: str | None, comparison_run_id: str | None = None, tertiary_run_id: str | None = None) -> str:
    params = {}
    if primary_run_id:
        params["primary"] = primary_run_id
    if comparison_run_id:
        params["comparison"] = comparison_run_id
    if tertiary_run_id:
        params["tertiary"] = tertiary_run_id
    suffix = f"?{urlencode(params)}" if params else ""
    return f"{API_URL}/demo/{suffix}"


def open_viewer(
    primary_run_id: str | None,
    comparison_run_id: str | None = None,
    tertiary_run_id: str | None = None,
) -> None:
    url = viewer_url(primary_run_id, comparison_run_id, tertiary_run_id)
    components.html(
        f"""
        <script>
          window.open({url!r}, "_blank");
        </script>
        """,
        height=0,
    )


def metric_improvement(run: Dict[str, Any], baseline: Dict[str, Any] | None, metric_name: str = "avg_travel_time_s") -> str:
    if baseline is None:
        return '<span class="neutral">No basic controller baseline yet</span>'
    current_value = run["metrics"][metric_name]
    baseline_value = baseline["metrics"][metric_name]
    if baseline_value == 0:
        return '<span class="neutral">No baseline yet</span>'
    improved = current_value < baseline_value
    percent = abs((current_value - baseline_value) / baseline_value) * 100
    css_class = "improved" if improved else "worse"
    arrow = "↑" if improved else "↓"
    word = "better" if improved else "slower"
    return f'<span class="{css_class}">{arrow} {percent:.1f}% {word} than the Basic Fixed-Time Controller</span>'


def render_recent_runs(runs: List[Dict[str, Any]], network_id: str | None) -> None:
    if not runs:
        st.info("Run a few controllers first to see the comparison here.")
        return
    visible_runs = [run for run in runs if network_id is None or run["network_id"] == network_id][:6]
    baselines = {
        run["network_id"]: run
        for run in visible_runs
        if run["controller_mode"] == "fixed_time"
    }
    for run in visible_runs:
        baseline = baselines.get(run["network_id"])
        metrics = run["metrics"]
        cars_entered = metrics.get("started_car_trip_count")
        if cars_entered is None:
            total_trip_count = metrics.get("total_trip_count")
            bus_trip_count = metrics.get("bus_trip_count")
            if total_trip_count is not None and bus_trip_count is not None:
                cars_entered = max(0, total_trip_count - bus_trip_count)
            else:
                cars_entered = 0
        st.markdown(
            f"""
            <div class="run-card">
              <div class="run-title">{run['controller']['display']}</div>
              <div class="run-meta">{run['scenario']['title']}</div>
                <div class="metric-mini-grid">
                <div class="metric-mini"><div class="metric-mini-label">Average Travel Time</div><div class="metric-mini-value">{run['metrics']['avg_travel_time_s']:.2f}s</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Traffic Flow Score</div><div class="metric-mini-value">{run['metrics'].get('city_flow_score', 0):.1f}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Cars Entered The Map</div><div class="metric-mini-value">{cars_entered:.0f}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">People Moved</div><div class="metric-mini-value">{run['metrics'].get('people_moved', 0):.0f}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Cars That Finished</div><div class="metric-mini-value">{run['metrics']['throughput']:.0f}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Cars Off The Road</div><div class="metric-mini-value">{run['metrics'].get('cars_removed_from_roads', 0):.0f}</div></div>
              </div>
              <div style="margin-top:10px">{metric_improvement(run, baseline)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def run_selected_controllers(
    network: Dict[str, Any],
    scenario_id: str | None,
    controller_modes: List[str],
    seed: int,
    duration_s: int,
    allow_recovery: bool = True,
) -> List[Dict[str, Any]]:
    results = []
    status_box = st.empty()
    progress_rows = []
    progress_container = st.container()
    with progress_container:
        for mode in controller_modes:
            copy = controller_copy(mode)
            label = st.empty()
            bar = st.progress(0.0)
            label.caption(f"{copy['display']} is waiting to run.")
            progress_rows.append((copy, label, bar))
    for index, (mode, row) in enumerate(zip(controller_modes, progress_rows), start=1):
        copy, label, bar = row
        copy = controller_copy(mode)
        status_box.info(f"Running {copy['display']}...")
        label.caption(f"{copy['display']} started. Waiting for the simulation service to finish this run.")
        bar.progress(0.12)
        time.sleep(0.05)
        try:
            result = post_json(
                "/simulations/run",
                {
                    "network_id": network["network_id"],
                    "demand_profile_id": network["demand_profile_id"],
                    "controller_mode": mode,
                    "scenario_id": scenario_id,
                    "seed": seed,
                    "duration_s": duration_s,
                },
            )
        except RuntimeError as exc:
            if allow_recovery and is_stale_context_error(str(exc)) and recover_simulator_context(keep_scenario=bool(scenario_id)):
                status_box.info("The simulator restarted. Refreshing the city and retrying this controller comparison...")
                refreshed_network = st.session_state["network"]
                refreshed_scenario_id = st.session_state["scenario"]["scenario_id"] if scenario_id and st.session_state.get("scenario") else None
                return run_selected_controllers(
                    refreshed_network,
                    refreshed_scenario_id,
                    controller_modes,
                    seed,
                    duration_s,
                    allow_recovery=False,
                )
            raise
        results.append(result)
        bar.progress(1.0)
        label.caption(f"{copy['display']} finished.")
    status_box.success("All selected controller runs finished.")
    return results


def choose_viewer_runs(results: List[Dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    by_mode = {result["controller_mode"]: result["run_id"] for result in results}
    primary = by_mode.get("ga_optimized") or by_mode.get("max_pressure") or results[-1]["run_id"] if results else None
    comparison = by_mode.get("fixed_time") or by_mode.get("max_pressure") or (results[0]["run_id"] if results else None)
    if primary == comparison:
        comparison = next((result["run_id"] for result in results if result["run_id"] != primary), None)
    tertiary = next(
        (
            result["run_id"]
            for result in results
            if result["run_id"] not in {primary, comparison}
        ),
        None,
    )
    return primary, comparison, tertiary


def build_study_seeds(base_seed: int, count: int) -> List[int]:
    offsets = [0, 4, 9, 15, 22]
    return [base_seed + offsets[index] for index in range(min(count, len(offsets)))]


def format_metric_value(metric_name: str, value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if metric_name.endswith("_pct"):
        return f"{float(value):.1f}%"
    if "travel_time" in metric_name or "delay" in metric_name:
        return f"{float(value):.1f}s"
    if "queue" in metric_name:
        return f"{float(value):.1f}m"
    if "score" in metric_name:
        return f"{float(value):.1f}"
    return f"{float(value):.0f}"


def metric_change_text(metric_name: str, baseline_value: float | None, proposal_value: float | None) -> str:
    if baseline_value is None or proposal_value is None or baseline_value == 0:
        return "No baseline comparison yet"
    better = "lower" if metric_name in {"avg_travel_time_s", "total_delay_s", "avg_queue_len_m", "p95_travel_time_s"} else "higher"
    raw_delta = float(proposal_value) - float(baseline_value)
    improved = raw_delta < 0 if better == "lower" else raw_delta > 0
    delta_pct = abs(raw_delta) / abs(float(baseline_value)) * 100
    word = "better" if improved else "worse"
    arrow = "↑" if improved else "↓"
    return f"{arrow} {delta_pct:.1f}% {word} than the baseline city"


def create_scenario_from_template(network: Dict[str, Any], template: Dict[str, Any]) -> Dict[str, Any]:
    return post_json(
        "/scenarios",
        {
            "network_id": network["network_id"],
            "title": template["title"],
            "intent": template["intent"],
            "target_area": template.get("target_area", {}),
            "mutations": template["mutations"],
            "evaluation_horizon_s": 300,
            "objective": template.get("objective", "avg_travel_time_s"),
        },
    )


def find_template(templates: List[Dict[str, Any]], template_key: str) -> Dict[str, Any] | None:
    return next((template for template in templates if template["key"] == template_key), None)


def render_analyst_panel(
    study: Dict[str, Any] | None,
    network: Dict[str, Any] | None,
    last_results: List[Dict[str, Any]],
) -> None:
    def request_analyst_summary(question_text: str) -> Dict[str, Any]:
        if context_type == "study":
            return post_json(
                "/analysis/study-summary",
                {
                    "study": study,
                    "question": question_text,
                    "network_name": network["name"] if network else None,
                },
            )
        return post_json(
            "/analysis/run-summary",
            {
                "run_ids": [result["run_id"] for result in last_results],
                "question": question_text,
            },
        )

    def submit_analyst_question(question_text: str, *, auto: bool = False) -> None:
        response = request_analyst_summary(question_text)
        st.session_state["analyst_question_input"] = question_text
        if auto:
            st.session_state["analyst_messages"] = [
                {"role": "assistant", "content": response["answer"], "meta": response, "auto": True}
            ]
            return
        st.session_state.setdefault("analyst_messages", []).extend(
            [
                {"role": "user", "content": question_text},
                {"role": "assistant", "content": response["answer"], "meta": response},
            ]
        )

    context_type = None
    context_key = None
    if study:
        context_type = "study"
        context_key = f"study:{study.get('scenario_id')}:{','.join(str(seed) for seed in study.get('seeds', []))}"
    elif last_results:
        run_ids = [result["run_id"] for result in last_results]
        context_type = "runs"
        context_key = f"runs:{'|'.join(run_ids)}"

    if st.session_state.get("analyst_context_key") != context_key:
        st.session_state["analyst_context_key"] = context_key
        st.session_state["analyst_messages"] = []
        st.session_state["analyst_autoload_pending"] = bool(context_key)

    st.markdown("### 5. AI Traffic Analyst")
    if not context_type:
        st.info("Finish a proposal study or a replay batch first, then ask for a plain-English explanation here.")
        return

    st.caption("Ask for a plain-English readout of the current results. The answer stays grounded in the actual study or replay data.")

    if st.session_state.get("analyst_autoload_pending") and not st.session_state.get("analyst_messages"):
        opening_question = "In plain English, what happened here and what should the city do next?"
        with st.spinner("AI Traffic Analyst is reading the latest result..."):
            try:
                submit_analyst_question(opening_question, auto=True)
            except Exception as exc:  # pragma: no cover - UI wrapper
                st.error(str(exc))
            finally:
                st.session_state["analyst_autoload_pending"] = False

    quick_prompts = [
        "In plain English, what happened here?",
        "What should the city do next?",
        "What is the clearest takeaway?",
    ]
    quick_cols = st.columns(3)
    for column, prompt in zip(quick_cols, quick_prompts):
        if column.button(prompt, key=f"analyst-quick-{prompt}", width="stretch"):
            with st.spinner("AI Traffic Analyst is reading the latest result..."):
                try:
                    submit_analyst_question(prompt)
                except Exception as exc:  # pragma: no cover - UI wrapper
                    st.error(str(exc))

    with st.form("analyst-form"):
        question = st.text_input(
            "Ask a follow-up question",
            value=st.session_state.get("analyst_question_input", "What is the clearest takeaway from this result?"),
        )
        submitted = st.form_submit_button("Ask AI Traffic Analyst", width="stretch")

    if submitted and question.strip():
        with st.spinner("AI Traffic Analyst is reading the latest result..."):
            try:
                submit_analyst_question(question.strip())
            except Exception as exc:  # pragma: no cover - UI wrapper
                st.error(str(exc))

    if not st.session_state.get("analyst_messages"):
        st.info("Try “What should the city do next?” to get a concise recommendation.")
        return

    for message in st.session_state["analyst_messages"][-6:]:
        if message["role"] == "user":
            st.markdown(
                f"""
                <div class="scenario-card">
                  <div class="scenario-title">You asked</div>
                  <div class="small-copy">{message['content']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            meta = message.get("meta", {})
            source_label = "Grok via xAI" if meta.get("used_ai") else "deterministic fallback"
            heading = "Automatic Summary" if message.get("auto") else "AI Traffic Analyst"
            st.markdown(
                f"""
                <div class="run-card">
                  <div class="run-title">{heading}</div>
                  <div class="run-meta">Source: {source_label}</div>
                  <div class="small-copy" style="margin-top:8px; white-space:pre-line">{message['content']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_study_results(study: Dict[str, Any]) -> None:
    if not study:
        st.info("Pick a proposal study and run a baseline-vs-proposal batch to see citywide impact.")
        return
    objective = study.get("objective", "avg_travel_time_s")
    best_summary = None
    best_score = None
    for summary in study.get("controllers", []):
        baseline_value = summary["baseline_aggregate_metrics"].get(objective)
        proposal_value = summary["proposal_aggregate_metrics"].get(objective)
        if baseline_value is None or proposal_value is None:
            continue
        score = proposal_value - baseline_value
        if objective in {"avg_travel_time_s", "total_delay_s", "avg_queue_len_m", "p95_travel_time_s"}:
            score *= -1
        if best_score is None or score > best_score:
            best_score = score
            best_summary = summary
    if best_summary:
        st.markdown(
            f"""
            <div class="scenario-card">
              <div class="scenario-title">Best proposal result: {best_summary['controller']['display']}</div>
              <div class="small-copy">{metric_change_text(objective, best_summary['baseline_aggregate_metrics'].get(objective), best_summary['proposal_aggregate_metrics'].get(objective))}</div>
              <div class="small-copy" style="margin-top:6px">Objective tracked: {objective.replace('_', ' ').title()} across seeds {', '.join(str(seed) for seed in study.get('seeds', []))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    for summary in study.get("controllers", []):
        baseline_metrics = summary["baseline_aggregate_metrics"]
        proposal_metrics = summary["proposal_aggregate_metrics"]
        st.markdown(
            f"""
            <div class="run-card">
              <div class="run-title">{summary['controller']['display']}</div>
              <div class="run-meta">{metric_change_text(objective, baseline_metrics.get(objective), proposal_metrics.get(objective))}</div>
              <div class="metric-mini-grid">
                <div class="metric-mini"><div class="metric-mini-label">Baseline Travel Time</div><div class="metric-mini-value">{format_metric_value('avg_travel_time_s', baseline_metrics.get('avg_travel_time_s'))}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Proposal Travel Time</div><div class="metric-mini-value">{format_metric_value('avg_travel_time_s', proposal_metrics.get('avg_travel_time_s'))}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Travel Time Change</div><div class="metric-mini-value">{format_metric_value('avg_travel_time_s', proposal_metrics.get('avg_travel_time_s', 0) - baseline_metrics.get('avg_travel_time_s', 0))}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Baseline People Moved</div><div class="metric-mini-value">{format_metric_value('people_moved', baseline_metrics.get('people_moved'))}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Proposal People Moved</div><div class="metric-mini-value">{format_metric_value('people_moved', proposal_metrics.get('people_moved'))}</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Cars Off The Road</div><div class="metric-mini-value">{format_metric_value('cars_removed_from_roads', proposal_metrics.get('cars_removed_from_roads'))}</div></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


st.set_page_config(page_title=APP_TITLE, layout="wide")
inject_styles()
render_header()

if "network" not in st.session_state:
    st.session_state["network"] = None
if "scenario" not in st.session_state:
    st.session_state["scenario"] = None
if "last_results" not in st.session_state:
    st.session_state["last_results"] = []
if "network_preview" not in st.session_state:
    st.session_state["network_preview"] = None
if "network_load_payload" not in st.session_state:
    st.session_state["network_load_payload"] = None
if "network_type_input" not in st.session_state:
    st.session_state["network_type_input"] = "synthetic"
if "last_network_type" not in st.session_state:
    st.session_state["last_network_type"] = "synthetic"
if "network_name_input" not in st.session_state:
    st.session_state["network_name_input"] = "City Demo Grid"
if "place_query_input" not in st.session_state:
    st.session_state["place_query_input"] = "Midtown Manhattan, New York, USA"
if "proposal_text_input" not in st.session_state:
    st.session_state["proposal_text_input"] = "Replace the traffic light at the busy intersection with a roundabout and compare travel times"
if "scenario_study" not in st.session_state:
    st.session_state["scenario_study"] = None
if "selected_template_key" not in st.session_state:
    st.session_state["selected_template_key"] = None
if "ui_notice" not in st.session_state:
    st.session_state["ui_notice"] = None
if "analyst_messages" not in st.session_state:
    st.session_state["analyst_messages"] = []
if "analyst_context_key" not in st.session_state:
    st.session_state["analyst_context_key"] = None
if "analyst_question_input" not in st.session_state:
    st.session_state["analyst_question_input"] = "What is the clearest takeaway from this result?"
if "analyst_autoload_pending" not in st.session_state:
    st.session_state["analyst_autoload_pending"] = False

notice = st.session_state.pop("ui_notice")
if notice:
    getattr(st, notice.get("kind", "info"))(notice["message"])

st.markdown(
    """
    <div class="hero-card">
      <div class="hero-eyebrow">Operator Console</div>
      <div class="hero-heading">Simulation Control Panel</div>
      <div class="hero-copy">
        Load a compact city map, pick a street or transit proposal, run the baseline city against the modified city over several seeded simulations, then open a replay for the most useful comparison.
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

hero_meta, hero_actions = st.columns([1.15, 0.85], gap="large")
with hero_meta:
    render_legend_card()
with hero_actions:
    st.markdown("#### Quick Actions")
    st.caption("Jump straight to the most useful demo flows.")
    if st.button("Compare All Three Controllers", width="stretch", disabled=not st.session_state["network"]):
        try:
            results = run_selected_controllers(
                st.session_state["network"],
                st.session_state["scenario"]["scenario_id"] if st.session_state["scenario"] else None,
                VISIBLE_CONTROLLER_MODES,
                seed=7,
                duration_s=180,
            )
            st.session_state["last_results"] = results
            primary, comparison, tertiary = choose_viewer_runs(results)
            open_viewer(primary, comparison, tertiary)
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))
    if st.button("Run Accident Recovery Study", width="stretch", disabled=not st.session_state["network"]):
        try:
            templates = get_templates_with_recovery(st.session_state["network"], keep_scenario=False)
            template = find_template(templates, "incident_detour")
            if template is None:
                raise RuntimeError("The accident-response study is not available for this network.")
            st.session_state["scenario"] = create_scenario_from_template(st.session_state["network"], template)
            st.session_state["selected_template_key"] = template["key"]
            st.session_state["scenario_study"] = None
            st.success("Accident-response study loaded.")
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))
    st.link_button("Open Traffic Comparison Viewer", f"{API_URL}/demo/", use_container_width=True)

left, center, right = st.columns([1.0, 1.35, 1.05], gap="large")

with left:
    st.markdown("### 1. Load a City Network")
    source_type = st.selectbox(
        "Network Type",
        ["synthetic", "osm"],
        format_func=network_type_label,
        help="Pick the built-in demo grid or load a real neighborhood map.",
        key="network_type_input",
    )
    if source_type != st.session_state.get("last_network_type"):
        current_name = (st.session_state.get("network_name_input") or "").strip()
        if source_type == "osm" and current_name in {"", "City Demo Grid"}:
            st.session_state["network_name_input"] = st.session_state.get("place_query_input", "Neighborhood Demo")
        if source_type == "synthetic" and current_name in {"", st.session_state.get("place_query_input", "")}:
            st.session_state["network_name_input"] = "City Demo Grid"
        st.session_state["last_network_type"] = source_type
    name = st.text_input("Network Name", key="network_name_input")
    seed = st.number_input("Random Seed", min_value=1, value=7)
    traffic_level = st.select_slider("Traffic Level", options=list(TRAFFIC_LEVEL_OPTIONS.keys()), value="City Rush")
    traffic_scale = TRAFFIC_LEVEL_OPTIONS[traffic_level]
    rows, cols = 4, 4
    if source_type == "synthetic":
        rows = st.slider("Grid Rows", min_value=3, max_value=6, value=4)
        cols = st.slider("Grid Columns", min_value=3, max_value=6, value=4)
        load_payload = {
            "source_type": "synthetic",
            "name": name,
            "seed": int(seed),
            "traffic_scale": traffic_scale,
            "grid_config": {"rows": rows, "cols": cols},
        }
        st.caption("Best for a fast demo. This creates a simple city-style grid you can compare immediately.")
    else:
        place_query = st.text_input("Neighborhood to Load", key="place_query_input")
        if (st.session_state.get("network_name_input") or "").strip() in {"", "City Demo Grid"}:
            st.session_state["network_name_input"] = place_query
            name = st.session_state["network_name_input"]
        load_payload = {
            "source_type": "osm",
            "name": name,
            "seed": int(seed),
            "traffic_scale": traffic_scale,
            "osm_area": {"place_query": place_query},
        }
        st.caption("Type a normal place name. The app loads a compact demo-sized section of that neighborhood.")
        if real_map_available():
            st.caption("Real neighborhood imports can take 20-60 seconds depending on the area size.")
        else:
            st.warning("Real neighborhood import is not available in this environment yet.")
    load_button_label = "Load This Network" if source_type == "synthetic" else "Load This Neighborhood Map"
    if st.button(load_button_label, width="stretch"):
        try:
            with st.spinner("Loading road network..."):
                st.session_state["network"] = post_json("/networks/load", load_payload)
            st.session_state["network_load_payload"] = load_payload
            st.session_state["network_preview"] = preview_for_payload(load_payload)
            st.session_state["scenario"] = None
            st.session_state["scenario_study"] = None
            st.session_state["selected_template_key"] = None
            st.session_state["ui_notice"] = {"kind": "success", "message": "Network loaded and ready."}
            st.rerun()
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))
    if st.session_state["network"]:
        network = st.session_state["network"]
        if st.session_state["network_preview"] is not None:
            st.image(st.session_state["network_preview"])
            st.caption("Built-in grid preview")
        st.markdown(
            f"""
            <div class="scenario-card">
              <div class="scenario-title">{network['name']}</div>
              <div class="small-copy">Network type: {network_type_label(network['source_type'])} | Intersections: {network['node_count']} | Road segments: {network['edge_count']}</div>
              {f"<div class='small-copy' style='margin-top:6px'>Neighborhood loaded: {network['place_query']}</div>" if network.get('place_query') else ""}
              <div class="small-copy" style="margin-top:6px">Traffic level: {traffic_level_label(network.get('traffic_scale', 1.0))} | Planned cars: {network.get('planned_car_trip_count', 0)} | Planned buses: {network.get('planned_bus_trip_count', 0)}</div>
              <div class="small-copy" style="margin-top:6px">Simulated city inputs: {network.get('city_input_count', 0)} feeds | Scheduled transit lines: {network.get('bus_route_count', 0)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("These counts drive the city study below. The proposal studies reuse the same traffic pattern across baseline and modified city runs.")

with center:
    st.markdown("### 2. Proposal Simulation Lab")
    st.caption("Pick a city proposal, then run a baseline-vs-proposal study across multiple seeds so the result feels like a real planning exercise.")
    templates: List[Dict[str, Any]] = []
    if st.session_state["network"]:
        try:
            templates = get_templates_with_recovery(st.session_state["network"], keep_scenario=bool(st.session_state["scenario"]))
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))
    template_tab, helper_tab = st.tabs(["Recommended City Studies", "Plain-English Helper"])
    with template_tab:
        if not st.session_state["network"]:
            st.info("Load a network first so the app can recommend realistic street and transit studies for that city.")
        else:
            template_cols = st.columns(2, gap="large")
            for index, template in enumerate(templates):
                with template_cols[index % 2]:
                    st.markdown(f"#### {template['title']}")
                    st.caption(f"{template['category']} study")
                    st.write(template["summary"])
                    st.caption(f"Watch for: {template['what_to_watch']}")
                    if st.button("Use This Study", key=f"template-{template['key']}", width="stretch"):
                        try:
                            st.session_state["scenario"] = create_scenario_from_template(st.session_state["network"], template)
                            st.session_state["selected_template_key"] = template["key"]
                            st.session_state["scenario_study"] = None
                            st.success(f"Loaded study: {template['title']}")
                        except Exception as exc:  # pragma: no cover - UI wrapper
                            if is_stale_context_error(str(exc)) and recover_simulator_context(keep_scenario=False):
                                st.session_state["scenario"] = create_scenario_from_template(st.session_state["network"], template)
                                st.session_state["selected_template_key"] = template["key"]
                                st.session_state["scenario_study"] = None
                                st.success(f"Loaded study: {template['title']}")
                            else:
                                st.error(str(exc))
            st.caption("These are structured, repeatable proposal studies generated from the currently loaded city network.")
    with helper_tab:
        st.caption("Use this when you want the app to translate a custom idea into a structured study. This is a helper, not the main workflow.")
        st.text_area(
            "Describe the change you want to test (in plain English)",
            key="proposal_text_input",
            placeholder="Replace the traffic light at the busy intersection with a roundabout and compare travel times",
            height=120,
            help="Describe the road or transit change in normal language. The helper will turn it into a structured study.",
        )
        if st.button("Translate My Idea Into a Study", width="stretch", disabled=not st.session_state["network"]):
            try:
                st.session_state["scenario"] = post_json(
                    "/scenarios/parse-proposal",
                    {
                        "network_id": st.session_state["network"]["network_id"],
                        "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                        "proposal_text": st.session_state["proposal_text_input"],
                    },
                )
                st.session_state["selected_template_key"] = "custom_helper"
                st.session_state["scenario_study"] = None
                st.success("Custom study created.")
            except Exception as exc:  # pragma: no cover - UI wrapper
                if is_stale_context_error(str(exc)) and recover_simulator_context(keep_scenario=False):
                    st.session_state["scenario"] = post_json(
                        "/scenarios/parse-proposal",
                        {
                            "network_id": st.session_state["network"]["network_id"],
                            "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                            "proposal_text": st.session_state["proposal_text_input"],
                        },
                    )
                    st.session_state["selected_template_key"] = "custom_helper"
                    st.session_state["scenario_study"] = None
                    st.success("Custom study created.")
                else:
                    st.error(str(exc))

    if st.session_state["scenario"]:
        scenario = st.session_state["scenario"]
        bullets = "".join(
            f"<li>{summarize_mutation(SimpleNamespace(**mutation))}</li>"
            for mutation in scenario["mutations"]
        )
        st.markdown(
            f"""
            <div class="scenario-card">
              <div class="scenario-title">Active Study: {scenario['title']}</div>
              <div class="small-copy" style="margin-bottom:8px">This proposal will be tested against the unchanged city using the same traffic demand and repeatable seeds.</div>
              <ul>{bullets}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        study_modes = st.multiselect(
            "Controllers to evaluate in the study",
            options=VISIBLE_CONTROLLER_MODES,
            default=VISIBLE_CONTROLLER_MODES,
            format_func=lambda mode: controller_copy(mode)["display"],
        )
        study_seed_count = st.radio("Repeat runs", options=[3, 5], horizontal=True, format_func=lambda value: f"{value} seeded runs")
        study_duration_s = st.slider("Study Length (seconds)", min_value=120, max_value=420, value=180, step=30)
        study_seeds = build_study_seeds(int(seed), study_seed_count)
        st.caption(f"Study seeds: {', '.join(str(item) for item in study_seeds)}")
        study_col_a, study_col_b = st.columns(2)
        if study_col_a.button("Run Baseline vs Proposal Study", width="stretch", disabled=not study_modes):
            try:
                with st.spinner("Running the baseline city and the proposal city across repeated simulations..."):
                    st.session_state["scenario_study"] = post_json(
                        f"/scenarios/{scenario['scenario_id']}/study",
                        {
                            "network_id": st.session_state["network"]["network_id"],
                            "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                            "controller_modes": study_modes,
                            "seeds": study_seeds,
                            "duration_s": study_duration_s,
                        },
                    )
                st.success("Proposal study finished.")
            except Exception as exc:  # pragma: no cover - UI wrapper
                if is_stale_context_error(str(exc)) and recover_simulator_context(keep_scenario=True):
                    refreshed_scenario = st.session_state["scenario"]
                    with st.spinner("Running the baseline city and the proposal city across repeated simulations..."):
                        st.session_state["scenario_study"] = post_json(
                            f"/scenarios/{refreshed_scenario['scenario_id']}/study",
                            {
                                "network_id": st.session_state["network"]["network_id"],
                                "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                                "controller_modes": study_modes,
                                "seeds": study_seeds,
                                "duration_s": study_duration_s,
                            },
                        )
                    st.success("Proposal study finished.")
                else:
                    st.error(str(exc))
        if study_col_b.button("Run One Replay For The Viewer", width="stretch"):
            try:
                results = run_selected_controllers(
                    st.session_state["network"],
                    scenario["scenario_id"],
                    study_modes or VISIBLE_CONTROLLER_MODES,
                    seed=int(seed),
                    duration_s=study_duration_s,
                )
                st.session_state["last_results"] = results
                primary, comparison, tertiary = choose_viewer_runs(results)
                open_viewer(primary, comparison, tertiary)
            except Exception as exc:  # pragma: no cover - UI wrapper
                st.error(str(exc))

    st.markdown("### 3. Controller Replay Sandbox")
    st.caption("Use this when you want a single side-by-side replay in the viewer instead of a full proposal study.")
    controller_columns = st.columns(3)
    selected_modes: List[str] = []
    for column, mode in zip(controller_columns, VISIBLE_CONTROLLER_MODES):
        copy = controller_copy(mode)
        if column.checkbox(copy["display"], value=True, key=f"replay-{mode}", help=copy["description"]):
            selected_modes.append(mode)
        column.caption(copy["description"])
    duration_s = st.slider("Replay Length (seconds)", min_value=120, max_value=360, value=180, step=30)
    if st.button("Run Selected Controllers For Replay", width="stretch", disabled=not st.session_state["network"] or not selected_modes):
        try:
            results = run_selected_controllers(
                st.session_state["network"],
                st.session_state["scenario"]["scenario_id"] if st.session_state["scenario"] else None,
                selected_modes,
                seed=int(seed),
                duration_s=duration_s,
            )
            st.session_state["last_results"] = results
            primary, comparison, tertiary = choose_viewer_runs(results)
            open_viewer(primary, comparison, tertiary)
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))

with right:
    st.markdown("### 4. Study Results")
    render_study_results(st.session_state["scenario_study"])
    render_analyst_panel(
        st.session_state["scenario_study"],
        st.session_state["network"],
        st.session_state["last_results"],
    )
    if st.session_state["scenario_study"]:
        viewer = st.session_state["scenario_study"].get("recommended_viewer", {})
        if viewer.get("primary"):
            st.link_button(
                "Open Recommended Proposal Replay",
                viewer_url(viewer.get("primary"), viewer.get("comparison"), viewer.get("tertiary")),
                use_container_width=True,
            )
    st.markdown("### Recent Runs")
    try:
        runs = get_json("/runs")
        render_recent_runs(runs, st.session_state["network"]["network_id"] if st.session_state["network"] else None)
        if st.session_state["last_results"]:
            primary, comparison, tertiary = choose_viewer_runs(st.session_state["last_results"])
            st.link_button("Open Latest Replay", viewer_url(primary, comparison, tertiary), use_container_width=True)
    except Exception as exc:  # pragma: no cover - UI wrapper
        st.error(str(exc))
