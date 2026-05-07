#!/usr/bin/env python3
"""
Generate one-sentence narrative summaries for the top-5 engineers using Ollama.
Reads:  top_5_engineers.json
Writes: top_5_narratives.json
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL      = "llama3.1:8b"

TOP5_FILE      = "outputs/top_5_engineers.json"
OUTPUT_FILE    = "outputs/top_5_narratives.json"

# ── Prompt ────────────────────────────────────────────────────────────────────

def build_prompt(eng: dict) -> str:
    tiers   = eng.get("impact_tiers") or {}
    cats    = eng.get("work_categories") or {}
    top_cat = ", ".join(
        f"{k.replace('_', ' ')} {round(v * 100)}%"
        for k, v in list(cats.items())[:4]
    )
    prs_text = "\n".join(
        f'  [{p["impact_tier"].upper()}] {p["title"]}: {p["rationale"]}'
        for p in (eng.get("highlight_prs") or [])[:3]
    ) or "  (none)"

    return (
        "You are writing a one-sentence professional summary for a top contributor to PostHog, "
        "an open-source product analytics platform.\n\n"
        f"Engineer profile:\n"
        f"- {eng['pr_count']} PRs merged in the last 90 days\n"
        f"- Work mix: {top_cat or 'varied'}\n"
        f"- Impact: {tiers.get('high',0)} high, {tiers.get('medium',0)} medium, {tiers.get('low',0)} low\n"
        f"- Reviews given to peers: {eng.get('reviews_given', 0)}\n"
        f"- Notable PRs:\n{prs_text}\n\n"
        "Write ONE sentence (15–25 words) capturing this engineer's contribution style and primary "
        "impact area. Use a direct, professional tone. Do not mention their name or GitHub handle. "
        "Output only the sentence — no quotes, no preamble."
    )

# ── API call ──────────────────────────────────────────────────────────────────

def call_ollama(prompt: str, max_retries: int = 4) -> str:
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.4},
                },
                timeout=120,
            )
            if resp.status_code >= 500:
                wait = 5 * (2 ** attempt)
                print(f"  HTTP {resp.status_code} — retry in {wait}s…", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip().strip('"')
        except requests.RequestException as exc:
            if attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
            else:
                return "Contributed high-quality PRs across core platform areas."
    return ""

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if not Path(TOP5_FILE).exists():
        print(f"Error: {TOP5_FILE} not found. Run final_ranking.py first.", file=sys.stderr)
        sys.exit(1)

    with open(TOP5_FILE, encoding="utf-8") as f:
        top5 = json.load(f)

    engineers = top5.get("top_5") or []
    print(f"Generating narratives for {len(engineers)} engineers…", flush=True)

    narratives: dict[str, str] = {}
    for eng in engineers:
        author = eng["author"]
        print(f"  {author}…", end=" ", flush=True)
        narrative = call_ollama(build_prompt(eng))
        narratives[author] = narrative
        print(narrative[:60] + ("…" if len(narrative) > 60 else ""), flush=True)

    output = {"narratives": narratives}
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
