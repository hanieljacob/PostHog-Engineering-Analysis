#!/usr/bin/env python3
"""
Rank engineers by structural impact score.
Reads:  structural_scores.json
Writes: top_candidates.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

INPUT_FILE = "outputs/structural_scores.json"
OUTPUT_FILE = "outputs/top_candidates.json"
TOP_N = 20


def main() -> None:
    path = Path(INPUT_FILE)
    if not path.exists():
        print(f"Error: {INPUT_FILE} not found. Run score_prs.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {INPUT_FILE}…", flush=True)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    prs: list[dict] = data["prs"]
    author_stats: dict[str, dict] = data.get("author_stats", {})
    print(f"  {len(prs)} total PRs across all authors.", flush=True)

    # ── Build per-author views from the PR list ───────────────────────────────

    # author → all their PRs
    authored: dict[str, list[dict]] = defaultdict(list)
    # reviewer → number of PRs they appeared as reviewer on
    reviews_given: dict[str, int] = defaultdict(int)

    for pr in prs:
        author = pr.get("author") or "unknown"
        authored[author].append(pr)
        for reviewer in (pr.get("reviews") or {}).get("distinct_reviewers") or []:
            reviews_given[reviewer] += 1

    # ── Score and filter each author ──────────────────────────────────────────

    all_candidates: list[dict] = []

    for author, pr_list in authored.items():
        non_trivial = [
            p for p in pr_list
            if not p.get("is_bot") and not p.get("is_trivial")
        ]
        # Exclude authors whose entire body of work is bots / trivial bumps
        if not non_trivial:
            continue

        total_score = sum(p["combined_score"] for p in pr_list)
        avg_score = total_score / len(pr_list)

        # distinct_authors_reviewed comes from score_prs's author_stats
        reviewed_list: list[str] = (
            author_stats.get(author, {}).get("distinct_reviewers_reviewed_by_this_author") or []
        )

        all_candidates.append({
            "author": author,
            "total_score": round(total_score, 4),
            "pr_count": len(pr_list),
            "non_trivial_pr_count": len(non_trivial),
            "avg_score": round(avg_score, 4),
            "reviews_given": reviews_given.get(author, 0),
            "distinct_authors_reviewed": len(reviewed_list),
            # Keep PR numbers sorted ascending for determinism
            "pr_ids": sorted(p["number"] for p in pr_list),
        })

    # ── Rank and slice ────────────────────────────────────────────────────────

    all_candidates.sort(key=lambda c: c["total_score"], reverse=True)
    top: list[dict] = all_candidates[:TOP_N]

    # ── Build output document ─────────────────────────────────────────────────

    top_author_set = {c["author"] for c in top}
    pool_prs = [p for p in prs if (p.get("author") or "unknown") in top_author_set]
    total_pool_prs = sum(c["pr_count"] for c in top)
    avg_pool_score = (
        round(sum(p["combined_score"] for p in pool_prs) / len(pool_prs), 4)
        if pool_prs else 0.0
    )

    top_candidates_out = [
        {
            "rank": rank,
            "author": c["author"],
            "total_score": c["total_score"],
            "pr_count": c["pr_count"],
            "non_trivial_pr_count": c["non_trivial_pr_count"],
            "avg_score": c["avg_score"],
            "reviews_given": c["reviews_given"],
            "distinct_authors_reviewed": c["distinct_authors_reviewed"],
            "pr_ids": c["pr_ids"],
        }
        for rank, c in enumerate(top, 1)
    ]

    output = {
        "top_candidates": top_candidates_out,
        "stats": {
            "total_candidates": len(top_candidates_out),
            "total_prs_in_candidate_pool": total_pool_prs,
            "avg_score_in_pool": avg_pool_score,
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {OUTPUT_FILE}\n")

    # ── Human-readable table ──────────────────────────────────────────────────

    col = {
        "rank":         5,
        "author":       22,
        "total_score":  12,
        "pr_count":      8,
        "non_trivial":  11,
        "avg_score":     9,
        "rev_given":    13,
        "distinct_rev": 14,
    }

    header = (
        f"{'Rank':<{col['rank']}} "
        f"{'Author':<{col['author']}} "
        f"{'Total Score':>{col['total_score']}} "
        f"{'PRs':>{col['pr_count']}} "
        f"{'Non-Trivial':>{col['non_trivial']}} "
        f"{'Avg Score':>{col['avg_score']}} "
        f"{'Reviews Given':>{col['rev_given']}} "
        f"{'Distinct Revd':>{col['distinct_rev']}}"
    )
    divider = (
        f"{'-' * col['rank']} "
        f"{'-' * col['author']} "
        f"{'-' * col['total_score']} "
        f"{'-' * col['pr_count']} "
        f"{'-' * col['non_trivial']} "
        f"{'-' * col['avg_score']} "
        f"{'-' * col['rev_given']} "
        f"{'-' * col['distinct_rev']}"
    )

    print(header)
    print(divider)
    for c in top_candidates_out:
        print(
            f"{c['rank']:<{col['rank']}} "
            f"{c['author']:<{col['author']}} "
            f"{c['total_score']:>{col['total_score']}.3f} "
            f"{c['pr_count']:>{col['pr_count']}} "
            f"{c['non_trivial_pr_count']:>{col['non_trivial']}} "
            f"{c['avg_score']:>{col['avg_score']}.3f} "
            f"{c['reviews_given']:>{col['rev_given']}} "
            f"{c['distinct_authors_reviewed']:>{col['distinct_rev']}}"
        )

    print(divider)
    print(
        f"\nPool stats:  {total_pool_prs} PRs from {len(top)} authors  "
        f"|  avg score {avg_pool_score:.3f}  "
        f"|  {len(all_candidates)} total eligible authors"
    )


if __name__ == "__main__":
    main()
