#!/usr/bin/env python3
"""
Recompute engineer rankings incorporating LLM impact-tier results.
Reads:  llm_scores.json, structural_scores.json, top_candidates.json
Writes: top_5_engineers.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

LLM_FILE         = "outputs/llm_scores.json"
STRUCTURAL_FILE  = "outputs/structural_scores.json"
TOP_CANDS_FILE   = "outputs/top_candidates.json"
OUTPUT_FILE      = "outputs/top_5_engineers.json"
EVALUATION_DAYS  = 90

TIER_POINTS   = {"high": 3.0, "medium": 1.5, "low": 0.5}
TIER_ORDER    = {"high": 3, "medium": 2, "low": 1}      # for sorting highlight PRs

# ── Load inputs ───────────────────────────────────────────────────────────────

def load_json(path: str) -> dict | list:
    p = Path(path)
    if not p.exists():
        print(f"Error: {path} not found.", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    print("Loading input files…", flush=True)
    llm_data        = load_json(LLM_FILE)
    structural_data = load_json(STRUCTURAL_FILE)
    top_cands_data  = load_json(TOP_CANDS_FILE)

    # ── Index LLM scores by PR number ─────────────────────────────────────────
    llm_by_pr: dict[int, dict] = {
        int(e["pr_number"]): e
        for e in llm_data["prs"]
        if not e.get("error")              # exclude failed scores
    }
    print(f"  {len(llm_by_pr)} LLM-scored PRs loaded.", flush=True)

    # ── Index structural PRs by number ────────────────────────────────────────
    structural_by_pr: dict[int, dict] = {
        pr["number"]: pr for pr in structural_data["prs"]
    }
    author_stats: dict[str, dict] = structural_data.get("author_stats", {})

    # ── Determine the top-20 author set ───────────────────────────────────────
    top_candidates: list[dict] = top_cands_data["top_candidates"]
    print(f"  {len(top_candidates)} top-candidate authors.", flush=True)

    # ── Score each of the top-20 ──────────────────────────────────────────────
    ranked: list[dict] = []

    for candidate in top_candidates:
        author     = candidate["author"]
        pr_numbers = [int(n) for n in candidate["pr_ids"]]

        # Split into LLM-scored vs. missing
        llm_entries     = [llm_by_pr[n] for n in pr_numbers if n in llm_by_pr]
        struct_entries  = [structural_by_pr[n] for n in pr_numbers if n in structural_by_pr]

        if not llm_entries:
            # Can't compute tier_score without LLM data — skip gracefully
            print(f"  Warning: no LLM scores for {author}, skipping.", flush=True)
            continue

        # 1. Impact tier distribution ─────────────────────────────────────────
        tier_counts: dict[str, int] = defaultdict(int)
        for e in llm_entries:
            tier = e.get("impact_tier", "unknown")
            if tier in TIER_POINTS:
                tier_counts[tier] += 1

        high_c   = tier_counts.get("high",   0)
        medium_c = tier_counts.get("medium", 0)
        low_c    = tier_counts.get("low",    0)
        tier_score = (
            high_c   * TIER_POINTS["high"]   +
            medium_c * TIER_POINTS["medium"] +
            low_c    * TIER_POINTS["low"]
        )

        # 2. Work category mix ────────────────────────────────────────────────
        cat_counts: dict[str, int] = defaultdict(int)
        for e in llm_entries:
            cat = e.get("category", "unknown")
            cat_counts[cat] += 1
        total_llm = len(llm_entries)
        work_categories = {
            cat: round(count / total_llm, 3)
            for cat, count in sorted(cat_counts.items(), key=lambda kv: -kv[1])
        }

        # 3. Collaboration signals ─────────────────────────────────────────────
        astats = author_stats.get(author, {})
        reviews_given          = candidate.get("reviews_given", astats.get("reviewer_count", 0))
        distinct_authors_revd  = candidate.get("distinct_authors_reviewed",
                                               len(astats.get("distinct_reviewers_reviewed_by_this_author") or []))

        collaboration_score = min((reviews_given / 100) * 0.3, 0.5)

        # 4. Avg structural score (non-trivial PRs only) ──────────────────────
        substantive = [
            p for p in struct_entries
            if not p.get("is_bot") and not p.get("is_trivial")
        ]
        avg_structural = (
            sum(p["combined_score"] for p in substantive) / len(substantive)
            if substantive else 0.0
        )

        # 5. Final score ──────────────────────────────────────────────────────
        final_score = (
            tier_score          * 0.5 +
            collaboration_score * 0.3 +
            avg_structural      * 0.2
        )

        # 6. Top-3 highlight PRs (high tier first, then by structural score) ──
        scored_prs = []
        for n in pr_numbers:
            llm = llm_by_pr.get(n)
            st  = structural_by_pr.get(n)
            if not llm or not st:
                continue
            scored_prs.append({
                "number":       n,
                "title":        llm.get("title") or st.get("title", ""),
                "impact_tier":  llm.get("impact_tier", "unknown"),
                "category":     llm.get("category", "unknown"),
                "rationale":    llm.get("rationale", ""),
                "_tier_ord":    TIER_ORDER.get(llm.get("impact_tier", ""), 0),
                "_struct_score": st.get("combined_score", 0.0),
            })

        scored_prs.sort(key=lambda p: (p["_tier_ord"], p["_struct_score"]), reverse=True)
        highlight_prs = [
            {k: v for k, v in p.items() if not k.startswith("_")}
            for p in scored_prs[:3]
        ]

        ranked.append({
            "author":                   author,
            "final_score":              round(final_score, 4),
            "tier_score":               round(tier_score, 4),
            "collaboration_score":      round(collaboration_score, 4),
            "avg_structural_score":     round(avg_structural, 4),
            "impact_tiers": {
                "high":   high_c,
                "medium": medium_c,
                "low":    low_c,
            },
            "work_categories":          work_categories,
            "pr_count":                 len(pr_numbers),
            "non_trivial_pr_count":     candidate.get("non_trivial_pr_count", len(substantive)),
            "llm_scored_pr_count":      total_llm,
            "reviews_given":            reviews_given,
            "distinct_authors_reviewed": distinct_authors_revd,
            "highlight_prs":            highlight_prs,
        })

    # ── Sort, add normalized_score (0–100 vs top engineer), slice top 5 ─────
    ranked.sort(key=lambda e: e["final_score"], reverse=True)
    max_score = ranked[0]["final_score"] if ranked else 1.0
    for e in ranked:
        e["normalized_score"] = round(e["final_score"] / max_score * 100, 1) if max_score > 0 else 0.0
    top5 = ranked[:5]

    for i, entry in enumerate(top5, 1):
        entry["rank"] = i

    # ── Build output ──────────────────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "top_5": [
            {
                "rank":                     e["rank"],
                "author":                   e["author"],
                "normalized_score":         e["normalized_score"],
                "final_score":              e["final_score"],
                "tier_score":               e["tier_score"],
                "collaboration_score":      e["collaboration_score"],
                "avg_structural_score":     e["avg_structural_score"],
                "impact_tiers":             e["impact_tiers"],
                "work_categories":          e["work_categories"],
                "pr_count":                 e["pr_count"],
                "non_trivial_pr_count":     e["non_trivial_pr_count"],
                "llm_scored_pr_count":      e["llm_scored_pr_count"],
                "reviews_given":            e["reviews_given"],
                "distinct_authors_reviewed": e["distinct_authors_reviewed"],
                "highlight_prs":            e["highlight_prs"],
            }
            for e in top5
        ],
        "full_ranking": [
            {
                "rank":              i + 1,
                "author":            e["author"],
                "normalized_score":  e["normalized_score"],
                "final_score":       e["final_score"],
                "tier_score":        e["tier_score"],
                "pr_count":          e["pr_count"],
                "impact_tiers":      e["impact_tiers"],
            }
            for i, e in enumerate(ranked)
        ],
        "metadata": {
            "ranked_at":               now_iso,
            "evaluation_period_days":  EVALUATION_DAYS,
            "engineers_evaluated":     len(ranked),
            "total_llm_scored_prs":    len(llm_by_pr),
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {OUTPUT_FILE}\n")
    _print_summary(top5, ranked)


# ── Human-readable output ─────────────────────────────────────────────────────

def _bar(value: float, max_val: float, width: int = 20) -> str:
    if max_val == 0:
        return " " * width
    filled = round(value * width / max_val)
    return "█" * filled + "░" * (width - filled)


def _print_summary(top5: list[dict], all_ranked: list[dict]) -> None:
    max_final = top5[0]["final_score"] if top5 else 1.0

    # ── Top-5 detail cards ────────────────────────────────────────────────────
    for e in top5:
        tiers  = e["impact_tiers"]
        cats   = e["work_categories"]
        bar    = _bar(e["final_score"], max_final)
        total  = tiers["high"] + tiers["medium"] + tiers["low"]

        print(f"{'─' * 64}")
        print(
            f"  #{e['rank']}  {e['author']:<22}  "
            f"{e['normalized_score']:.1f}/100  (raw {e['final_score']:.4f})  {bar}"
        )
        print(
            f"      PRs: {e['pr_count']} total / {e['non_trivial_pr_count']} substantive"
            f"  |  tiers: {tiers['high']}H {tiers['medium']}M {tiers['low']}L / {total}"
        )
        print(
            f"      tier_score {e['tier_score']:.2f}"
            f"  collab {e['collaboration_score']:.3f}"
            f"  structural {e['avg_structural_score']:.3f}"
        )
        print(
            f"      reviews_given {e['reviews_given']}"
            f"  distinct_authors {e['distinct_authors_reviewed']}"
        )

        # Category sparkline
        cat_parts = "  ".join(
            f"{cat}:{pct:.0%}" for cat, pct in list(cats.items())[:5]
        )
        print(f"      categories: {cat_parts}")

        # Highlight PRs
        print("      top PRs:")
        for pr in e["highlight_prs"]:
            tier_tag = {"high": "[H]", "medium": "[M]", "low": "[L]"}.get(
                pr["impact_tier"], "[ ]"
            )
            title_short = (pr["title"] or "")[:62]
            print(f"        {tier_tag} #{pr['number']}  {title_short}")
            if pr.get("rationale"):
                print(f"             {pr['rationale'][:80]}")

    print(f"{'─' * 64}")

    # ── Full ranking table ────────────────────────────────────────────────────
    print(f"\nFull top-{len(all_ranked)} ranking (final_score):\n")
    hdr = f"  {'Rank':<5} {'Author':<22} {'Score':>7} {'Tier▲':>6} {'PRs':>5} {'H':>4} {'M':>4} {'L':>4}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for e in all_ranked:
        t = e["impact_tiers"]
        marker = "◀ top 5" if e.get("rank") else ""
        print(
            f"  {e.get('rank', all_ranked.index(e) + 1):<5} "
            f"{e['author']:<22} "
            f"{e['normalized_score']:>7.1f} "
            f"{e['tier_score']:>6.2f} "
            f"{e['pr_count']:>5} "
            f"{t['high']:>4} "
            f"{t['medium']:>4} "
            f"{t['low']:>4}  {marker}"
        )


if __name__ == "__main__":
    main()
