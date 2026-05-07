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


# ── HTML template ──────────────────────────────────────────────────────────────
TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PostHog Engineering Impact — Top 5 Contributors</title>
  <style>
    :root {
      --bg:      #f1f5f9;
      --card:    #ffffff;
      --border:  #e2e8f0;
      --text:    #0f172a;
      --muted:   #64748b;
      --high:    #0ea5e9;
      --radius:  10px;
      --c-high:  #0ea5e9;
      --c-med:   #f59e0b;
      --c-low:   #cbd5e1;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      height: 100vh; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.4;
    }

    .wrapper {
      display: flex; flex-direction: column;
      height: 100vh; padding: 12px 14px; gap: 8px;
    }

    /* ── Header ── */
    .site-header { display: flex; align-items: baseline; gap: 14px; flex-shrink: 0; flex-wrap: wrap; }
    .site-header h1 { font-size: 0.92rem; font-weight: 800; letter-spacing: -0.02em; white-space: nowrap; }
    .header-date   { font-size: 0.70rem; color: var(--muted); white-space: nowrap; }

    /* ── Formula bar ── */
    .formula-bar {
      display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
      background: var(--card); border: 1px solid var(--border);
      border-radius: 8px; padding: 7px 12px; flex-shrink: 0;
    }
    .formula-label { font-size: 0.60rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); white-space: nowrap; }
    .formula-sep   { color: var(--border); }
    .formula-eq    { font-size: 0.68rem; color: var(--text); white-space: nowrap; }
    .fw  { font-weight: 700; }
    .fc-blue   { color: #0369a1; }
    .fc-green  { color: #15803d; }
    .fc-purple { color: #7c3aed; }
    .fc-high   { color: var(--high); }

    /* ── Five-column row ── */
    .engineers-row {
      display: flex; flex: 1; min-height: 0;
      gap: 10px; align-items: stretch;
    }

    /* ── Per-engineer card ── */
    .eng-card {
      flex: 1; min-width: 0;
      background: var(--card); border: 1px solid var(--border);
      border-radius: var(--radius); padding: 14px;
      display: flex; flex-direction: column; gap: 9px;
      overflow: hidden;
    }

    /* ── Top row ── */
    .card-top { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
    .rank-badge {
      width: 22px; height: 22px; border-radius: 50%;
      background: #334155; color: #fff;
      font-weight: 800; font-size: 0.68rem;
      display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    }
    .rank-1 { background: #f59e0b; }
    .rank-2 { background: #94a3b8; }
    .rank-3 { background: #b45309; }
    .avatar { width: 40px; height: 40px; border-radius: 50%; border: 2px solid var(--border); flex-shrink: 0; }
    .eng-identity { flex: 1; min-width: 0; }
    .eng-name { font-size: 0.83rem; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .score-label { font-size: 0.57rem; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
    .eng-score   { font-size: 1.5rem; font-weight: 800; color: var(--high); line-height: 1; }

    /* ── Score progress bar ── */
    .score-progress { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; flex-shrink: 0; }
    .score-progress-fill { height: 100%; background: var(--high); border-radius: 2px; }

    /* ── Stats ── */
    .stats-row { display: flex; gap: 10px; font-size: 0.65rem; color: var(--muted); flex-shrink: 0; flex-wrap: wrap; }
    .stats-row strong { color: var(--text); }

    /* ── Stacked bar ── */
    .stacked-bar {
      display: flex; border-radius: 5px; overflow: hidden;
      background: var(--border); gap: 1px; flex-shrink: 0;
    }
    .stacked-seg { min-width: 1px; }

    /* ── Tier section ── */
    .tier-section { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
    .section-label { font-size: 0.57rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
    .tier-legend { display: flex; gap: 8px; font-size: 0.61rem; }
    .tier-legend span { display: flex; align-items: center; gap: 3px; }
    .ldot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

    /* ── Score breakdown waterfall ── */
    .score-breakdown {
      display: flex; flex-direction: column; gap: 4px;
      background: var(--bg); border-radius: 6px; padding: 8px;
      flex-shrink: 0;
    }
    .breakdown-row { display: flex; align-items: center; gap: 5px; }
    .breakdown-label { font-size: 0.60rem; font-weight: 600; width: 72px; flex-shrink: 0; }
    .breakdown-val   { font-size: 0.70rem; font-weight: 700; width: 38px; text-align: right; flex-shrink: 0; }
    .breakdown-eq    { font-size: 0.58rem; color: var(--muted); width: 60px; flex-shrink: 0; }
    .bar-track { flex: 1; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; }
    .bar-fill  { height: 100%; border-radius: 3px; }
    .breakdown-pct { font-size: 0.57rem; color: var(--muted); width: 30px; text-align: right; flex-shrink: 0; }
    .breakdown-divider { border-top: 1px solid var(--border); margin: 1px 0; }
    .breakdown-total {
      display: flex; justify-content: space-between; align-items: baseline;
      font-size: 0.60rem; color: var(--muted);
    }
    .breakdown-total strong { color: var(--text); }
    .breakdown-norm { font-size: 0.60rem; }

    /* ── Work focus ── */
    .work-focus { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
    .cat-legend { display: flex; flex-wrap: wrap; gap: 2px 8px; font-size: 0.60rem; color: var(--muted); }
    .cat-legend-item { display: flex; align-items: center; gap: 3px; }
    .cat-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

    /* ── Narrative ── */
    .narrative {
      font-size: 0.67rem; color: var(--muted); line-height: 1.4; flex-shrink: 0;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }

    .divider { border: none; border-top: 1px solid var(--border); flex-shrink: 0; }

    /* ── Highlight PRs ── */
    .pr-section { display: flex; flex-direction: column; gap: 7px; flex: 1; min-height: 0; overflow: hidden; }
    .pr-label { font-size: 0.57rem; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); flex-shrink: 0; }
    .pr-item { display: flex; flex-direction: column; gap: 2px; flex-shrink: 0; }
    .pr-top  { display: flex; align-items: baseline; gap: 5px; }
    .tier-badge {
      padding: 1px 5px; border-radius: 3px;
      font-size: 0.55rem; font-weight: 700; text-transform: uppercase;
      white-space: nowrap; flex-shrink: 0;
    }
    .tier-badge.high   { background: #e0f2fe; color: #0369a1; }
    .tier-badge.medium { background: #fff7ed; color: #c2410c; }
    .tier-badge.low    { background: #f1f5f9; color: #475569; }
    .pr-link {
      color: var(--text); font-size: 0.70rem; font-weight: 500;
      text-decoration: none; line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .pr-link:hover { color: var(--high); text-decoration: underline; }
    .pr-rationale {
      font-size: 0.62rem; color: var(--muted); line-height: 1.3;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
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

    const CAT_COLORS = {
      feature: '#10b981', performance: '#f59e0b', refactor: '#8b5cf6',
      bug: '#ef4444', infrastructure: '#64748b', docs: '#0ea5e9',
      testing: '#ec4899', chore: '#94a3b8', security: '#dc2626',
    };
    function catColor(k) { return CAT_COLORS[k] || '#94a3b8'; }

    function esc(s) {
      return String(s ?? '')
        .replace(/&/g,'&amp;').replace(/</g,'&lt;')
        .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    function tierSection(tiers) {
      const total = (tiers.high||0) + (tiers.medium||0) + (tiers.low||0);
      if (!total) return '';
      const hF = tiers.high||0, mF = tiers.medium||0, lF = tiers.low||0;
      return `
        <div class="tier-section">
          <div class="section-label">PR impact tiers &mdash; ${total} PRs scored by LLM</div>
          <div class="stacked-bar" style="height:9px">
            <div class="stacked-seg" style="flex:${hF};background:var(--c-high)" title="High: ${hF}"></div>
            <div class="stacked-seg" style="flex:${mF};background:var(--c-med)"  title="Medium: ${mF}"></div>
            <div class="stacked-seg" style="flex:${lF};background:var(--c-low)"  title="Low: ${lF}"></div>
          </div>
          <div class="tier-legend">
            <span><span class="ldot" style="background:var(--c-high)"></span><strong>${hF}</strong>&nbsp;High</span>
            <span><span class="ldot" style="background:var(--c-med)"></span><strong>${mF}</strong>&nbsp;Medium</span>
            <span><span class="ldot" style="background:var(--c-low)"></span><strong>${lF}</strong>&nbsp;Low</span>
          </div>
        </div>`;
    }

    function workFocus(cats) {
      const entries = Object.entries(cats).filter(([,v]) => v > 0).slice(0, 6);
      if (!entries.length) return '';
      const segs = entries.map(([k, v]) =>
        `<div class="stacked-seg" style="flex:${(v*100).toFixed(1)};background:${catColor(k)}" title="${k.replace(/_/g,' ')}: ${Math.round(v*100)}%"></div>`
      ).join('');
      const legend = entries.map(([k, v]) =>
        `<span class="cat-legend-item"><span class="cat-dot" style="background:${catColor(k)}"></span>${esc(k.replace(/_/g,' '))} ${Math.round(v*100)}%</span>`
      ).join('');
      return `
        <div class="work-focus">
          <div class="section-label">Work focus</div>
          <div class="stacked-bar" style="height:9px">${segs}</div>
          <div class="cat-legend">${legend}</div>
        </div>`;
    }

    function scoreBreakdown(eng, maxRawScore) {
      // Weighted contributions — these three values sum to final_score
      const tierC  = (eng.tier_score          || 0) * 0.5;
      const collC  = (eng.collaboration_score || 0) * 0.3;
      const qualC  = (eng.avg_structural_score|| 0) * 0.2;
      const raw    = eng.final_score || (tierC + collC + qualC);

      function brow(label, color, rawVal, weight, contrib, total) {
        const pct = total > 0 ? (contrib / total * 100) : 0;
        const barW = pct.toFixed(1);
        return `
          <div class="breakdown-row">
            <div class="breakdown-label" style="color:${color}">${label}</div>
            <div class="breakdown-val">${rawVal}</div>
            <div class="breakdown-eq" style="color:var(--muted)">×${weight} = ${contrib.toFixed(3)}</div>
            <div class="bar-track"><div class="bar-fill" style="width:${barW}%;background:${color}"></div></div>
            <div class="breakdown-pct">${pct.toFixed(1)}%</div>
          </div>`;
      }

      return `
        <div class="score-breakdown">
          <div class="section-label">Score breakdown &mdash; how the raw score is computed</div>
          ${brow('PR Impact',     '#0369a1', (eng.tier_score||0).toFixed(1),          '0.5', tierC, raw)}
          ${brow('Collaboration', '#15803d', (eng.collaboration_score||0).toFixed(3), '0.3', collC, raw)}
          ${brow('Code Quality',  '#7c3aed', (eng.avg_structural_score||0).toFixed(3),'0.2', qualC, raw)}
          <div class="breakdown-divider"></div>
          <div class="breakdown-total">
            <span>Raw total: <strong>${raw.toFixed(3)}</strong></span>
            <span class="breakdown-norm">
              &divide; top score (${maxRawScore.toFixed(3)}) &times; 100
              = <strong class="fc-high">${(eng.normalized_score||0).toFixed(1)}</strong>
            </span>
          </div>
        </div>`;
    }

    function makeCard(eng, rank, maxRawScore) {
      const narrative = NARRATIVES[eng.author] || '';
      const tiers     = eng.impact_tiers    || {};
      const cats      = eng.work_categories || {};
      const rankClass = rank <= 3 ? `rank-${rank}` : '';
      const score     = (eng.normalized_score || 0).toFixed(1);

      const prs = (eng.highlight_prs || []).slice(0, 3).map(pr => {
        const tier = (pr.impact_tier || 'low').toLowerCase();
        const url  = `https://github.com/PostHog/posthog/pull/${pr.number}`;
        return `
          <div class="pr-item">
            <div class="pr-top">
              <span class="tier-badge ${esc(tier)}">${tier.toUpperCase()}</span>
              <a class="pr-link" href="${esc(url)}" target="_blank" rel="noopener">
                #${pr.number} ${esc((pr.title || '').slice(0, 80))}
              </a>
            </div>
            ${pr.rationale ? `<div class="pr-rationale">${esc(pr.rationale)}</div>` : ''}
          </div>`;
      }).join('');

      return `
        <div class="eng-card">

          <div class="card-top">
            <div class="rank-badge ${rankClass}">${rank}</div>
            <img class="avatar"
                 src="https://github.com/${esc(eng.author)}.png?size=80"
                 alt="${esc(eng.author)}" loading="lazy"
                 onerror="this.onerror=null;this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 40 40%22%3E%3Crect fill=%22%23e2e8f0%22 width=%2240%22 height=%2240%22/%3E%3C/svg%3E'" />
            <div class="eng-identity">
              <div class="eng-name">${esc(eng.author)}</div>
              <div class="score-label">impact score &mdash; relative to #1 contributor</div>
            </div>
            <div class="eng-score">${score}</div>
          </div>

          <div class="score-progress" title="${score} = ${(eng.final_score||0).toFixed(3)} / top × 100">
            <div class="score-progress-fill" style="width:${score}%"></div>
          </div>

          <div class="stats-row">
            <span><strong>${eng.pr_count      || 0}</strong> PRs merged</span>
            <span><strong>${eng.reviews_given || 0}</strong> reviews given</span>
            <span><strong>${eng.distinct_authors_reviewed || 0}</strong> authors reviewed</span>
          </div>

          ${tierSection(tiers)}

          ${scoreBreakdown(eng, maxRawScore)}

          ${workFocus(cats)}

          ${narrative ? `<div class="narrative">${esc(narrative)}</div>` : ''}

          <hr class="divider" />

          <div class="pr-section">
            <div class="pr-label">Highlight PRs</div>
            ${prs || '<div class="narrative">No PRs scored.</div>'}
          </div>

        </div>`;
    }

    function renderDashboard() {
      const top5 = TOP5.top_5 || [];

      // Normalization: top engineer = 100
      const maxRaw = Math.max(...top5.map(e => e.final_score || 0), 1);
      top5.forEach(e => {
        if (e.normalized_score == null)
          e.normalized_score = Math.round((e.final_score / maxRaw) * 1000) / 10;
      });

      const date = new Date().toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
      document.getElementById('root').innerHTML = `
        <div class="wrapper">
          <header class="site-header">
            <h1>PostHog Engineering Impact &mdash; Top 5 Contributors (90 days)</h1>
            <span class="header-date">${date}</span>
          </header>
          <div class="formula-bar">
            <span class="formula-label">Ranking formula</span>
            <span class="formula-sep">|</span>
            <span class="formula-eq fw">Raw score</span>
            <span class="formula-eq">=</span>
            <span class="formula-eq">(<span class="fw fc-blue">PR Impact</span> &times; 0.5)</span>
            <span class="formula-eq">+</span>
            <span class="formula-eq">(<span class="fw fc-green">Collaboration</span> &times; 0.3)</span>
            <span class="formula-eq">+</span>
            <span class="formula-eq">(<span class="fw fc-purple">Code Quality</span> &times; 0.2)</span>
            <span class="formula-sep">|</span>
            <span class="formula-eq fw">Score</span>
            <span class="formula-eq">= raw &divide; top raw &times; 100&nbsp;&nbsp;(top contributor = 100 by definition)</span>
          </div>
          <div class="engineers-row" id="engineers-row"></div>
        </div>`;

      const row = document.getElementById('engineers-row');
      top5.forEach((eng, i) => row.insertAdjacentHTML('beforeend', makeCard(eng, i + 1, maxRaw)));
    }

    document.addEventListener('DOMContentLoaded', renderDashboard);
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
