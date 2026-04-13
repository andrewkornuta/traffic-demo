import React from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";
import htm from "https://esm.sh/htm@3.1.1";

const html = htm.bind(React.createElement);

function App() {
  return html`
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"></div>
          <div>
            <div className="brand-title">Andrew's Traffic Analyzer - City Traffic Flow Optimizer</div>
            <div className="brand-subtitle">See how different smart controllers improve traffic</div>
          </div>
        </div>
        <nav className="nav-tabs">
          <a href="http://127.0.0.1:8501/" className="nav-tab">Operator Console</a>
          <a href="/demo/" className="nav-tab">Traffic Comparison Viewer</a>
          <a href="/demo/architecture.html" className="nav-tab nav-tab-active">Architecture</a>
        </nav>
      </header>

      <div className="hero-band">
        <section className="panel">
          <div className="eyebrow">Architecture</div>
          <h1>How the product turns a street idea into a traffic comparison</h1>
          <p className="hero-copy">
            The operator loads a city grid or a real neighborhood, writes a plain-English what-if idea, and the system runs several traffic-control strategies side by side so the result is easy to understand.
          </p>
        </section>
        <section className="panel">
          <div className="eyebrow">How This Works</div>
          <div className="legend-list">
            <div className="legend-item">
              <span className="badge" style=${{ background: "#94A3B8" }}></span>
              <div><div className="legend-title">Basic Fixed-Time Controller</div><div className="legend-copy">Lights follow a fixed schedule, no matter how busy traffic is.</div></div>
            </div>
            <div className="legend-item">
              <span className="badge" style=${{ background: "#22D3EE" }}></span>
              <div><div className="legend-title">Real-Time Smart Controller</div><div className="legend-copy">Changes lights every few seconds based on actual car counts and queues.</div></div>
            </div>
            <div className="legend-item">
              <span className="badge" style=${{ background: "#A855F7" }}></span>
              <div><div className="legend-title">Evolution-Optimized Controller</div><div className="legend-copy">Tests thousands of timing plans in simulation and picks the winner.</div></div>
            </div>
          </div>
        </section>
      </div>

      <div className="viewer-layout">
        <section className="panel">
          <div className="eyebrow">Step 1</div>
          <h3>Load a road network</h3>
          <p className="legend-copy">Start with the built-in city grid or pull in a real neighborhood. The system creates roads, intersections, sensors, and a repeatable traffic pattern.</p>
        </section>
        <section className="panel">
          <div className="eyebrow">Step 2</div>
          <h3>Describe a what-if idea in plain English</h3>
          <p className="legend-copy">The Smart Scenario Creator turns plain language like “replace this traffic light with a roundabout” into a safe, structured street-change proposal.</p>
        </section>
        <section className="panel">
          <div className="eyebrow">Step 3</div>
          <h3>Run the three smart controllers</h3>
          <p className="legend-copy">Each controller runs on the same traffic pattern so the comparison is fair. Results are stored with travel time, delay, and cars-through metrics.</p>
        </section>
      </div>

      <section className="panel" style=${{ marginTop: "18px" }}>
        <div className="eyebrow">System Flow</div>
        <h3>Plain-English view of the backend</h3>
        <div className="legend-list">
          <div className="legend-item"><div><div className="legend-title">1. Operator Console</div><div className="legend-copy">Loads a network, creates a scenario, and launches controller runs.</div></div></div>
          <div className="legend-item"><div><div className="legend-title">2. Fast API service</div><div className="legend-copy">Receives requests, stores runs, and serves replay data to both interfaces.</div></div></div>
          <div className="legend-item"><div><div className="legend-title">3. Traffic simulator</div><div className="legend-copy">Moves vehicles through the road graph, applies traffic lights, and records congestion over time.</div></div></div>
          <div className="legend-item"><div><div className="legend-title">4. Comparison viewer</div><div className="legend-copy">Shows the side-by-side replay, trend chart, scenario summary, and exportable GIF.</div></div></div>
        </div>
      </section>
    </div>
  `;
}

createRoot(document.getElementById("architecture-root")).render(html`<${App} />`);
