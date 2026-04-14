import React from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";
import htm from "https://esm.sh/htm@3.1.1";

const { useEffect, useMemo, useRef, useState } = React;
const html = htm.bind(React.createElement);

const API_URL = window.location.origin;
const DEFAULT_AI_PROMPT = "In plain English, what happened here and what should the city do next?";
const MAP_WIDTH = 1000;
const MAP_HEIGHT = 640;
const PREFERRED_MODES = ["fixed_time", "max_pressure", "ga_optimized"];
const FEATURED_METRICS = [
  "city_flow_score",
  "people_moved",
  "avg_travel_time_s",
  "throughput",
  "bus_throughput",
  "cars_removed_from_roads",
];

const FALLBACK_UI = {
  app_title: "Andrew's Traffic Analyzer - City Traffic Flow Optimizer",
  app_subtitle: "See how different smart controllers improve traffic",
  controllers: [
    {
      display: "Basic Fixed-Time Controller",
      short: "Basic Fixed-Time",
      description: "Lights follow a fixed schedule, no matter how busy traffic is.",
      badge_color: "#94A3B8",
    },
    {
      display: "Real-Time Smart Controller",
      short: "Real-Time Smart",
      description: "Changes lights every few seconds based on actual car counts and queues.",
      badge_color: "#22D3EE",
    },
    {
      display: "Evolution-Optimized Controller",
      short: "Evolution-Optimized",
      description: "Tests thousands of timing plans in simulation and picks the winner.",
      badge_color: "#A855F7",
    },
  ],
};

function fetchJson(path) {
  return fetch(`${API_URL}${path}`).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed for ${path}`);
    }
    return response.json();
  });
}

function postJson(path, payload) {
  return fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      throw new Error(text || `Request failed for ${path}`);
    }
    return response.json();
  });
}

function dedupeIds(ids) {
  const seen = new Set();
  return ids.filter((id) => {
    if (!id || seen.has(id)) {
      return false;
    }
    seen.add(id);
    return true;
  });
}

function sameSelection(left, right) {
  return left.primary === right.primary && left.secondary === right.secondary && left.tertiary === right.tertiary;
}

function parseQuerySelection() {
  const params = new URLSearchParams(window.location.search);
  return {
    primary: params.get("primary") || "",
    secondary: params.get("comparison") || params.get("secondary") || "",
    tertiary: params.get("tertiary") || "",
  };
}

function groupRunsByNetwork(runs) {
  const grouped = new Map();
  runs.forEach((run) => {
    const existing = grouped.get(run.network_id) || [];
    existing.push(run);
    grouped.set(run.network_id, existing);
  });
  return [...grouped.entries()].map(([networkId, items]) => ({
    networkId,
    runs: items.sort((a, b) => new Date(b.created_at) - new Date(a.created_at)),
    latestAt: items.reduce((latest, item) => {
      const createdAt = new Date(item.created_at).getTime();
      return Math.max(latest, createdAt);
    }, 0),
  }));
}

function choosePreferredRuns(runs) {
  const picked = [];
  PREFERRED_MODES.forEach((mode) => {
    const match = runs.find((run) => run.controller_mode === mode && !picked.includes(run.run_id));
    if (match) {
      picked.push(match.run_id);
    }
  });
  runs.forEach((run) => {
    if (picked.length < 3 && !picked.includes(run.run_id)) {
      picked.push(run.run_id);
    }
  });
  return picked.slice(0, 3);
}

function chooseDefaultSelection(runs, requested = parseQuerySelection()) {
  const runsById = new Map(runs.map((run) => [run.run_id, run]));
  const requestedIds = dedupeIds([requested.primary, requested.secondary, requested.tertiary].filter((id) => runsById.has(id)));
  let targetGroup = null;
  if (requestedIds.length) {
    const targetNetworkId = runsById.get(requestedIds[0]).network_id;
    targetGroup = runs.filter((run) => run.network_id === targetNetworkId);
  } else {
    const candidates = groupRunsByNetwork(runs).sort((left, right) => {
      const enoughRunsDiff = Number(right.runs.length >= 3) - Number(left.runs.length >= 3);
      if (enoughRunsDiff !== 0) {
        return enoughRunsDiff;
      }
      return right.latestAt - left.latestAt;
    });
    targetGroup = candidates[0]?.runs || runs;
  }
  const preferred = choosePreferredRuns(targetGroup);
  const merged = dedupeIds([...requestedIds, ...preferred]);
  return {
    primary: merged[0] || "",
    secondary: merged[1] || "",
    tertiary: merged[2] || "",
  };
}

function runOptionLabel(run) {
  const createdAt = new Date(run.created_at);
  const timeLabel = createdAt.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  return `${run.controller.short} - ${timeLabel} - #${run.run_id.slice(-4)}`;
}

function metricLabel(name) {
  return {
    city_flow_score: "Traffic Flow Score",
    avg_travel_time_s: "Average Travel Time",
    bus_avg_travel_time_s: "Average Bus Travel Time",
    total_delay_s: "Total Delay",
    throughput: "Cars That Finished",
    started_trip_count: "Trips Started",
    started_car_trip_count: "Cars Entered The Map",
    started_bus_trip_count: "Buses Entered The Map",
    people_moved: "People Moved",
    bus_throughput: "Buses That Finished",
    rail_riders_served: "Rail Riders Served",
    cars_removed_from_roads: "Cars Taken Off The Road",
    avg_queue_len_m: "Average Queue Length",
    p95_travel_time_s: "95th Percentile Travel Time",
    incident_clearance_impact: "Incident Impact",
    completion_ratio_pct: "Trips Finished",
    bus_completion_ratio_pct: "Bus Trips Finished",
  }[name] || name.replace(/_/g, " ");
}

function lowerIsBetter(metricName) {
  return ![
    "throughput",
    "cars_through",
    "bus_throughput",
    "people_moved",
    "rail_riders_served",
    "cars_removed_from_roads",
    "city_flow_score",
    "completion_ratio_pct",
    "bus_completion_ratio_pct",
  ].includes(metricName);
}

function formatMetricValue(metricName, value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "--";
  }
  if (metricName.includes("ratio_pct")) {
    return `${Number(value).toFixed(1)}%`;
  }
  if (metricName.includes("travel_time") || metricName.includes("delay")) {
    return `${Math.round(Number(value)).toLocaleString()} s`;
  }
  if (metricName.includes("queue")) {
    return `${Math.round(Number(value)).toLocaleString()} m`;
  }
  if (metricName.includes("throughput") || metricName.includes("cars") || metricName.includes("started_trip")) {
    return Math.round(Number(value)).toLocaleString();
  }
  if (metricName.includes("moved") || metricName.includes("riders")) {
    return Math.round(Number(value)).toLocaleString();
  }
  if (metricName.includes("score")) {
    return Number(value).toFixed(1);
  }
  return Number(value).toFixed(1);
}

function resolveMetricValue(metricName, run, replay) {
  const metrics = run?.metrics || replay?.metrics || {};
  const networkSummary = replay?.network_summary || {};
  if (metrics[metricName] != null) {
    return metrics[metricName];
  }
  if (metricName === "throughput") {
    return metrics.completed_trip_count ?? null;
  }
  if (metricName === "started_trip_count") {
    if (metrics.total_trip_count != null) {
      return metrics.total_trip_count;
    }
    const plannedTrips = (networkSummary.planned_car_trip_count || 0) + (networkSummary.planned_bus_trip_count || 0);
    return plannedTrips || null;
  }
  if (metricName === "started_car_trip_count") {
    if (metrics.total_trip_count != null && metrics.bus_trip_count != null) {
      return Math.max(0, metrics.total_trip_count - metrics.bus_trip_count);
    }
    return networkSummary.planned_car_trip_count ?? null;
  }
  if (metricName === "started_bus_trip_count") {
    return metrics.bus_trip_count ?? networkSummary.planned_bus_trip_count ?? null;
  }
  if (metricName === "bus_throughput") {
    return metrics.buses_through ?? null;
  }
  return null;
}

function compareToBaseline(metricName, value, baselineValue) {
  if (baselineValue == null || value == null) {
    return { className: "neutral", text: "No baseline comparison yet" };
  }
  if (value === baselineValue) {
    return { className: "neutral", text: "Matches the baseline run" };
  }
  const lowerBetter = lowerIsBetter(metricName);
  const improved = lowerBetter ? value < baselineValue : value > baselineValue;
  const deltaPercent = baselineValue === 0 ? 0 : Math.abs(((value - baselineValue) / baselineValue) * 100);
  return {
    className: improved ? "improved" : "worse",
    text: `${deltaPercent.toFixed(1)}% ${improved ? "better" : "worse"} than Basic Fixed-Time`,
  };
}

function queueColor(queue) {
  if (queue >= 10) {
    return "#FF5D73";
  }
  if (queue >= 5) {
    return "#F59E0B";
  }
  return "#22D3EE";
}

function buildProjection(featureCollection) {
  const coordinates = [];
  featureCollection.features.forEach((feature) => {
    if (feature.geometry.type === "LineString") {
      feature.geometry.coordinates.forEach((point) => coordinates.push(point));
    }
    if (feature.geometry.type === "Point") {
      coordinates.push(feature.geometry.coordinates);
    }
  });
  if (!coordinates.length) {
    return {
      projectPoint: (x, y) => [x, y],
    };
  }
  const xs = coordinates.map((point) => point[0]);
  const ys = coordinates.map((point) => point[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const spanX = Math.max(0.001, maxX - minX);
  const spanY = Math.max(0.001, maxY - minY);
  const pad = 72;
  const drawableWidth = MAP_WIDTH - pad * 2;
  const drawableHeight = MAP_HEIGHT - pad * 2;
  const scale = Math.min(drawableWidth / spanX, drawableHeight / spanY);
  const offsetX = (drawableWidth - spanX * scale) / 2;
  const offsetY = (drawableHeight - spanY * scale) / 2;
  return {
    projectPoint: (x, y) => [
      pad + offsetX + (x - minX) * scale,
      MAP_HEIGHT - pad - offsetY - (y - minY) * scale,
    ],
  };
}

function pointsToPolyline(points) {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

function nearestPointOnSegment(point, start, end) {
  const [px, py] = point;
  const [x1, y1] = start;
  const [x2, y2] = end;
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) {
    return [x1, y1];
  }
  const t = Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / lengthSquared));
  return [x1 + dx * t, y1 + dy * t];
}

function nearestPointOnPolyline(point, polyline) {
  if (!polyline?.length) {
    return point;
  }
  if (polyline.length === 1) {
    return polyline[0];
  }
  let bestPoint = polyline[0];
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < polyline.length - 1; index += 1) {
    const candidate = nearestPointOnSegment(point, polyline[index], polyline[index + 1]);
    const distance = Math.hypot(candidate[0] - point[0], candidate[1] - point[1]);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestPoint = candidate;
    }
  }
  return bestPoint;
}

function useReplay(selectedIds) {
  const [state, setState] = useState({ loading: true, error: "", replays: {} });

  useEffect(() => {
    const ids = dedupeIds(selectedIds);
    if (!ids.length) {
      setState({ loading: false, error: "", replays: {} });
      return undefined;
    }
    let cancelled = false;
    setState((current) => ({ ...current, loading: true, error: "" }));
    Promise.all(ids.map((id) => fetchJson(`/runs/${id}/replay`).then((payload) => [id, payload])))
      .then((entries) => {
        if (cancelled) {
          return;
        }
        setState({
          loading: false,
          error: "",
          replays: Object.fromEntries(entries),
        });
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setState({ loading: false, error: error.message, replays: {} });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedIds.join("|")]);

  return state;
}

function App() {
  const [runs, setRuns] = useState([]);
  const [uiConfig, setUiConfig] = useState(FALLBACK_UI);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [runError, setRunError] = useState("");
  const [selection, setSelection] = useState({ primary: "", secondary: "", tertiary: "" });
  const [isPlaying, setIsPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [frameIndex, setFrameIndex] = useState(0);
  const [gifBusy, setGifBusy] = useState(false);
  const [aiQuestion, setAiQuestion] = useState("In plain English, what happened here and which controller should I pay attention to?");
  const [aiAnswer, setAiAnswer] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiMeta, setAiMeta] = useState(null);
  const aiRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchJson("/runs"), fetchJson("/ui-config")])
      .then(([runsPayload, configPayload]) => {
        if (cancelled) {
          return;
        }
        setRuns(runsPayload);
        setUiConfig({ ...FALLBACK_UI, ...configPayload });
        setLoadingRuns(false);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        setRunError(error.message);
        setLoadingRuns(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!runs.length) {
      return;
    }
    setSelection((current) => {
      const runsById = new Map(runs.map((run) => [run.run_id, run]));
      if (current.primary && runsById.has(current.primary)) {
        const networkId = runsById.get(current.primary).network_id;
        const networkRuns = runs.filter((run) => run.network_id === networkId);
        const kept = dedupeIds([current.primary, current.secondary, current.tertiary].filter((id) => runsById.get(id)?.network_id === networkId));
        const preferred = choosePreferredRuns(networkRuns);
        const merged = dedupeIds([...kept, ...preferred]);
        const next = { primary: merged[0] || "", secondary: merged[1] || "", tertiary: merged[2] || "" };
        return sameSelection(current, next) ? current : next;
      }
      const next = chooseDefaultSelection(runs);
      return sameSelection(current, next) ? current : next;
    });
  }, [runs]);

  useEffect(() => {
    const params = new URLSearchParams();
    if (selection.primary) {
      params.set("primary", selection.primary);
    }
    if (selection.secondary) {
      params.set("comparison", selection.secondary);
    }
    if (selection.tertiary) {
      params.set("tertiary", selection.tertiary);
    }
    const nextUrl = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ""}`;
    window.history.replaceState({}, "", nextUrl);
  }, [selection.primary, selection.secondary, selection.tertiary]);

  const selectedIds = useMemo(
    () => dedupeIds([selection.primary, selection.secondary, selection.tertiary]),
    [selection.primary, selection.secondary, selection.tertiary],
  );
  const selectionKey = selectedIds.join("|");

  const replayState = useReplay(selectedIds);
  const runsById = useMemo(() => Object.fromEntries(runs.map((run) => [run.run_id, run])), [runs]);
  const primaryRun = selection.primary ? runsById[selection.primary] : null;
  const networkRuns = useMemo(() => {
    if (!primaryRun) {
      return runs;
    }
    return runs.filter((run) => run.network_id === primaryRun.network_id);
  }, [runs, primaryRun]);

  const selectedRuns = useMemo(
    () => selectedIds.map((id) => runsById[id]).filter(Boolean),
    [selectedIds, runsById],
  );

  const selectedReplays = useMemo(
    () => selectedIds.map((id) => replayState.replays[id]).filter(Boolean),
    [selectedIds, replayState.replays],
  );

  const frameCount = useMemo(
    () => Math.max(0, ...selectedReplays.map((replay) => replay.frames.length)),
    [selectedReplays],
  );
  const featuredMetrics = useMemo(
    () => (uiConfig.featured_metrics && uiConfig.featured_metrics.length ? uiConfig.featured_metrics : FEATURED_METRICS),
    [uiConfig],
  );

  useEffect(() => {
    if (!frameCount) {
      return;
    }
    setFrameIndex((current) => Math.min(current, frameCount - 1));
  }, [frameCount]);

  const suggestedStartFrame = useMemo(() => {
    if (!selectedReplays.length) {
      return 0;
    }
    const maxLength = Math.max(...selectedReplays.map((replay) => replay.frames.length));
    for (let index = 0; index < maxLength; index += 1) {
      const activityScore = selectedReplays.reduce((sum, replay) => {
        const frame = replay.frames[Math.min(index, Math.max(replay.frames.length - 1, 0))];
        if (!frame) {
          return sum;
        }
        const vehicles = frame.vehicles?.length || 0;
        const queuePressure = Object.values(frame.queues || {}).reduce((queueSum, value) => queueSum + value, 0);
        return sum + vehicles + queuePressure;
      }, 0);
      if (activityScore >= 18) {
        return index;
      }
    }
    return Math.max(0, Math.min(maxLength - 1, Math.floor(maxLength * 0.25)));
  }, [selectedReplays]);

  useEffect(() => {
    setFrameIndex(suggestedStartFrame);
  }, [selectedIds.join("|"), suggestedStartFrame]);

  useEffect(() => {
    if (!isPlaying || frameCount <= 1) {
      return undefined;
    }
    const intervalMs = Math.max(80, 420 / speed);
    const timer = window.setInterval(() => {
      setFrameIndex((current) => (current + 1 >= frameCount ? 0 : current + 1));
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [isPlaying, frameCount, speed]);

  const baselineRun = selectedRuns.find((run) => run.controller_mode === "fixed_time") || selectedRuns[0] || null;
  const winnerMetric = useMemo(() => {
    if (selectedRuns.some((run) => (run.metrics?.city_flow_score || 0) > 0)) {
      return "city_flow_score";
    }
    return "avg_travel_time_s";
  }, [selectedRuns]);
  const winnerRunId = useMemo(() => {
    if (!selectedRuns.length) {
      return "";
    }
    const scoredRuns = selectedRuns.filter((run) => run.metrics?.[winnerMetric] != null);
    if (!scoredRuns.length) {
      return "";
    }
    const sorted = [...scoredRuns].sort((left, right) => {
      const leftValue = left.metrics?.[winnerMetric];
      const rightValue = right.metrics?.[winnerMetric];
      if (winnerMetric === "city_flow_score") {
        if ((rightValue || 0) !== (leftValue || 0)) {
          return (rightValue || 0) - (leftValue || 0);
        }
        return (left.metrics?.avg_travel_time_s || Number.POSITIVE_INFINITY) - (right.metrics?.avg_travel_time_s || Number.POSITIVE_INFINITY);
      }
      return (leftValue || Number.POSITIVE_INFINITY) - (rightValue || Number.POSITIVE_INFINITY);
    });
    return sorted[0]?.run_id || "";
  }, [selectedRuns, winnerMetric]);

  const primaryScenario = selectedReplays[0]?.scenario || {
    title: "Run a comparison to see what changed",
    summary: "Pick up to three controller runs on the same road network to compare them side by side.",
    bullets: [],
  };
  const networkSummary = selectedReplays[0]?.network_summary || null;

  const handlePrimaryChange = (runId) => {
    const nextPrimary = runsById[runId];
    if (!nextPrimary) {
      return;
    }
    const compatibleRuns = runs.filter((run) => run.network_id === nextPrimary.network_id);
    const preferred = choosePreferredRuns(compatibleRuns);
    const merged = dedupeIds([runId, ...preferred]);
    setSelection({
      primary: merged[0] || "",
      secondary: merged[1] || "",
      tertiary: merged[2] || "",
    });
  };

  const handleSecondaryChange = (runId) => {
    const preferred = choosePreferredRuns(networkRuns);
    const merged = dedupeIds([selection.primary, runId, selection.tertiary, ...preferred]);
    setSelection({
      primary: merged[0] || "",
      secondary: merged[1] || "",
      tertiary: merged[2] || "",
    });
  };

  const handleTertiaryChange = (runId) => {
    const preferred = choosePreferredRuns(networkRuns);
    const merged = dedupeIds([selection.primary, selection.secondary, runId, ...preferred]);
    setSelection({
      primary: merged[0] || "",
      secondary: merged[1] || "",
      tertiary: merged[2] || "",
    });
  };

  const refreshRuns = () => {
    setLoadingRuns(true);
    setRunError("");
    Promise.all([fetchJson("/runs"), fetchJson("/ui-config")])
      .then(([runsPayload, configPayload]) => {
        setRuns(runsPayload);
        setUiConfig({ ...FALLBACK_UI, ...configPayload });
        setLoadingRuns(false);
      })
      .catch((error) => {
        setRunError(error.message);
        setLoadingRuns(false);
      });
  };

  const exportGif = async () => {
    if (!selection.primary) {
      return;
    }
    setGifBusy(true);
    try {
      const params = new URLSearchParams();
      params.set("primary", selection.primary);
      if (selection.secondary) {
        params.set("comparison", selection.secondary);
      }
      if (selection.tertiary) {
        params.set("tertiary", selection.tertiary);
      }
      window.open(`${API_URL}/runs/export-gif?${params.toString()}`, "_blank", "noopener,noreferrer");
    } finally {
      window.setTimeout(() => setGifBusy(false), 400);
    }
  };

  const askTrafficAnalyst = async (questionOverride) => {
    if (!selectedIds.length) {
      return;
    }
    const question = (questionOverride || aiQuestion || DEFAULT_AI_PROMPT).trim();
    if (!question) {
      return;
    }
    const requestId = aiRequestRef.current + 1;
    aiRequestRef.current = requestId;
    setAiQuestion(question);
    setAiBusy(true);
    setAiError("");
    try {
      const result = await postJson("/analysis/run-summary", {
        run_ids: selectedIds,
        question,
      });
      if (aiRequestRef.current !== requestId) {
        return;
      }
      setAiAnswer(result.answer || "");
      setAiMeta(result);
    } catch (error) {
      if (aiRequestRef.current !== requestId) {
        return;
      }
      setAiError(error.message);
    } finally {
      if (aiRequestRef.current === requestId) {
        setAiBusy(false);
      }
    }
  };

  useEffect(() => {
    aiRequestRef.current += 1;
    setAiAnswer("");
    setAiError("");
    setAiMeta(null);
    setAiQuestion(DEFAULT_AI_PROMPT);
    setAiBusy(false);
  }, [selectionKey]);

  useEffect(() => {
    if (!selectedIds.length || replayState.loading || loadingRuns) {
      return;
    }
    askTrafficAnalyst(DEFAULT_AI_PROMPT);
  }, [selectionKey, replayState.loading, loadingRuns]);

  return html`
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"></div>
          <div>
            <div className="brand-title">${uiConfig.app_title || FALLBACK_UI.app_title}</div>
            <div className="brand-subtitle">${uiConfig.app_subtitle || FALLBACK_UI.app_subtitle}</div>
          </div>
        </div>
        <nav className="nav-tabs">
          <a href="http://127.0.0.1:8501/" className="nav-tab">Operator Console</a>
          <a href="/demo/" className="nav-tab nav-tab-active">Traffic Comparison Viewer</a>
          <a href="/demo/architecture.html" className="nav-tab">Overview and Documentation</a>
        </nav>
      </header>

      <div className="hero-band">
        <section className="panel">
          <div className="eyebrow">Traffic Comparison Viewer</div>
          <h1>Watch the cars move and see which controller actually keeps traffic flowing.</h1>
          <p className="hero-copy">
            Compare up to three runs on the same road network, zoom into trouble spots, and see how street changes, bus upgrades, and rail ideas affect the whole city in plain English.
          </p>
        </section>
        <section className="panel legend-panel">
          <div className="eyebrow">How This Works</div>
          <div className="legend-list">
            ${(uiConfig.controllers || FALLBACK_UI.controllers).map(
              (item) => html`
                <div className="legend-item" key=${item.display}>
                  <span className="badge" style=${{ background: item.badge_color }}></span>
                  <div>
                    <div className="legend-title">${item.display || item.label}</div>
                    <div className="legend-copy">${item.description}</div>
                  </div>
                </div>
              `,
            )}
          </div>
        </section>
      </div>

      <div className="comparison-layout">
        <aside className="sidebar-panel">
          <section className="panel">
            <div className="eyebrow">Choose Runs</div>
            <h3>Compare up to three controller runs</h3>
            <p className="helper-text">
              The viewer keeps all three slots on the same road network so the comparison stays fair and readable.
            </p>
            <div className="selection-grid">
              <label>
                <span className="field-label">Primary Run</span>
                <select value=${selection.primary} onChange=${(event) => handlePrimaryChange(event.target.value)}>
                  ${runs.map(
                    (run) => html`<option value=${run.run_id} key=${run.run_id}>${runOptionLabel(run)}</option>`,
                  )}
                </select>
              </label>
              <label>
                <span className="field-label">Comparison Run</span>
                <select value=${selection.secondary} onChange=${(event) => handleSecondaryChange(event.target.value)}>
                  <option value="">None</option>
                  ${networkRuns.map(
                    (run) => html`<option value=${run.run_id} key=${run.run_id}>${runOptionLabel(run)}</option>`,
                  )}
                </select>
              </label>
              <label>
                <span className="field-label">Third Run</span>
                <select value=${selection.tertiary} onChange=${(event) => handleTertiaryChange(event.target.value)}>
                  <option value="">None</option>
                  ${networkRuns.map(
                    (run) => html`<option value=${run.run_id} key=${run.run_id}>${runOptionLabel(run)}</option>`,
                  )}
                </select>
              </label>
            </div>
            <div className="controls-row">
              <button className="primary-button" onClick=${refreshRuns}>Refresh Latest Runs</button>
              <button className="secondary-button" onClick=${exportGif} disabled=${gifBusy || !selection.primary}>
                ${gifBusy ? "Preparing GIF..." : "Export 15-Second GIF"}
              </button>
            </div>
            <div className="inline-note" style=${{ marginTop: "12px" }}>
              Scroll to zoom. Drag to pan. White dots are cars. Amber bars are buses. Gold dashed lines mark planned rail or transit upgrades. Cross markers show which direction has the green light.
            </div>
          </section>

          <section className="panel">
            <div className="eyebrow">Playback</div>
            <h3>Play the comparison</h3>
            <div className="controls-row">
              <button className="primary-button" onClick=${() => setIsPlaying((current) => !current)}>
                ${isPlaying ? "Pause Replay" : "Play Replay"}
              </button>
            </div>
            <label>
              <span className="field-label">Playback Speed: ${speed.toFixed(1)}x</span>
              <input type="range" min="0.5" max="3" step="0.25" value=${speed} onChange=${(event) => setSpeed(Number(event.target.value))} />
            </label>
            <label>
              <span className="field-label">Timeline Position</span>
              <input
                type="range"
                min="0"
                max=${Math.max(0, frameCount - 1)}
                step="1"
                value=${frameIndex}
                onChange=${(event) => setFrameIndex(Number(event.target.value))}
                disabled=${frameCount <= 1}
              />
            </label>
            <div className="helper-text">
              ${frameCount ? `Showing frame ${frameIndex + 1} of ${frameCount}.` : "Run a few controllers first to see the comparison here."}
            </div>
          </section>

          <section className="panel">
            <div className="eyebrow">Scoreboard</div>
            <h3>Which controller is winning?</h3>
            <div className="scoreboard-list">
	              ${selectedRuns.length
	                ? selectedRuns.map(
	                    (run) => {
                        const replay = replayState.replays[run.run_id];
                        const metricValue = resolveMetricValue(winnerMetric, run, replay);
                        const baselineValue = baselineRun
                          ? resolveMetricValue(winnerMetric, baselineRun, replayState.replays[baselineRun.run_id])
                          : null;
                        const baselineComparison = compareToBaseline(winnerMetric, metricValue, baselineValue);
                        return html`
	                      <div className=${`score-card ${run.run_id === winnerRunId ? "best" : ""}`} key=${run.run_id}>
	                      <div className="score-card-head">
	                          <div className="series-chip">
	                            <span className="badge" style=${{ background: run.controller.badge_color }}></span>
	                            <span>${run.controller.short}</span>
	                          </div>
	                          ${run.run_id === winnerRunId ? html`<span className="winner-flag">Best Result</span>` : null}
	                        </div>
	                        <div className="score-label">${metricLabel(winnerMetric)}</div>
	                        <div className="score-main-value">${formatMetricValue(winnerMetric, metricValue)}</div>
	                        <div className=${`metric-delta ${baselineComparison.className}`}>
	                          ${baselineComparison.text}
	                        </div>
	                      </div>
	                    `;
                      },
	                  )
	                : html`<div className="empty-state compact">Choose a few runs to rank the controllers.</div>`}
            </div>
          </section>
        </aside>

        <main className="comparison-main">
          ${loadingRuns || replayState.loading
            ? html`<section className="panel"><div className="empty-state">Loading the latest controller runs and replay data...</div></section>`
            : runError || replayState.error
              ? html`<section className="panel"><div className="empty-state">${runError || replayState.error}</div></section>`
              : selectedReplays.length
                ? html`
                    <section className="panel">
                      <div className="maps-toolbar">
                        <div>
                          <div className="eyebrow">Live Replay</div>
                          <h3>Three smart controllers on the same map</h3>
                          <p className="helper-text">
                            The map shows moving cars, buses, live traffic-light state, and road segments that are filling up with queues.
                          </p>
                        </div>
                        <div className="run-pill-group">
                          ${selectedRuns.map(
                            (run) => html`
                              <span className=${`run-pill ${run.run_id === winnerRunId ? "run-pill-best" : ""}`} key=${run.run_id}>
                                <span className="badge" style=${{ background: run.controller.badge_color }}></span>
                                ${run.controller.short}
                              </span>
                            `,
                          )}
                        </div>
                      </div>
                      <div className=${`maps-grid maps-grid-${selectedReplays.length}`}>
                        ${selectedReplays.map(
                          (replay) => html`
                            <${ReplayMap}
                              key=${replay.run_id}
                              replay=${replay}
                              frameIndex=${frameIndex}
                              isWinner=${replay.run_id === winnerRunId}
                              isPlaying=${isPlaying}
                            />
                          `,
                        )}
                      </div>
                    </section>

                    <section className="insights-grid">
                      <section className="panel">
                        <div className="eyebrow">AI Traffic Analyst</div>
                        <h3>Ask for a plain-English readout</h3>
                        <p className="helper-text">
                          ${uiConfig.analyst?.available
                            ? "Powered by Grok through the server-side xAI integration."
                            : "Using a deterministic fallback summary if the external model is unavailable."}
                        </p>
                        <div className="inline-note" style=${{ marginBottom: "12px" }}>
                          The analyst now explains the currently selected runs automatically. Use the quick prompts below if you want to dig deeper.
                        </div>
                        <div className="prompt-chip-row">
                          ${[
                            "In plain English, what happened here?",
                            "What should the city do next?",
                            "What is the clearest takeaway?",
                            "What should I notice in the replay?",
                          ].map(
                            (prompt) => html`
                              <button
                                key=${prompt}
                                className="secondary-button chip-button"
                                onClick=${() => askTrafficAnalyst(prompt)}
                                disabled=${aiBusy || !selectedIds.length}
                              >
                                ${prompt}
                              </button>
                            `,
                          )}
                        </div>
                        <label>
                          <span className="field-label">Ask a follow-up</span>
                          <textarea
                            className="analyst-input"
                            value=${aiQuestion}
                            onChange=${(event) => setAiQuestion(event.target.value)}
                            placeholder="Why did this controller win, and what is the clearest takeaway?"
                          ></textarea>
                        </label>
                        <div className="controls-row">
                          <button className="primary-button" onClick=${() => askTrafficAnalyst()} disabled=${aiBusy || !selectedIds.length}>
                            ${aiBusy ? "Asking AI Traffic Analyst..." : "Ask AI Traffic Analyst"}
                          </button>
                        </div>
                        ${aiError ? html`<div className="inline-note">${aiError}</div>` : null}
                        ${aiAnswer
                          ? html`
                              <div className="ai-answer">${aiAnswer}</div>
                              <div className="ai-meta">
                                ${aiMeta?.used_ai ? "Source: Grok via xAI." : "Source: deterministic fallback summary."}
                              </div>
                            `
                          : html`<div className="empty-state compact">Ask “What should the city do next?” for a plain-English recommendation.</div>`}
                      </section>

                      <section className="panel">
                        <div className="eyebrow">Travel Time Trend</div>
                        <h3>How traffic changed over time</h3>
                        <${TimelineChart} replays=${selectedReplays} frameIndex=${frameIndex} />
                      </section>

                      <section className="panel">
                        <div className="eyebrow">What Changed</div>
                        <h3>${primaryScenario.title}</h3>
                        <p className="legend-copy">${primaryScenario.summary}</p>
                        <ul className="scenario-list">
                          ${(primaryScenario.bullets || []).map((bullet, index) => html`<li key=${`${primaryScenario.title}-${index}`}>${bullet}</li>`)}
                        </ul>
                      </section>

                      <section className="panel">
                        <div className="eyebrow">What Powers This Demo</div>
                        <h3>${networkSummary?.name || "City Traffic Model"}</h3>
                        <p className="legend-copy">
                          ${networkSummary
                            ? `This run uses ${networkSummary.bus_route_count || 0} scheduled bus routes, ${networkSummary.rail_line_count || 0} planned rail corridors, and a bundle of simulated city data feeds.`
                            : "Pick a run to see the city inputs and transit assumptions behind this simulation."}
                        </p>
                        <div className="summary-metric">
                          <span>Traffic Level</span>
                          <strong>${formatTrafficScale(networkSummary?.traffic_scale)}</strong>
                        </div>
                        <div className="summary-metric">
                          <span>Planned Car Trips</span>
                          <strong>${networkSummary?.planned_car_trip_count || 0}</strong>
                        </div>
                        <div className="summary-metric">
                          <span>Map Type</span>
                          <strong>${networkSummary?.source_type === "osm" ? "Real Neighborhood Map" : "Built-In Demo Grid"}</strong>
                        </div>
                        <div className="summary-metric">
                          <span>Bus Routes</span>
                          <strong>${networkSummary?.bus_route_count || 0}</strong>
                        </div>
                        <div className="summary-metric">
                          <span>Planned Rail Corridors</span>
                          <strong>${networkSummary?.rail_line_count || 0}</strong>
                        </div>
                        <div className="summary-metric">
                          <span>Cars Taken Off The Road</span>
                          <strong>${networkSummary?.cars_removed_from_roads || 0}</strong>
                        </div>
                        <div className="feed-list">
                          ${(networkSummary?.city_inputs || []).map((feed) => html`<div className="feed-pill" key=${feed}>${feed}</div>`)}
                        </div>
                      </section>

                      <section className="panel">
                        <div className="eyebrow">Key Numbers</div>
                        <h3>Quick read on each selected run</h3>
                        <div className="run-summary-grid">
	                          ${selectedRuns.map(
	                            (run) => html`
	                              <div className="summary-card" key=${run.run_id}>
	                                <div className="summary-card-head">
	                                  <span className="series-chip">
	                                    <span className="badge" style=${{ background: run.controller.badge_color }}></span>
	                                    ${run.controller.short}
                                  </span>
                                  ${run.run_id === winnerRunId ? html`<span className="winner-flag">Best</span>` : null}
                                </div>
	                                ${featuredMetrics.map(
	                                  (metricName) => html`
	                                    <div className="summary-metric" key=${metricName}>
	                                      <span>${metricLabel(metricName)}</span>
	                                      <strong>${formatMetricValue(metricName, resolveMetricValue(metricName, run, replayState.replays[run.run_id]))}</strong>
	                                    </div>
	                                  `,
	                                )}
                              </div>
                            `,
                          )}
                        </div>
                      </section>
                    </section>
                  `
                : html`<section className="panel"><div className="empty-state">Run a few controllers first to see the comparison here.</div></section>`}
        </main>
      </div>
    </div>
  `;
}

function formatTrafficScale(scale) {
  if (!scale) {
    return "City Rush";
  }
  if (Math.abs(scale - 0.75) < 0.01) {
    return "Light";
  }
  if (Math.abs(scale - 1.0) < 0.01) {
    return "City Rush";
  }
  if (Math.abs(scale - 1.5) < 0.01) {
    return "Heavy";
  }
  if (Math.abs(scale - 2.2) < 0.01) {
    return "Gridlock";
  }
  return `${scale.toFixed(1)}x`;
}

function ReplayMap({ replay, frameIndex, isWinner, isPlaying }) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef(null);

  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, [replay.run_id]);

  const lineFeatures = useMemo(
    () => replay.network_geojson.features.filter((feature) => feature.geometry.type === "LineString"),
    [replay.network_geojson],
  );
  const signalFeatures = useMemo(
    () =>
      replay.network_geojson.features.filter(
        (feature) => feature.geometry.type === "Point" && feature.properties.control_type === "signal",
      ),
    [replay.network_geojson],
  );
  const roundaboutFeatures = useMemo(
    () =>
      replay.network_geojson.features.filter(
        (feature) => feature.geometry.type === "Point" && feature.properties.control_type === "roundabout",
      ),
    [replay.network_geojson],
  );
  const projection = useMemo(() => buildProjection(replay.network_geojson), [replay.network_geojson]);
  const frame = replay.frames[Math.min(frameIndex, Math.max(replay.frames.length - 1, 0))] || {
    time_s: 0,
    queues: {},
    signals: {},
    vehicles: [],
  };
  const projectedLines = useMemo(
    () =>
      lineFeatures.map((feature) => ({
        id: feature.properties.id,
        rawPoints: feature.geometry.coordinates,
        points: feature.geometry.coordinates.map(([x, y]) => projection.projectPoint(x, y)),
      })),
    [lineFeatures, projection],
  );
  const lineLookup = useMemo(() => new Map(projectedLines.map((line) => [line.id, line])), [projectedLines]);
  const projectedSignals = useMemo(
    () =>
      signalFeatures.map((feature) => ({
        id: feature.properties.id,
        point: projection.projectPoint(feature.geometry.coordinates[0], feature.geometry.coordinates[1]),
      })),
    [projection, signalFeatures],
  );
  const projectedRoundabouts = useMemo(
    () =>
      roundaboutFeatures.map((feature) => ({
        id: feature.properties.id,
        point: projection.projectPoint(feature.geometry.coordinates[0], feature.geometry.coordinates[1]),
      })),
    [projection, roundaboutFeatures],
  );
  const transitOverlays = replay.network_summary?.transit_overlays || [];
  const projectedTransitOverlays = useMemo(
    () =>
      transitOverlays.map((overlay, index) => ({
        id: `${overlay.type || "transit"}-${overlay.name || index}-${index}`,
        name: overlay.name || "Transit Upgrade",
        type: overlay.type || "transit",
        color: overlay.color || "#F59E0B",
        points: (overlay.geometry || []).map(([x, y]) => projection.projectPoint(x, y)),
      })),
    [projection, transitOverlays],
  );

  const allVehicles = frame.vehicles || [];
  const buses = allVehicles.filter((vehicle) => vehicle.vehicle_type === "bus");
  const cars = allVehicles.filter((vehicle) => vehicle.vehicle_type !== "bus");
  const vehicleStep = Math.max(1, Math.ceil(cars.length / 420));
  const visibleCars = cars.filter((_, index) => index % vehicleStep === 0);
  const visibleVehicles = [...visibleCars, ...buses];
  const worstQueue = Math.max(0, ...Object.values(frame.queues || {}));

  const updateZoom = (nextZoom) => {
    setZoom(Math.max(1, Math.min(4, nextZoom)));
  };

  const handleWheel = (event) => {
    event.preventDefault();
    const delta = event.deltaY < 0 ? 0.16 : -0.16;
    updateZoom(zoom + delta);
  };

  const handlePointerDown = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      scaleX: MAP_WIDTH / rect.width,
      scaleY: MAP_HEIGHT / rect.height,
    };
    setDragging(true);
  };

  const handlePointerMove = (event) => {
    if (!dragRef.current) {
      return;
    }
    const dx = (event.clientX - dragRef.current.x) * dragRef.current.scaleX;
    const dy = (event.clientY - dragRef.current.y) * dragRef.current.scaleY;
    dragRef.current.x = event.clientX;
    dragRef.current.y = event.clientY;
    setPan((current) => ({ x: current.x + dx, y: current.y + dy }));
  };

  const stopDragging = () => {
    dragRef.current = null;
    setDragging(false);
  };

  const transform = `translate(${pan.x} ${pan.y}) translate(${MAP_WIDTH / 2} ${MAP_HEIGHT / 2}) scale(${zoom}) translate(${-MAP_WIDTH / 2} ${-MAP_HEIGHT / 2})`;

  return html`
    <article className=${`panel map-panel ${isWinner ? "is-winner" : ""}`}>
      <div className="map-header">
        <div>
          <div className="map-title">${replay.controller.display}</div>
          <div className="map-copy">${replay.controller.description}</div>
          <div className="map-stat-row">
            <span className="stat-pill">${visibleCars.length} cars shown</span>
            <span className="stat-pill">${buses.length} buses shown</span>
            <span className="stat-pill">${projectedSignals.length} traffic lights</span>
            <span className="stat-pill">${projectedTransitOverlays.length} transit upgrade${projectedTransitOverlays.length === 1 ? "" : "s"}</span>
            <span className="stat-pill">${Math.round(worstQueue)} vehicles in the worst queue</span>
          </div>
        </div>
        <div className="time-chip">t = ${Math.round(frame.time_s || 0)}s</div>
      </div>
      <div className="map-surface">
        <svg
          className=${`map-svg ${dragging ? "is-dragging" : ""}`}
          viewBox=${`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
          onWheel=${handleWheel}
          onPointerDown=${handlePointerDown}
          onPointerMove=${handlePointerMove}
          onPointerUp=${stopDragging}
          onPointerLeave=${stopDragging}
        >
          <defs>
            <filter id=${`glow-${replay.run_id}`}>
              <feGaussianBlur stdDeviation="2.2" result="coloredBlur" />
              <feMerge>
                <feMergeNode in="coloredBlur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g transform=${transform}>
            ${projectedTransitOverlays.map((overlay) => {
              if (overlay.points.length < 2) {
                return null;
              }
              return html`
                <polyline
                  key=${`${overlay.id}-overlay`}
                  className=${`transit-overlay transit-overlay-${overlay.type}`}
                  points=${pointsToPolyline(overlay.points)}
                  fill="none"
                  stroke=${overlay.color}
                  strokeWidth=${overlay.type === "rail" ? 8 : 6}
                  strokeDasharray=${overlay.type === "rail" ? "18 10" : "10 8"}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity="0.72"
                />
              `;
            })}

            ${projectedLines.map((line) => {
              return html`
                <polyline
                  key=${`${line.id}-base`}
                  className="road-base"
                  points=${pointsToPolyline(line.points)}
                  fill="none"
                  stroke="rgba(113, 212, 255, 0.18)"
                  strokeWidth="4.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity="0.9"
                />
              `;
            })}

            ${projectedLines.map((line) => {
              const queue = frame.queues?.[line.id] || 0;
              return html`
                <polyline
                  key=${line.id}
                  className=${`congestion-path ${queue >= 8 ? "pulse" : ""}`}
                  points=${pointsToPolyline(line.points)}
                  fill="none"
                  stroke=${queueColor(queue)}
                  strokeWidth=${2.5 + Math.min(queue, 12) * 0.55}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity=${0.98}
                  filter=${`url(#glow-${replay.run_id})`}
                />
              `;
            })}

            ${projectedRoundabouts.map((roundabout) => {
              const [x, y] = roundabout.point;
              return html`
                <g key=${roundabout.id}>
                  <circle cx=${x} cy=${y} r="8" fill="none" stroke="#F59E0B" strokeWidth="2.4" opacity="0.9" />
                  <circle cx=${x} cy=${y} r="12" fill="none" stroke="#F59E0B" strokeWidth="1.2" opacity="0.32" />
                </g>
              `;
            })}

            ${projectedSignals.map((signal) => {
              const [x, y] = signal.point;
              const phase = frame.signals?.[signal.id] || "NS";
              const nsOpen = phase === "NS";
              return html`
                <g key=${signal.id}>
                  <circle cx=${x} cy=${y} r="9" fill="#04101D" stroke="rgba(255,255,255,0.22)" strokeWidth="1.2" />
                  <line x1=${x} y1=${y - 6} x2=${x} y2=${y + 6} stroke=${nsOpen ? "#22C55E" : "#FF5D73"} strokeWidth="2.6" strokeLinecap="round" />
                  <line x1=${x - 6} y1=${y} x2=${x + 6} y2=${y} stroke=${nsOpen ? "#FF5D73" : "#22C55E"} strokeWidth="2.6" strokeLinecap="round" />
                </g>
              `;
            })}

            ${visibleVehicles.map((vehicle, index) => {
              const edge = lineLookup.get(vehicle.edge_id);
              const snappedPoint = edge
                ? nearestPointOnPolyline([vehicle.x, vehicle.y], edge.rawPoints)
                : [vehicle.x, vehicle.y];
              const [x, y] = projection.projectPoint(snappedPoint[0], snappedPoint[1]);
              if (vehicle.vehicle_type === "bus") {
                return html`
                  <g key=${`${replay.run_id}-bus-${index}`}>
                    <rect
                      className=${`bus-marker ${isPlaying ? "moving" : ""}`}
                      x=${x - 4.8}
                      y=${y - 2.8}
                      rx="2"
                      ry="2"
                      width="9.6"
                      height="5.6"
                      fill="#F59E0B"
                      stroke="#FEF3C7"
                      strokeWidth="0.9"
                      opacity="0.98"
                    />
                    ${vehicle.route_name ? html`<title>${vehicle.route_name}</title>` : null}
                  </g>
                `;
              }
              return html`
                <circle
                  key=${`${replay.run_id}-car-${index}`}
                  className=${`car-dot ${isPlaying ? "moving" : ""}`}
                  cx=${x}
                  cy=${y}
                  r="2.5"
                  fill="#F8FDFF"
                  stroke="#7DD3FC"
                  strokeWidth="0.8"
                  opacity="0.96"
                />
              `;
            })}

            ${isWinner
              ? [0, 1, 2].map(
                  (index) => html`
                    <circle
                      key=${`${replay.run_id}-success-${index}`}
                      className="success-particle"
                      cx=${880 + index * 24}
                      cy=${90 + index * 16}
                      r=${4 + index}
                      fill="rgba(34,197,94,0.75)"
                    />
                  `,
                )
              : null}
          </g>
        </svg>

        <div className="map-overlay">
          <div className="map-overlay-controls">
            <button className="icon-button" onClick=${() => updateZoom(zoom - 0.25)}>-</button>
            <div className="zoom-readout">${zoom.toFixed(1)}x</div>
            <button className="icon-button" onClick=${() => updateZoom(zoom + 0.25)}>+</button>
            <button className="icon-button icon-button-wide" onClick=${() => {
              setZoom(1);
              setPan({ x: 0, y: 0 });
            }}>Reset</button>
          </div>
        </div>

        <div className="map-key">
          <div className="map-key-item"><span className="map-key-swatch map-key-cars"></span>White dots = cars</div>
          <div className="map-key-item"><span className="map-key-swatch map-key-bus"></span>Amber bars = buses</div>
          ${projectedTransitOverlays.some((overlay) => overlay.type === "rail")
            ? html`<div className="map-key-item"><span className="map-key-swatch map-key-rail"></span>Gold dashed line = planned rail corridor</div>`
            : null}
          <div className="map-key-item"><span className="map-key-swatch map-key-signal"></span>Cross markers = traffic lights</div>
          <div className="map-key-item"><span className="map-key-swatch map-key-queue"></span>Warm roads = growing queues</div>
          <div className="zoom-note">Drag to pan. Scroll to zoom.</div>
        </div>
      </div>
    </article>
  `;
}

function TimelineChart({ replays, frameIndex }) {
  const series = replays.map((replay) => ({
    runId: replay.run_id,
    label: replay.controller.display,
    color: replay.controller.badge_color,
    points: replay.timeline || [],
  }));

  if (!series.length) {
    return html`<div className="empty-state compact">Run a few controllers first to see the trend chart.</div>`;
  }

  const width = 560;
  const height = 220;
  const padX = 40;
  const padY = 24;
  const allPoints = series.flatMap((item) => item.points);
  const maxTime = Math.max(1, ...allPoints.map((point) => point.time_s || 0));
  const values = allPoints.map((point) => point.travel_time_index_s || 0);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const spanValue = Math.max(1, maxValue - minValue);
  const projectX = (timeS) => padX + ((timeS || 0) / maxTime) * (width - padX * 2);
  const projectY = (value) => height - padY - (((value || 0) - minValue) / spanValue) * (height - padY * 2);

  const frameTime = Math.max(
    0,
    ...series.map((item) => item.points[Math.min(frameIndex, Math.max(item.points.length - 1, 0))]?.time_s || 0),
  );

  return html`
    <div className="trend-chart">
      <svg viewBox=${`0 0 ${width} ${height}`} className="timeline-svg">
        ${[0, 0.25, 0.5, 0.75, 1].map((step) => {
          const y = padY + step * (height - padY * 2);
          return html`<line key=${`grid-${step}`} x1=${padX} y1=${y} x2=${width - padX} y2=${y} stroke="rgba(255,255,255,0.08)" />`;
        })}
        <line x1=${projectX(frameTime)} y1=${padY} x2=${projectX(frameTime)} y2=${height - padY} stroke="rgba(255,255,255,0.16)" strokeDasharray="4 6" />
        ${series.map((item) => {
          const path = item.points.map((point, index) => `${index === 0 ? "M" : "L"} ${projectX(point.time_s)} ${projectY(point.travel_time_index_s)}`).join(" ");
          const currentPoint = item.points[Math.min(frameIndex, Math.max(item.points.length - 1, 0))] || item.points[item.points.length - 1];
          return html`
            <g key=${item.runId}>
              <path d=${path} fill="none" stroke=${item.color} strokeWidth="3.2" strokeLinecap="round" />
              ${currentPoint
                ? html`<circle cx=${projectX(currentPoint.time_s)} cy=${projectY(currentPoint.travel_time_index_s)} r="4.6" fill=${item.color} stroke="#ffffff" strokeWidth="1.4" />`
                : null}
            </g>
          `;
        })}
      </svg>
      <div className="chart-key">
        ${series.map(
          (item) => html`
            <div className="key-item" key=${item.runId}>
              <span className="badge" style=${{ background: item.color }}></span>
              <span>${item.label}</span>
            </div>
          `,
        )}
      </div>
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
