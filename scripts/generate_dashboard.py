#!/usr/bin/env python3
"""
Generate dashboard.html from top_5_engineers.json and top_5_narratives.json.
Usage: python generate_dashboard.py
"""

import json
import sys
from pathlib import Path

TOP5_FILE       = "outputs/top_5_engineers.json"
NARRATIVES_FILE = "outputs/top_5_narratives.json"
OUTPUT_FILE     = "index.html"


def load_json_safe(path, default):
    p = Path(path)
    if not p.exists():
        print(f"  Note: {path} not found — using defaults.", file=sys.stderr)
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main():
    print(f"Reading {TOP5_FILE}…")
    top5 = load_json_safe(TOP5_FILE, {"top_5": [], "metadata": {}})

    print(f"Reading {NARRATIVES_FILE}…")
    narratives = load_json_safe(NARRATIVES_FILE, {"narratives": {}})

    html = TEMPLATE \
        .replace("__TOP5_DATA__",       json.dumps(top5,       ensure_ascii=False)) \
        .replace("__NARRATIVES_DATA__", json.dumps(narratives, ensure_ascii=False))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    n = len(top5.get("top_5") or [])
    print(f"Wrote {OUTPUT_FILE}  ({n} engineers)")


# ── HTML template (CSS + JS inline, data injected by Python) ──────────────────
TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PostHog Engineering Impact — Top 5 Contributors</title>
  <style>
    :root {
      --bg:     #f1f5f9;
      --card:   #ffffff;
      --border: #e2e8f0;
      --text:   #0f172a;
      --muted:  #64748b;
      --high:   #0ea5e9;
      --radius: 10px;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      height: 100vh;
      overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.4;
    }

    .wrapper {
      display: flex;
      flex-direction: column;
      height: 100vh;
      padding: 12px 14px;
      gap: 10px;
    }

    /* ── Header ── */
    .site-header { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
    .header-main { display: flex; align-items: baseline; gap: 10px; }
    .site-header h1   { font-size: 0.95rem; font-weight: 800; letter-spacing: -0.02em; }
    .header-date      { font-size: 0.72rem; color: var(--muted); }
    .header-note      { font-size: 0.63rem; color: var(--muted); }

    /* ── Five-column row ── */
    .engineers-row {
      display: flex;
      gap: 10px;
      flex: 1;
      min-height: 0;
    }

    /* ── Per-engineer card ── */
    .eng-card {
      flex: 1;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 7px;
      min-width: 0;
      overflow: hidden;
    }

    /* ── Top row: rank badge · avatar · name · score ── */
    .card-top {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-shrink: 0;
    }
    .rank-badge {
      width: 22px; height: 22px;
      border-radius: 50%;
      background: #334155; color: #fff;
      font-weight: 800; font-size: 0.68rem;
      display: flex; align-items: center; justify-content: center;
      flex-shrink: 0;
    }
    .rank-1 { background: #f59e0b; }
    .rank-2 { background: #94a3b8; }
    .rank-3 { background: #b45309; }
    .avatar {
      width: 34px; height: 34px;
      border-radius: 50%;
      border: 2px solid var(--border);
      flex-shrink: 0;
    }
    .eng-identity { flex: 1; min-width: 0; }
    .eng-name {
      font-size: 0.85rem; font-weight: 700;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .score-label { font-size: 0.58rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
    .eng-score   { font-size: 1.25rem; font-weight: 800; color: var(--high); line-height: 1; cursor: help; }

    /* ── Tier pills ── */
    .tiers-row { display: flex; gap: 4px; flex-shrink: 0; }
    .tier-pill {
      padding: 2px 6px; border-radius: 4px;
      font-size: 0.65rem; font-weight: 700;
    }
    .tier-pill.high   { background: #e0f2fe; color: #0369a1; }
    .tier-pill.medium { background: #fff7ed; color: #c2410c; }
    .tier-pill.low    { background: #f1f5f9; color: #475569; }

    /* ── Stats ── */
    .stats-row {
      display: flex; flex-wrap: wrap; gap: 2px 10px;
      font-size: 0.67rem; color: var(--muted); flex-shrink: 0;
    }
    .stats-row strong { color: var(--text); }

    /* ── Work categories ── */
    .cats-row {
      font-size: 0.65rem; color: var(--muted); flex-shrink: 0;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }

    /* ── Narrative ── */
    .narrative {
      font-size: 0.68rem; color: var(--muted); line-height: 1.4;
      flex-shrink: 0;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }

    .divider { border: none; border-top: 1px solid var(--border); flex-shrink: 0; }

    /* ── Highlight PRs ── */
    .pr-section {
      flex: 1; min-height: 0;
      display: flex; flex-direction: column; gap: 6px;
      overflow: hidden;
    }
    .pr-label {
      font-size: 0.58rem; font-weight: 700;
      text-transform: uppercase; letter-spacing: .05em;
      color: var(--muted); flex-shrink: 0;
    }
    .pr-item { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
    .pr-top  { display: flex; align-items: baseline; gap: 5px; }
    .tier-badge {
      padding: 1px 5px; border-radius: 3px;
      font-size: 0.56rem; font-weight: 700; text-transform: uppercase;
      white-space: nowrap; flex-shrink: 0;
    }
    .tier-badge.high   { background: #e0f2fe; color: #0369a1; }
    .tier-badge.medium { background: #fff7ed; color: #c2410c; }
    .tier-badge.low    { background: #f1f5f9; color: #475569; }
    .pr-link {
      color: var(--text); font-size: 0.71rem; font-weight: 500;
      text-decoration: none; line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .pr-link:hover { color: var(--high); text-decoration: underline; }
    .pr-rationale {
      font-size: 0.63rem; color: var(--muted); line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical;
      overflow: hidden;
    }
  </style>
</head>
<body>
  <script>
    window.__TOP5__       = __TOP5_DATA__;
    window.__NARRATIVES__ = __NARRATIVES_DATA__;
  </script>
  <div id="root"></div>
  <script>
    "use strict";
    const TOP5       = window.__TOP5__       || { top_5: [] };
    const NARRATIVES = (window.__NARRATIVES__ || {}).narratives || {};

    function esc(s) {
      return String(s ?? "")
        .replace(/&/g,"&amp;").replace(/</g,"&lt;")
        .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    }

    function makeCard(eng, rank) {
      const narrative = NARRATIVES[eng.author] || "";
      const tiers     = eng.impact_tiers    || {};
      const cats      = eng.work_categories || {};
      const rankClass = rank <= 3 ? `rank-${rank}` : "";

      const catStr = Object.entries(cats).slice(0, 3)
        .map(([k, v]) => `${k.replace(/_/g," ")} ${Math.round(v*100)}%`)
        .join("  ·  ");

      const prs = (eng.highlight_prs || []).slice(0, 2).map(pr => {
        const tier = (pr.impact_tier || "low").toLowerCase();
        const url  = `https://github.com/PostHog/posthog/pull/${pr.number}`;
        return `
          <div class="pr-item">
            <div class="pr-top">
              <span class="tier-badge ${esc(tier)}">${tier.toUpperCase()}</span>
              <a class="pr-link" href="${esc(url)}" target="_blank" rel="noopener">
                #${pr.number} ${esc((pr.title || "").slice(0, 80))}
              </a>
            </div>
            ${pr.rationale ? `<div class="pr-rationale">${esc(pr.rationale)}</div>` : ""}
          </div>`;
      }).join("");

      return `
        <div class="eng-card">
          <div class="card-top">
            <div class="rank-badge ${rankClass}">${rank}</div>
            <img class="avatar"
                 src="https://github.com/${esc(eng.author)}.png?size=72"
                 alt="${esc(eng.author)}" loading="lazy"
                 onerror="this.onerror=null;this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 34 34%22%3E%3Crect fill=%22%23e2e8f0%22 width=%2234%22 height=%2234%22/%3E%3C/svg%3E'" />
            <div class="eng-identity">
              <div class="eng-name">${esc(eng.author)}</div>
              <div class="score-label">impact score / 100</div>
            </div>
            <div class="eng-score" title="Top engineer = 100">${(eng.normalized_score || 0).toFixed(1)}</div>
          </div>

          <div class="tiers-row">
            <span class="tier-pill high">${tiers.high   || 0}&nbsp;H</span>
            <span class="tier-pill medium">${tiers.medium || 0}&nbsp;M</span>
            <span class="tier-pill low">${tiers.low    || 0}&nbsp;L</span>
          </div>

          <div class="stats-row">
            <span><strong>${eng.pr_count      || 0}</strong> PRs</span>
            <span><strong>${eng.reviews_given || 0}</strong> reviews given</span>
            <span>Tier&nbsp;<strong>${(eng.tier_score||0).toFixed(1)}</strong>&nbsp;&middot;&nbsp;Collab&nbsp;<strong>${(eng.collaboration_score||0).toFixed(2)}</strong>&nbsp;&middot;&nbsp;Struct&nbsp;<strong>${(eng.avg_structural_score||0).toFixed(2)}</strong></span>
          </div>

          <div class="cats-row">${esc(catStr)}</div>

          ${narrative ? `<div class="narrative">${esc(narrative)}</div>` : ""}

          <hr class="divider" />

          <div class="pr-section">
            <div class="pr-label">Highlight PRs</div>
            ${prs || `<div class="narrative">No PRs scored.</div>`}
          </div>
        </div>`;
    }

    function renderDashboard() {
      const date = new Date().toLocaleDateString("en-US", { month: "long", year: "numeric" });
      document.getElementById("root").innerHTML = `
        <div class="wrapper">
          <header class="site-header">
            <div class="header-main">
              <h1>PostHog Engineering Impact &mdash; Top 5 Contributors (90 days)</h1>
              <p class="header-date">${date}</p>
            </div>
            <p class="header-note">Scores are normalized to 100 for the top contributor in the 90-day window &mdash; an engineer at 65 contributed roughly 65% of the impact of the #1 ranked contributor.</p>
          </header>
          <div class="engineers-row" id="engineers-row"></div>
        </div>`;

      const row = document.getElementById("engineers-row");
      (TOP5.top_5 || []).forEach((eng, i) => {
        row.insertAdjacentHTML("beforeend", makeCard(eng, i + 1));
      });
    }

    document.addEventListener("DOMContentLoaded", renderDashboard);
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
