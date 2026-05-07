#!/usr/bin/env python3
"""
Score PRs from top engineers using local Ollama.
Reads:  top_candidates.json, structural_scores.json
Writes: llm_scores.json  (real-time, crash-safe, fully resumable)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "llama3.1:8b"

TOP_CANDIDATES_FILE = "outputs/top_candidates.json"
STRUCTURAL_FILE = "outputs/structural_scores.json"
OUTPUT_FILE = "outputs/llm_scores.json"

MAX_BODY_CHARS = 1500
MAX_FILES_SHOWN = 20
MAX_RETRIES = 4
PROGRESS_EVERY = 50

HEADERS = {
    "Content-Type": "application/json",
}

# ── Ollama API call ───────────────────────────────────────────────────────────
def call_ollama(prompt: str) -> Optional[dict]:
    """Call Ollama and return parsed JSON dict, or None on unrecoverable failure."""

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                OLLAMA_URL,
                headers=HEADERS,
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                    },
                },
                timeout=120,
            )

            # Transient server errors
            if resp.status_code >= 500:
                wait = 5 * (2 ** attempt)
                print(f"\n  HTTP {resp.status_code} — retry in {wait}s…", flush=True)
                time.sleep(wait)
                continue

            resp.raise_for_status()

            data = resp.json()

            raw = (
                data.get("message", {})
                .get("content", "")
                .strip()
            )

            if not raw:
                print(
                    f"\n  Empty response (attempt {attempt + 1}/{MAX_RETRIES})",
                    flush=True,
                )
                continue

            # Strip markdown fences if model adds them
            if raw.startswith("```"):
                parts = raw.split("```")

                if len(parts) >= 2:
                    raw = parts[1]

                if raw.startswith("json"):
                    raw = raw[4:]

                raw = raw.strip()

            # Extract JSON object if extra text appears
            start = raw.find("{")
            end = raw.rfind("}")

            if start != -1 and end != -1:
                raw = raw[start:end + 1]

            return json.loads(raw)

        except json.JSONDecodeError as exc:
            print(
                f"\n  JSON parse error (attempt {attempt + 1}/{MAX_RETRIES}): {exc}",
                flush=True,
            )

            if attempt == MAX_RETRIES - 1:
                return None

        except requests.RequestException as exc:
            wait = 5 * (2 ** attempt)

            print(
                f"\n  Request error ({exc}) — retry in {wait}s…",
                flush=True,
            )

            time.sleep(wait)

    return None
# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(pr: dict) -> str:
    title = pr.get("title") or "(no title)"
    author = pr.get("author") or "unknown"

    body = (pr.get("body") or "").strip()
    body_excerpt = body[:MAX_BODY_CHARS] + ("…" if len(body) > MAX_BODY_CHARS else "")

    labels = ", ".join(pr.get("labels") or []) or "none"
    reviews = pr.get("reviews") or {}
    comments = reviews.get("total_review_comments", 0)
    reviewers = reviews.get("distinct_reviewer_count", 0)

    files: list[dict] = pr.get("files") or []
    shown = files[:MAX_FILES_SHOWN]

    files_lines = "\n".join(
        f"  {f['path']} (+{f['additions']}/-{f['deletions']})"
        for f in shown
    )

    if len(files) > MAX_FILES_SHOWN:
        files_lines += f"\n  … and {len(files) - MAX_FILES_SHOWN} more files"

    linked = pr.get("linked_issues") or []
    linked_str = ", ".join(f"#{i['number']}" for i in linked[:5]) or "none"

    merge_hours = pr.get("merge_time_hours") or 0.0

    return (
        "You are evaluating the impact of a GitHub pull request in an open-source "
        "engineering project.\n\n"
        "PR Details:\n"
        f"- Title: {title}\n"
        f"- Author: {author}\n"
        f"- Body: {body_excerpt or '(no body)'}\n"
        f"- Labels: {labels}\n"
        f"- Files Changed:\n{files_lines or '  (none listed)'}\n"
        f"- Review Comments: {comments}\n"
        f"- Distinct Reviewers: {reviewers}\n"
        f"- Linked Issues: {linked_str}\n"
        f"- Merge Time: {merge_hours:.1f} hours\n\n"
        "Categorize this PR and assign an impact tier with reasoning.\n\n"
        "Output ONLY valid JSON (no preamble, no markdown):\n"
        "{\n"
        '  "category": "bug_fix|feature|performance|security|refactor|infrastructure|cleanup|documentation",\n'
        '  "impact_tier": "high|medium|low",\n'
        '  "rationale": "One sentence explaining the impact tier.",\n'
        '  "signals": ["key signal 1", "key signal 2", "key signal 3"]\n'
        "}"
    )

# ── Output helpers ────────────────────────────────────────────────────────────

def load_existing() -> tuple[list[dict], set[int]]:
    """Return (existing_entries, set_of_already_scored_pr_numbers)."""
    p = Path(OUTPUT_FILE)

    if not p.exists():
        return [], set()

    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        entries: list[dict] = data.get("prs") or []
        ids = {int(e["pr_number"]) for e in entries if "pr_number" in e}

        print(f"  Resuming: {len(ids)} PRs already scored.", flush=True)

        return entries, ids

    except (json.JSONDecodeError, KeyError, ValueError):
        print("  Warning: output file unreadable — starting fresh.", flush=True)
        return [], set()


def flush_output(scored: list[dict]) -> None:
    """Rewrite llm_scores.json atomically with updated metadata."""
    by_category: dict[str, int] = {}
    by_tier: dict[str, int] = {}

    for e in scored:
        cat = e.get("category", "unknown")
        tier = e.get("impact_tier", "unknown")

        by_category[cat] = by_category.get(cat, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1

    # Write to a temp file first, then rename — avoids corrupt output on crash
    tmp = OUTPUT_FILE + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(
            {
                "prs": scored,
                "metadata": {
                    "total_scored": len(scored),
                    "by_category": dict(sorted(by_category.items())),
                    "by_tier": dict(sorted(by_tier.items())),
                },
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    Path(tmp).replace(OUTPUT_FILE)

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    for fname in (TOP_CANDIDATES_FILE, STRUCTURAL_FILE):
        if not Path(fname).exists():
            print(f"Error: {fname} not found.", file=sys.stderr)
            sys.exit(1)

    print(f"Reading {TOP_CANDIDATES_FILE}…", flush=True)

    with open(TOP_CANDIDATES_FILE, encoding="utf-8") as f:
        top_data = json.load(f)

    print(f"Reading {STRUCTURAL_FILE}…", flush=True)

    with open(STRUCTURAL_FILE, encoding="utf-8") as f:
        structural = json.load(f)

    # PR number → full PR record
    pr_map: dict[int, dict] = {
        pr["number"]: pr for pr in structural["prs"]
    }

    # Ordered list of (pr_number, author) for every PR owned by a top candidate
    work: list[tuple[int, str]] = []

    for candidate in top_data["top_candidates"]:
        author = candidate["author"]

        for pr_num in candidate["pr_ids"]:
            work.append((int(pr_num), author))

    total = len(work)

    print(
        f"  {len(top_data['top_candidates'])} top engineers · {total} PRs total.\n",
        flush=True,
    )

    scored, already_done = load_existing()

    pending = [(n, a) for n, a in work if n not in already_done]

    print(
        f"  {len(already_done)} cached · {len(pending)} to score.\n",
        flush=True,
    )

    if not pending:
        print("Nothing to do — all PRs already scored.", flush=True)
        _print_summary(scored)
        return

    errors = 0

    for i, (pr_num, author) in enumerate(pending, 1):
        pr = pr_map.get(pr_num)

        if not pr:
            print(
                f"\n  Warning: PR #{pr_num} missing from structural scores — skipping.",
                flush=True,
            )
            continue

        result = call_ollama(build_prompt(pr))

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if result is None:
            errors += 1

            entry: dict = {
                "pr_id": pr_num,
                "pr_number": pr_num,
                "author": author,
                "title": pr.get("title"),
                "category": "unknown",
                "impact_tier": "unknown",
                "rationale": "Scoring failed after retries.",
                "signals": [],
                "llm_model": MODEL,
                "scored_at": now_iso,
                "error": True,
            }

        else:
            entry = {
                "pr_id": pr_num,
                "pr_number": pr_num,
                "author": author,
                "title": pr.get("title"),
                "category": result.get("category", "unknown"),
                "impact_tier": result.get("impact_tier", "unknown"),
                "rationale": result.get("rationale", ""),
                "signals": result.get("signals") or [],
                "llm_model": MODEL,
                "scored_at": now_iso,
            }

        scored.append(entry)

        # Persist after every PR — crash-safe via atomic rename
        flush_output(scored)

        total_done = len(already_done) + i

        if total_done % PROGRESS_EVERY == 0 or i == len(pending):
            pct = total_done / total * 100

            print(
                f"  Scored {total_done} / {total} PRs  ({pct:.0f}%)…",
                flush=True,
            )

    status = f"{errors} errors" if errors else "no errors"

    print(f"\nDone ({status}).", flush=True)

    _print_summary(scored)


def _print_summary(scored: list[dict]) -> None:
    if not scored:
        return

    by_category: dict[str, int] = {}
    by_tier: dict[str, int] = {}

    for e in scored:
        cat = e.get("category", "unknown")
        tier = e.get("impact_tier", "unknown")

        by_category[cat] = by_category.get(cat, 0) + 1
        by_tier[tier] = by_tier.get(tier, 0) + 1

    total = len(scored)

    print(f"\nResults → {OUTPUT_FILE}   ({total} total)\n")

    print("  Impact tier breakdown:")

    for tier in ("high", "medium", "low", "unknown"):
        n = by_tier.get(tier, 0)

        if n == 0:
            continue

        bar = "█" * max(1, round(n * 30 / total))

        print(
            f"    {tier:<8}  {bar:<32}  {n:>5}  ({n / total * 100:.1f}%)"
        )

    print("\n  Category breakdown:")

    for cat, n in sorted(by_category.items(), key=lambda kv: -kv[1]):
        bar = "█" * max(1, round(n * 25 / total))

        print(f"    {cat:<18}  {bar:<27}  {n:>5}")


if __name__ == "__main__":
    main()