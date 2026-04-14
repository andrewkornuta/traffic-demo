import React from "https://esm.sh/react@18";
import { createRoot } from "https://esm.sh/react-dom@18/client";
import htm from "https://esm.sh/htm@3.1.1";
import { marked } from "https://esm.sh/marked@13.0.2";
import DOMPurify from "https://esm.sh/dompurify@3.1.6";
import mermaid from "https://esm.sh/mermaid@10.9.1?bundle";

const { useEffect, useMemo, useRef, useState } = React;
const html = htm.bind(React.createElement);

const DOCS = [
  {
    key: "overview",
    label: "One-Page Overview",
    eyebrow: "Quick Read",
    title: "Submission-ready summary",
    description: "A concise one-pager that explains the system, the architecture, and the trade-offs with live product screenshots.",
    path: "/project-docs/traffic-analyzer-one-pager.md",
  },
  {
    key: "memo",
    label: "Full Architecture Memo",
    eyebrow: "Deep Dive",
    title: "Technical decision record",
    description: "The full architecture narrative covering the problem framing, system boundaries, algorithms, trade-offs, and production roadmap.",
    path: "/project-docs/traffic-analyzer-architecture-memo.md",
  },
];

marked.setOptions({
  gfm: true,
  breaks: false,
  headerIds: true,
  mangle: false,
});

mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  securityLevel: "loose",
});

function rewriteDocPaths(markdown) {
  return markdown.replaceAll("./assets/", "/project-docs/assets/");
}

function normalizeMarkdown(markdown) {
  return rewriteDocPaths(markdown)
    .replaceAll("\r\n", "\n")
    .trim();
}

function DocCard({ doc, active, onSelect }) {
  return html`
    <button className=${`doc-tab ${active ? "doc-tab-active" : ""}`} onClick=${() => onSelect(doc.key)}>
      <div className="eyebrow">${doc.eyebrow}</div>
      <div className="doc-tab-title">${doc.label}</div>
      <div className="doc-tab-copy">${doc.description}</div>
    </button>
  `;
}

function MarkdownDocument({ activeDoc }) {
  const [rawMarkdown, setRawMarkdown] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const containerRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");

    fetch(activeDoc.path, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Failed to load ${activeDoc.label}.`);
        }
        return response.text();
      })
      .then((text) => {
        if (cancelled) {
          return;
        }
        setRawMarkdown(normalizeMarkdown(text));
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) {
          return;
        }
        setError(err.message || `Failed to load ${activeDoc.label}.`);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeDoc]);

  const renderedHtml = useMemo(() => {
    if (!rawMarkdown) {
      return "";
    }
    return DOMPurify.sanitize(marked.parse(rawMarkdown));
  }, [rawMarkdown]);

  useEffect(() => {
    if (!containerRef.current || !renderedHtml) {
      return;
    }

    const mermaidBlocks = containerRef.current.querySelectorAll("pre code.language-mermaid");
    mermaidBlocks.forEach((node) => {
      const pre = node.parentElement;
      if (!pre || pre.dataset.mermaidProcessed === "true") {
        return;
      }
      const wrapper = document.createElement("div");
      wrapper.className = "mermaid";
      wrapper.textContent = node.textContent || "";
      pre.replaceWith(wrapper);
    });

    mermaid
      .run({ nodes: containerRef.current.querySelectorAll(".mermaid") })
      .catch(() => {
        // Keep the page readable even if Mermaid rendering fails.
      });
  }, [renderedHtml, activeDoc.key]);

  if (loading) {
    return html`
      <section className="panel docs-panel">
        <div className="eyebrow">Loading</div>
        <h2>${activeDoc.label}</h2>
        <p className="legend-copy">Loading the document from the repository.</p>
      </section>
    `;
  }

  if (error) {
    return html`
      <section className="panel docs-panel">
        <div className="eyebrow">Document Error</div>
        <h2>${activeDoc.label}</h2>
        <p className="legend-copy">${error}</p>
        <a className="nav-tab docs-link" href=${activeDoc.path} target="_blank" rel="noreferrer">Open raw markdown</a>
      </section>
    `;
  }

  return html`
    <section className="panel docs-panel">
      <div className="docs-panel-head">
        <div>
          <div className="eyebrow">${activeDoc.eyebrow}</div>
          <h2>${activeDoc.title}</h2>
          <p className="legend-copy">${activeDoc.description}</p>
        </div>
        <a className="nav-tab docs-link" href=${activeDoc.path} target="_blank" rel="noreferrer">Open raw markdown</a>
      </div>
      <article
        ref=${containerRef}
        className="markdown-body"
        dangerouslySetInnerHTML=${{ __html: renderedHtml }}
      ></article>
    </section>
  `;
}

function App() {
  const [activeDocKey, setActiveDocKey] = useState("overview");
  const activeDoc = DOCS.find((doc) => doc.key === activeDocKey) || DOCS[0];

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
          <a href="/demo/architecture.html" className="nav-tab nav-tab-active">Overview and Documentation</a>
        </nav>
      </header>

      <div className="hero-band docs-hero">
        <section className="panel">
          <div className="eyebrow">Overview and Documentation</div>
          <h1>Read the quick overview or open the full architecture memo inside the app.</h1>
          <p className="hero-copy">
            This page now contains the actual project documents from the repository, rendered directly in the product.
            Use the one-page summary for a fast walkthrough, then switch to the full memo for the deeper technical rationale.
          </p>
        </section>

        <section className="panel legend-panel">
          <div className="eyebrow">Included Here</div>
          <div className="legend-list">
            ${DOCS.map(
              (doc) => html`
                <div className="legend-item" key=${doc.key}>
                  <span className="badge" style=${{ background: doc.key === "overview" ? "#22D3EE" : "#A855F7" }}></span>
                  <div>
                    <div className="legend-title">${doc.label}</div>
                    <div className="legend-copy">${doc.description}</div>
                  </div>
                </div>
              `,
            )}
          </div>
        </section>
      </div>

      <section className="docs-switcher">
        ${DOCS.map(
          (doc) =>
            html`<${DocCard} key=${doc.key} doc=${doc} active=${doc.key === activeDoc.key} onSelect=${setActiveDocKey} />`,
        )}
      </section>

      <${MarkdownDocument} activeDoc=${activeDoc} />
    </div>
  `;
}

createRoot(document.getElementById("architecture-root")).render(html`<${App} />`);
