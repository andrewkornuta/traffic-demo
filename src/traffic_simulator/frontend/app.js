import React from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";
import htm from "https://esm.sh/htm@3.1.1";

const { useEffect, useMemo, useRef, useState } = React;
const html = htm.bind(React.createElement);

const API_URL = window.location.origin;
const MAP_WIDTH = 1000;
const MAP_HEIGHT = 640;
const PREFERRED_MODES = ["fixed_time", "max_pressure", "ga_optimized"];
const FEATURED_METRICS = [
  "avg_travel_time_s",
  "total_delay_s",
  "throughput",
  "avg_queue_len_m",
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
    avg_travel_time_s: "Average Travel Time",
    total_delay_s: "Total Delay",
    throughput: "Cars Through",
    avg_queue_len_m: "Average Queue Length",
    p95_travel_time_s: "95th Percentile Travel Time",
    incident_clearance_impact: "Incident Impact",
  }[name] || name.replace(/_/g, " ");
}

function lowerIsBetter(metricName) {
  return !["throughput", "cars_through"].includes(metricName);
}

function formatMetricValue(metricName, value) {
  if (value == null || Number.isNaN(Number(value))) {
    return "--";
  }
  if (metricName.includes("travel_time") || metricName.includes("delay")) {
    return `${Math.round(Number(value)).toLocaleString()} s`;
  }
  if (metricName.includes("queue")) {
    return `${Math.round(Number(value)).toLocaleString()} m`;
  }
  if (metricName.includes("throughput") || metricName.includes("cars")) {
    return Math.round(Number(value)).toLocaleString();
  }
  return Number(value).toFixed(1);
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
  const winnerRunId = useMemo(() => {
    if (!selectedRuns.length) {
      return "";
    }
    const scoredRuns = selectedRuns.filter((run) => (run.metrics?.avg_travel_time_s || 0) > 0);
    if (!scoredRuns.length) {
      return "";
    }
    return [...scoredRuns]
      .sort((left, right) => (left.metrics?.avg_travel_time_s || Number.POSITIVE_INFINITY) - (right.metrics?.avg_travel_time_s || Number.POSITIVE_INFINITY))[0]
      .run_id;
  }, [selectedRuns]);

  const primaryScenario = selectedReplays[0]?.scenario || {
    title: "Run a comparison to see what changed",
    summary: "Pick up to three controller runs on the same road network to compare them side by side.",
    bullets: [],
  };

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
      window.open(`${API_URL}/runs/export-gif?${params.toString()}`, "_blank", "noopener,noreferrer");
    } finally {
      window.setTimeout(() => setGifBusy(false), 400);
    }
  };

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
          <a href="/demo/architecture.html" className="nav-tab">Architecture</a>
        </nav>
      </header>

      <div className="hero-band">
        <section className="panel">
          <div className="eyebrow">Traffic Comparison Viewer</div>
          <h1>Watch the cars move and see which controller actually keeps traffic flowing.</h1>
          <p className="hero-copy">
            Compare up to three runs on the same road network, zoom into trouble spots, and read the results in plain English instead of traffic jargon.
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
              Scroll to zoom. Drag to pan. White dots are cars. Traffic-light markers show which direction currently has green.
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
                    (run) => html`
                      <div className=${`score-card ${run.run_id === winnerRunId ? "best" : ""}`} key=${run.run_id}>
                        <div className="score-card-head">
                          <div className="series-chip">
                            <span className="badge" style=${{ background: run.controller.badge_color }}></span>
                            <span>${run.controller.short}</span>
                          </div>
                          ${run.run_id === winnerRunId ? html`<span className="winner-flag">Best Result</span>` : null}
                        </div>
                        <div className="score-main-value">${formatMetricValue("avg_travel_time_s", run.metrics?.avg_travel_time_s)}</div>
                        <div className=${`metric-delta ${compareToBaseline("avg_travel_time_s", run.metrics?.avg_travel_time_s, baselineRun?.metrics?.avg_travel_time_s).className}`}>
                          ${compareToBaseline("avg_travel_time_s", run.metrics?.avg_travel_time_s, baselineRun?.metrics?.avg_travel_time_s).text}
                        </div>
                      </div>
                    `,
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
                            The map only shows real traffic lights, moving cars, and road segments that are filling up with queues.
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
                      <div className="maps-grid">
                        ${selectedReplays.map(
                          (replay) => html`
                            <${ReplayMap}
                              key=${replay.run_id}
                              replay=${replay}
                              frameIndex=${frameIndex}
                              isWinner=${replay.run_id === winnerRunId}
                            />
                          `,
                        )}
                      </div>
                    </section>

                    <section className="insights-grid">
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
                                ${FEATURED_METRICS.map(
                                  (metricName) => html`
                                    <div className="summary-metric" key=${metricName}>
                                      <span>${metricLabel(metricName)}</span>
                                      <strong>${formatMetricValue(metricName, run.metrics?.[metricName])}</strong>
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

function ReplayMap({ replay, frameIndex, isWinner }) {
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
        points: feature.geometry.coordinates.map(([x, y]) => projection.projectPoint(x, y)),
      })),
    [lineFeatures, projection],
  );
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

  const vehicleStep = Math.max(1, Math.ceil((frame.vehicles || []).length / 550));
  const visibleVehicles = (frame.vehicles || []).filter((_, index) => index % vehicleStep === 0);
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
            <span className="stat-pill">${visibleVehicles.length} cars shown</span>
            <span className="stat-pill">${projectedSignals.length} traffic lights</span>
            <span className="stat-pill">${Math.round(worstQueue)} cars in the worst queue</span>
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
            ${projectedLines.map((line) => {
              const queue = frame.queues?.[line.id] || 0;
              return html`
                <polyline
                  key=${line.id}
                  className=${`congestion-path ${queue >= 8 ? "pulse" : ""}`}
                  points=${pointsToPolyline(line.points)}
                  fill="none"
                  stroke=${queueColor(queue)}
                  strokeWidth=${2.1 + Math.min(queue, 12) * 0.45}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity=${0.9}
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
              const [x, y] = projection.projectPoint(vehicle.x, vehicle.y);
              return html`
                <circle
                  key=${`${replay.run_id}-car-${index}`}
                  className="car-dot moving"
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
