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


def real_map_available() -> bool:
    return importlib.util.find_spec("osmnx") is not None


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
              <a class="nav-pill" href="{API_URL}/demo/architecture.html" target="_blank">Architecture</a>
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


def viewer_url(primary_run_id: str | None, comparison_run_id: str | None = None) -> str:
    params = {}
    if primary_run_id:
        params["primary"] = primary_run_id
    if comparison_run_id:
        params["comparison"] = comparison_run_id
    suffix = f"?{urlencode(params)}" if params else ""
    return f"{API_URL}/demo/{suffix}"


def open_viewer(primary_run_id: str | None, comparison_run_id: str | None = None) -> None:
    url = viewer_url(primary_run_id, comparison_run_id)
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
        st.markdown(
            f"""
            <div class="run-card">
              <div class="run-title">{run['controller']['display']}</div>
              <div class="run-meta">{run['scenario']['title']}</div>
              <div class="metric-mini-grid">
                <div class="metric-mini"><div class="metric-mini-label">Average Travel Time</div><div class="metric-mini-value">{run['metrics']['avg_travel_time_s']:.2f}s</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Total Delay</div><div class="metric-mini-value">{run['metrics']['total_delay_s']:.0f}s</div></div>
                <div class="metric-mini"><div class="metric-mini-label">Cars Through</div><div class="metric-mini-value">{run['metrics']['throughput']:.0f}</div></div>
              </div>
              <div style="margin-top:10px">{metric_improvement(run, baseline)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def run_selected_controllers(network: Dict[str, Any], scenario_id: str | None, controller_modes: List[str], seed: int, duration_s: int) -> List[Dict[str, Any]]:
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
        results.append(result)
        bar.progress(1.0)
        label.caption(f"{copy['display']} finished.")
    status_box.success("All selected controller runs finished.")
    return results


def choose_viewer_runs(results: List[Dict[str, Any]]) -> tuple[str | None, str | None]:
    by_mode = {result["controller_mode"]: result["run_id"] for result in results}
    primary = by_mode.get("ga_optimized") or by_mode.get("max_pressure") or results[-1]["run_id"] if results else None
    comparison = by_mode.get("fixed_time") or by_mode.get("max_pressure") or (results[0]["run_id"] if results else None)
    if primary == comparison:
        comparison = next((result["run_id"] for result in results if result["run_id"] != primary), None)
    return primary, comparison


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

hero_left, hero_right = st.columns([1.55, 1.0], gap="large")
with hero_left:
    st.markdown(
        """
        <div class="hero-card">
          <div class="hero-eyebrow">Operator Console</div>
          <div class="hero-heading">See how different smart controllers improve traffic</div>
          <div class="hero-copy">
            Load a small city network, describe a street change in plain English, and compare the three smart controllers with one click.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hero_right:
    render_legend_card()

with st.sidebar:
    st.markdown('<div class="mini-eyebrow">Quick Actions</div>', unsafe_allow_html=True)
    st.caption("Fast ways to produce a clean before-and-after comparison.")
    if st.button("Compare All Three Controllers", width="stretch", disabled=not st.session_state["network"]):
        results = run_selected_controllers(
            st.session_state["network"],
            st.session_state["scenario"]["scenario_id"] if st.session_state["scenario"] else None,
            VISIBLE_CONTROLLER_MODES,
            seed=7,
            duration_s=300,
        )
        st.session_state["last_results"] = results
        primary, comparison = choose_viewer_runs(results)
        open_viewer(primary, comparison)
    if st.button("Add an accident and see how the system reacts", width="stretch", disabled=not st.session_state["network"]):
        st.session_state["scenario"] = post_json(
            "/scenarios/parse-proposal",
            {
                "network_id": st.session_state["network"]["network_id"],
                "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                "proposal_text": "Close the busiest road because of an accident and compare travel times",
            },
        )
        results = run_selected_controllers(
            st.session_state["network"],
            st.session_state["scenario"]["scenario_id"],
            ["fixed_time", "max_pressure"],
            seed=7,
            duration_s=300,
        )
        st.session_state["last_results"] = results
        primary, comparison = choose_viewer_runs(results)
        open_viewer(primary, comparison)
    st.link_button("Open Traffic Comparison Viewer", f"{API_URL}/demo/", use_container_width=True)

left, center, right = st.columns([1.05, 1.25, 1.2], gap="large")

with left:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("#### Load Network")
    source_type = st.selectbox(
        "Network Type",
        ["synthetic", "osm"],
        format_func=network_type_label,
        help="Pick the built-in demo grid or load a real neighborhood map.",
    )
    name = st.text_input("Network Name", value="City Demo Grid")
    seed = st.number_input("Random Seed", min_value=1, value=7)
    rows, cols = 4, 4
    if source_type == "synthetic":
        rows = st.slider("Grid Rows", min_value=3, max_value=6, value=4)
        cols = st.slider("Grid Columns", min_value=3, max_value=6, value=4)
        load_payload = {
            "source_type": "synthetic",
            "name": name,
            "seed": int(seed),
            "grid_config": {"rows": rows, "cols": cols},
        }
        st.caption("Best for a fast demo. This creates a simple city-style grid you can compare immediately.")
    else:
        place_query = st.text_input("Neighborhood to Load", value="Lower Manhattan, New York, USA")
        load_payload = {
            "source_type": "osm",
            "name": name,
            "seed": int(seed),
            "osm_area": {"place_query": place_query},
        }
        st.caption("Type a normal place name. Example: Lower Manhattan, New York, USA.")
        if real_map_available():
            st.caption("Real neighborhood imports can take 20-60 seconds depending on the area size.")
        else:
            st.warning("Real neighborhood import is not available in this environment yet.")
    if st.button("Load This Network", width="stretch"):
        try:
            with st.spinner("Loading road network..."):
                st.session_state["network"] = post_json("/networks/load", load_payload)
            st.session_state["network_preview"] = make_grid_preview(rows, cols) if source_type == "synthetic" else None
            st.success("Network loaded and ready.")
        except Exception as exc:  # pragma: no cover - UI wrapper
            st.error(str(exc))
    if st.session_state["network"]:
        if st.session_state["network_preview"] is not None:
            st.markdown('<div class="preview-wrap">', unsafe_allow_html=True)
            st.image(st.session_state["network_preview"])
            st.caption("Built-in grid preview")
            st.markdown("</div>", unsafe_allow_html=True)
        network = st.session_state["network"]
        st.markdown(
            f"""
            <div class="scenario-card">
              <div class="scenario-title">{network['name']}</div>
              <div class="small-copy">Network type: {network_type_label(network['source_type'])} | Intersections: {network['node_count']} | Road segments: {network['edge_count']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

with center:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("#### Smart Scenario Creator")
    proposal_text = st.text_area(
        "Describe the change you want to test (in plain English)",
        value="Replace the traffic light at the busy intersection with a roundabout and compare travel times",
        placeholder="Replace the traffic light at the busy intersection with a roundabout and compare travel times",
        height=120,
        help="Describe the road change in normal language. The helper will turn it into a testable scenario.",
    )
    if st.button("Create Scenario", width="stretch", disabled=not st.session_state["network"]):
        try:
            st.session_state["scenario"] = post_json(
                "/scenarios/parse-proposal",
                {
                    "network_id": st.session_state["network"]["network_id"],
                    "demand_profile_id": st.session_state["network"]["demand_profile_id"],
                    "proposal_text": proposal_text,
                },
            )
            st.success("Scenario created.")
        except Exception as exc:  # pragma: no cover - UI wrapper
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
              <div class="scenario-title">Scenario Created: {scenario['title']}</div>
              <div class="small-copy" style="margin-bottom:8px">The Smart Scenario Creator translated your request into these changes:</div>
              <ul>{bullets}</ul>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Run This Scenario Now", width="stretch"):
            results = run_selected_controllers(
                st.session_state["network"],
                scenario["scenario_id"],
                VISIBLE_CONTROLLER_MODES,
                seed=int(seed),
                duration_s=300,
            )
            st.session_state["last_results"] = results
            primary, comparison = choose_viewer_runs(results)
            open_viewer(primary, comparison)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="glass-card" style="margin-top:18px">', unsafe_allow_html=True)
    st.markdown("#### Test the Three Smart Controllers")
    controller_columns = st.columns(3)
    selected_modes: List[str] = []
    for column, mode in zip(controller_columns, VISIBLE_CONTROLLER_MODES):
        copy = controller_copy(mode)
        if column.checkbox(copy["display"], value=True if mode in ("fixed_time", "max_pressure") else False, help=copy["description"]):
            selected_modes.append(mode)
        column.caption(copy["description"])
    duration_s = st.slider("Simulation Length (seconds)", min_value=120, max_value=600, value=300, step=30)
    if st.button("Run All Selected", width="stretch", disabled=not st.session_state["network"] or not selected_modes):
        results = run_selected_controllers(
            st.session_state["network"],
            st.session_state["scenario"]["scenario_id"] if st.session_state["scenario"] else None,
            selected_modes,
            seed=int(seed),
            duration_s=duration_s,
        )
        st.session_state["last_results"] = results
    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown('<div class="glass-card">', unsafe_allow_html=True)
    st.markdown("#### Recent Runs")
    try:
        runs = get_json("/runs")
        render_recent_runs(runs, st.session_state["network"]["network_id"] if st.session_state["network"] else None)
        if st.session_state["last_results"]:
            primary, comparison = choose_viewer_runs(st.session_state["last_results"])
            st.link_button("Open Traffic Comparison Viewer", viewer_url(primary, comparison), use_container_width=True)
    except Exception as exc:  # pragma: no cover - UI wrapper
        st.error(str(exc))
    st.markdown("</div>", unsafe_allow_html=True)
