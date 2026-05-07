#!/usr/bin/env python3
"""
Compute structural impact scores for merged PRs.
Reads:  merged_prs.json
Writes: structural_scores.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

INPUT_FILE = "merged_prs.json"
OUTPUT_FILE = "structural_scores.json"

# ── Bot detection ─────────────────────────────────────────────────────────────

_KNOWN_BOTS: set[str] = {
    "dependabot",
    "dependabot[bot]",
    "github-actions",
    "github-actions[bot]",
    "pre-commit-ci",
    "pre-commit-ci[bot]",
    "renovate",
    "renovate[bot]",
    "snyk-bot",
    "snyk[bot]",
    "semantic-release-bot",
    "allcontributors[bot]",
    "stale[bot]",
    "kodiak[bot]",
    "codecov[bot]",
    "posthog-bot",
    "posthog-contributions-bot",
    "imgbot[bot]",
    "restyled-io[bot]",
    "pyup-bot",
}
_BOT_SUFFIXES = ("[bot]", "-bot", "-ci", "[ci]", "[app]")


def is_bot_author(login: Optional[str]) -> bool:
    if not login:
        return True
    s = login.lower()
    return s in _KNOWN_BOTS or any(s.endswith(sfx) for sfx in _BOT_SUFFIXES)


# ── Trivial PR detection ──────────────────────────────────────────────────────

_TRIVIAL_TITLE_PREFIXES = (
    "chore(deps)",
    "chore(deps-dev)",
    "chore: bump",
    "chore:bump",
    "update dependency",
    "update dependencies",
    "bump ",
    "revert ",
    "revert:",
    "revert!:",
)

_LOCK_FILES: set[str] = {
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "npm-shrinkwrap.json",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-base.txt",
    "requirements-prod.txt",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
    "go.mod",
    "Gemfile.lock",
    "composer.lock",
    ".terraform.lock.hcl",
    "mix.lock",
    "pubspec.lock",
}
_VERSION_FILES: set[str] = {
    "version.py",
    "version.go",
    "version.ts",
    "version.js",
    "VERSION",
    "version.txt",
    "__version__.py",
    "setup.cfg",
    "pyproject.toml",
}
_DOC_EXTENSIONS: set[str] = {".md", ".mdx", ".rst", ".txt"}
_DOC_DIR_PREFIXES = ("docs/", "doc/", "documentation/")


def _is_lock_or_version(path: str) -> bool:
    return Path(path).name in (_LOCK_FILES | _VERSION_FILES)


def _is_doc(path: str) -> bool:
    p = Path(path)
    if p.suffix.lower() in _DOC_EXTENSIONS:
        return True
    name = p.name
    if name == "CHANGELOG" or name.startswith("CHANGELOG."):
        return True
    return any(path.startswith(prefix) for prefix in _DOC_DIR_PREFIXES)


def check_trivial(pr: dict) -> tuple[bool, str]:
    title = (pr.get("title") or "").lower().strip()
    files: list[dict] = pr.get("files") or []
    paths = [f["path"] for f in files]

    for prefix in _TRIVIAL_TITLE_PREFIXES:
        if title.startswith(prefix):
            return True, f"title matches trivial pattern '{prefix}'"

    if not paths:
        return False, ""

    if all(_is_lock_or_version(p) for p in paths):
        return True, "only lock/dependency/version files changed"

    if all(_is_doc(p) for p in paths):
        total_lines = sum(f.get("additions", 0) + f.get("deletions", 0) for f in files)
        if total_lines < 20:
            return True, f"only docs changed ({total_lines} lines total)"

    return False, ""


# ── Review depth score (0.0 – 1.0) ───────────────────────────────────────────

def compute_review_depth(pr: dict) -> float:
    reviews: dict = pr.get("reviews") or {}
    distinct: int = reviews.get("distinct_reviewer_count", 0)
    comments: int = reviews.get("total_review_comments", 0)
    changes_requested: bool = reviews.get("changes_requested", False)
    merge_hours: float = pr.get("merge_time_hours") or 0.0

    # Base: reviewer sub-score (0-5 scale) + comment sub-score (0-20 scale)
    reviewer_sub = min(distinct / 5.0, 1.0)
    comment_sub = min(comments / 20.0, 1.0)
    score = reviewer_sub * 0.5 + comment_sub * 0.5

    if changes_requested:
        score += 0.2
    if merge_hours < 2.0:
        score -= 0.2
    elif 2.0 <= merge_hours <= 24.0:
        score += 0.2

    return round(max(0.0, min(1.0, score)), 4)


# ── Label score (0.0 – 1.0) ──────────────────────────────────────────────────

_LABEL_WEIGHTS: dict[str, float] = {
    "bug": 0.3,
    "performance": 0.3,
    "security": 0.3,
    "incident": 0.3,
    "hotfix": 0.3,
    "critical": 0.3,
    "feature": 0.15,
    "enhancement": 0.15,
    "new feature": 0.15,
    "chore": 0.05,
    "docs": 0.05,
    "documentation": 0.05,
    "test": 0.05,
    "tests": 0.05,
    "ci": 0.05,
    "build": 0.05,
    "style": 0.05,
    "refactor": 0.05,
}


def compute_label_score(pr: dict) -> float:
    labels = [lbl.lower().strip() for lbl in (pr.get("labels") or [])]
    total = 0.0
    for label in labels:
        weight = _LABEL_WEIGHTS.get(label, 0.0)
        if weight == 0.0:
            # substring fallback (e.g. "type: bug", "kind/feature")
            for key, w in _LABEL_WEIGHTS.items():
                if key in label:
                    weight = max(weight, w)
        total += weight
    return round(min(total, 1.0), 4)


# ── Title categorization ──────────────────────────────────────────────────────

_TITLE_WEIGHTS: dict[str, float] = {
    "fix": 0.2,
    "feat": 0.2,
    "perf": 0.2,
    "refactor": 0.2,
    "chore": 0.05,
    "test": 0.05,
    "docs": 0.05,
    "ci": 0.05,
    "style": 0.05,
    "build": 0.05,
    "revert": 0.05,
}

# Conventional-commit prefix: "feat(scope):" or "feat!:" or "feat:"
_PREFIX_RE = re.compile(r"^([a-z]+)(?:\([^)]+\))?!?:", re.IGNORECASE)


def categorize_title(title: str) -> tuple[str, float]:
    title = (title or "").strip()
    m = _PREFIX_RE.match(title)
    if m:
        prefix = m.group(1).lower()
        weight = _TITLE_WEIGHTS.get(prefix, 0.0)
        if weight > 0.0:
            return prefix, weight
        return prefix, 0.0

    # Fallback: bare keyword at start (e.g. "Revert some thing")
    lower = title.lower()
    for cat, weight in _TITLE_WEIGHTS.items():
        if lower.startswith(cat + " ") or lower.startswith(cat + ":"):
            return cat, weight

    return "other", 0.0


# ── Files diversity score (0.0 – 0.5) ────────────────────────────────────────

def compute_diversity(pr: dict) -> float:
    files: list[dict] = pr.get("files") or []
    if not files:
        return 0.0
    top_dirs = {Path(f["path"]).parts[0] for f in files if Path(f["path"]).parts}
    n = len(top_dirs)
    if n >= 5:
        return 0.5
    if n >= 3:
        return 0.3
    return 0.1


# ── Score a single PR ─────────────────────────────────────────────────────────

def score_pr(pr: dict) -> dict:
    author = pr.get("author")
    bot = is_bot_author(author)
    trivial, trivial_reason = check_trivial(pr)

    review_depth = compute_review_depth(pr)
    label_score = compute_label_score(pr)
    title_cat, title_weight = categorize_title(pr.get("title") or "")
    has_linked = bool(pr.get("linked_issues"))
    diversity = compute_diversity(pr)

    combined = (
        review_depth  * 0.4
        + label_score * 0.2
        + title_weight * 0.2
        + diversity   * 0.1
        + (0.1 if has_linked else 0.0)
    )

    if bot or trivial:
        combined = 0.05

    return {
        **pr,
        # Filters
        "is_bot": bot,
        "is_trivial": trivial,
        "trivial_reason": trivial_reason if trivial else None,
        # Component scores
        "review_depth_score": review_depth,
        "label_score": label_score,
        "title_category": title_cat,
        "title_weight": title_weight,
        "has_linked_issue": has_linked,
        "diversity_score": diversity,
        # Final
        "combined_score": round(min(combined, 1.0), 4),
    }


# ── Per-author aggregation ────────────────────────────────────────────────────

def compute_author_stats(prs: list[dict]) -> dict[str, dict]:
    # Author → PRs they authored
    authored: dict[str, list[dict]] = defaultdict(list)
    for pr in prs:
        authored[pr.get("author") or "unknown"].append(pr)

    # Author → distinct reviewers who reviewed *their* PRs
    received_from: dict[str, set[str]] = defaultdict(set)
    # Reviewer → distinct PR authors they reviewed
    given_to: dict[str, set[str]] = defaultdict(set)
    for pr in prs:
        pr_author = pr.get("author") or "unknown"
        reviewers: list[str] = (pr.get("reviews") or {}).get("distinct_reviewers") or []
        received_from[pr_author].update(reviewers)
        for reviewer in reviewers:
            given_to[reviewer].add(pr_author)

    stats: dict[str, dict] = {}
    for author, author_prs in authored.items():
        scores = [p["combined_score"] for p in author_prs]
        stats[author] = {
            "total_pr_count": len(author_prs),
            "total_score": round(sum(scores), 4),
            "avg_score": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "reviewer_count": len(received_from[author]),
            "distinct_reviewers_reviewed_by_this_author": sorted(given_to.get(author, set())),
        }

    return dict(sorted(stats.items(), key=lambda kv: kv[1]["total_score"], reverse=True))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    input_path = Path(INPUT_FILE)
    if not input_path.exists():
        print(f"Error: {INPUT_FILE} not found. Run fetch_merged_prs.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Reading {INPUT_FILE}…", flush=True)
    with open(input_path, encoding="utf-8") as f:
        prs: list[dict] = json.load(f)

    print(f"Scoring {len(prs)} PRs…", flush=True)

    scored: list[dict] = []
    for i, pr in enumerate(prs, 1):
        scored.append(score_pr(pr))
        if i % 200 == 0 or i == len(prs):
            print(f"  {i} / {len(prs)} PRs scored…", end="\r", flush=True)

    print(flush=True)

    # Counts
    bot_count = sum(1 for p in scored if p["is_bot"])
    trivial_count = sum(1 for p in scored if p["is_trivial"] and not p["is_bot"])
    substantive_count = sum(1 for p in scored if not p["is_bot"] and not p["is_trivial"])
    print(f"  {bot_count:>6} bot PRs filtered")
    print(f"  {trivial_count:>6} trivial PRs filtered")
    print(f"  {substantive_count:>6} substantive PRs scored")

    print("\nAggregating per-author stats…", flush=True)
    author_stats = compute_author_stats(scored)

    subst = [p for p in scored if not p["is_bot"] and not p["is_trivial"]]
    avg_score = round(sum(p["combined_score"] for p in subst) / len(subst), 4) if subst else 0.0

    output = {
        "summary": {
            "total_prs": len(scored),
            "bot_prs": bot_count,
            "trivial_prs": trivial_count,
            "substantive_prs": substantive_count,
            "avg_combined_score_substantive": avg_score,
        },
        "author_stats": author_stats,
        "prs": scored,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {OUTPUT_FILE}")

    # Score distribution (substantive PRs only)
    if subst:
        bands = [("0.0–0.2", 0.0, 0.2), ("0.2–0.4", 0.2, 0.4),
                 ("0.4–0.6", 0.4, 0.6), ("0.6–0.8", 0.6, 0.8), ("0.8–1.0", 0.8, 1.01)]
        total = len(subst)
        print("\nScore distribution (substantive PRs):")
        for label, lo, hi in bands:
            n = sum(1 for p in subst if lo <= p["combined_score"] < hi)
            bar = "█" * max(1, round(n * 30 / total)) if n else ""
            print(f"  {label}  {bar:<32} {n:>5}  ({n / total * 100:.1f}%)")

    # Top 10 by score
    top = sorted(subst, key=lambda p: p["combined_score"], reverse=True)[:10]
    if top:
        print("\nTop 10 PRs by combined_score:")
        for p in top:
            print(f"  #{p['number']:>6}  {p['combined_score']:.3f}  {p['title'][:70]}")


if __name__ == "__main__":
    main()
