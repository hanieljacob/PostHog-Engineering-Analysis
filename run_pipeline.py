#!/usr/bin/env python3
"""
PostHog Engineering Impact — full pipeline orchestrator.

Usage:
  python run_pipeline.py                  # run all steps, skip any with existing output
  python run_pipeline.py --force          # re-run every step from scratch
  python run_pipeline.py --skip-to 5     # jump to step 5 (prior outputs must exist)
  python run_pipeline.py --only 4        # run a single step
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Colour helpers ────────────────────────────────────────────────────────────

_TTY = sys.stdout.isatty()

class C:
    BOLD   = "\033[1m"  if _TTY else ""
    DIM    = "\033[2m"  if _TTY else ""
    GREEN  = "\033[92m" if _TTY else ""
    YELLOW = "\033[93m" if _TTY else ""
    RED    = "\033[91m" if _TTY else ""
    CYAN   = "\033[96m" if _TTY else ""
    RESET  = "\033[0m"  if _TTY else ""

def ok(msg):   print(f"  {C.GREEN}✓{C.RESET}  {msg}")
def skip(msg): print(f"  {C.YELLOW}–{C.RESET}  {C.DIM}{msg}{C.RESET}")
def err(msg):  print(f"  {C.RED}✗{C.RESET}  {msg}", file=sys.stderr)
def info(msg): print(f"     {C.DIM}{msg}{C.RESET}")
def banner(msg):
    line = "─" * 64
    print(f"\n{C.BOLD}{line}\n  {msg}\n{line}{C.RESET}")

def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s:02d}s"

# ── Env loading ───────────────────────────────────────────────────────────────

def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

# ── Step definition ───────────────────────────────────────────────────────────

@dataclass
class Step:
    num:         int
    script:      str
    output:      str
    description: str
    long_running: bool = False

STEPS: list[Step] = [
    Step(1, "scripts/fetch_merged_prs.py",    "outputs/merged_prs.json",        "Fetch merged PRs from GitHub (GraphQL)"),
    Step(2, "scripts/score_prs.py",           "outputs/structural_scores.json",  "Compute structural impact scores"),
    Step(3, "scripts/rank_engineers.py",      "outputs/top_candidates.json",     "Select top-20 candidate engineers"),
    Step(4, "scripts/llm_score_prs.py",       "outputs/llm_scores.json",         "LLM-score all candidate PRs via Ollama", long_running=True),
    Step(5, "scripts/final_ranking.py",       "outputs/top_5_engineers.json",    "Rerank and select top-5 engineers"),
    Step(6, "scripts/generate_narratives.py", "outputs/top_5_narratives.json",   "Generate engineer narrative summaries"),
    Step(7, "scripts/generate_dashboard.py",  "index.html",                      "Build the HTML dashboard"),
]

# ── Subprocess runner ─────────────────────────────────────────────────────────

def run_step(step: Step, force: bool = False) -> bool:
    """Run a pipeline step. Returns True on success."""
    output = Path(step.output)

    if output.exists() and not force:
        size = output.stat().st_size
        skip(f"Step {step.num} — {step.output} already exists ({size:,} bytes); skipping")
        return True

    label = f"Step {step.num}/{len(STEPS)}: {step.description}"
    print(f"\n{C.BOLD}{'─' * 64}{C.RESET}")
    print(f"{C.BOLD}  {label}{C.RESET}")
    if step.long_running:
        print(f"  {C.YELLOW}⚠  Long-running step. Output is written in real-time.")
        print(f"     Safe to Ctrl-C and resume later — cached results are preserved.{C.RESET}")
    print()

    t0 = time.time()

    proc = subprocess.Popen(
        [sys.executable, "-u", step.script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )

    # Stream output line-by-line as it arrives
    assert proc.stdout is not None
    try:
        for raw in iter(proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").rstrip()
            print(f"  {line}")
    except KeyboardInterrupt:
        proc.terminate()
        elapsed = time.time() - t0
        print(f"\n  {C.YELLOW}Interrupted after {fmt_time(elapsed)}.{C.RESET}")
        if step.long_running and output.exists():
            print(f"  Partial output saved to {step.output}. Re-run to resume.")
        return False

    proc.wait()
    elapsed = time.time() - t0

    if proc.returncode != 0:
        err(f"Step {step.num} failed with exit code {proc.returncode} ({fmt_time(elapsed)})")
        return False

    if not output.exists():
        err(f"Step {step.num} exited 0 but {step.output} was not created")
        return False

    size = output.stat().st_size
    ok(f"{step.output} ({size:,} bytes) — {fmt_time(elapsed)}")
    return True

# ── Credential check ──────────────────────────────────────────────────────────

def check_credentials() -> bool:
    missing = []
    for key in ("GITHUB_TOKEN",):
        val = os.environ.get(key, "")
        if not val or val.startswith("your_"):
            missing.append(key)
    if missing:
        err(f"Missing or placeholder credentials: {', '.join(missing)}")
        print(f"\n  Set them in {C.BOLD}.env{C.RESET} or export them before running:")
        for k in missing:
            print(f"    export {k}=<your_key>")
        return False
    return True

# ── Final summary ─────────────────────────────────────────────────────────────

def print_summary(total_wall: float) -> None:
    banner("Pipeline complete")

    # Total PRs
    try:
        with open("outputs/merged_prs.json", encoding="utf-8") as f:
            prs = json.load(f)
        print(f"  Total PRs processed : {C.BOLD}{len(prs):,}{C.RESET}")
    except Exception:
        pass

    # Structural stats
    try:
        with open("outputs/structural_scores.json", encoding="utf-8") as f:
            ss = json.load(f)
        summary = ss.get("summary", {})
        print(f"  Substantive PRs      : {C.BOLD}{summary.get('substantive_prs', '–'):,}{C.RESET}")
        print(f"  Bot/trivial filtered : {(summary.get('bot_prs',0) + summary.get('trivial_prs',0)):,}")
    except Exception:
        pass

    # LLM scored
    try:
        with open("outputs/llm_scores.json", encoding="utf-8") as f:
            ls = json.load(f)
        meta = ls.get("metadata", {})
        print(f"  LLM-scored PRs       : {C.BOLD}{meta.get('total_scored', '–'):,}{C.RESET}")
        tiers = meta.get("by_tier", {})
        tier_str = "  ·  ".join(
            f"{t}: {n}" for t, n in sorted(tiers.items()) if n
        )
        if tier_str:
            print(f"  Tier breakdown       : {tier_str}")
    except Exception:
        pass

    # Top 5
    try:
        with open("outputs/top_5_engineers.json", encoding="utf-8") as f:
            t5 = json.load(f)
        print(f"\n  {C.BOLD}Top 5 engineers:{C.RESET}")
        for eng in t5.get("top_5", []):
            tiers = eng.get("impact_tiers", {})
            print(
                f"    {C.CYAN}#{eng['rank']}{C.RESET}  "
                f"{C.BOLD}{eng['author']:<22}{C.RESET}"
                f"  score {eng['normalized_score']:.1f}/100"
                f"  |  {tiers.get('high',0)}H {tiers.get('medium',0)}M {tiers.get('low',0)}L"
                f"  ({eng['pr_count']} PRs)"
            )
    except Exception:
        pass

    # Dashboard path
    dash = Path("index.html").resolve()
    if dash.exists():
        print(f"\n  {C.BOLD}Dashboard{C.RESET} → {C.GREEN}{dash}{C.RESET}")
        print(f"  Open with:  open {dash}")

    print(f"\n  Total wall time: {C.BOLD}{fmt_time(total_wall)}{C.RESET}")
    print(f"{'─' * 64}\n")

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PostHog Engineering Impact Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(f"  Step {s.num}: {s.description}" for s in STEPS),
    )
    parser.add_argument(
        "--skip-to", type=int, default=1, metavar="N",
        help="Start from step N (1–7); earlier outputs must exist",
    )
    parser.add_argument(
        "--only", type=int, metavar="N",
        help="Run only step N",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-run steps even when their output already exists",
    )
    args = parser.parse_args()

    # Load .env before checking credentials
    load_env()

    # Header
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    banner(f"PostHog Engineering Impact Pipeline  ·  {now}")
    print(f"  Working directory: {Path('.').resolve()}\n")

    # Verify scripts exist
    missing_scripts = [s.script for s in STEPS if not Path(s.script).exists()]
    if missing_scripts:
        for ms in missing_scripts:
            err(f"Script not found: {ms}")
        sys.exit(1)

    # Credential check (always required even with --skip-to)
    print(f"{C.BOLD}  Checking credentials…{C.RESET}")
    if not check_credentials():
        sys.exit(1)
    ok("GITHUB_TOKEN is set")

    # Determine which steps to run
    if args.only:
        steps_to_run = [s for s in STEPS if s.num == args.only]
        if not steps_to_run:
            err(f"No step with number {args.only}")
            sys.exit(1)
    else:
        steps_to_run = [s for s in STEPS if s.num >= args.skip_to]

    skipped_steps = [s for s in STEPS if s.num < args.skip_to]
    if skipped_steps:
        # Verify that skipped steps' outputs actually exist
        missing_outputs = [s for s in skipped_steps if not Path(s.output).exists()]
        if missing_outputs:
            for ms in missing_outputs:
                err(f"--skip-to {args.skip_to} requires {ms.output} (step {ms.num}) to exist")
            sys.exit(1)

    print(f"\n  {len(steps_to_run)} step(s) to run: "
          + ", ".join(str(s.num) for s in steps_to_run))
    if args.force:
        print(f"  {C.YELLOW}--force: existing outputs will be overwritten{C.RESET}")

    # Run pipeline
    t_start = time.time()
    step_times: dict[int, float] = {}

    for step in steps_to_run:
        t0 = time.time()
        success = run_step(step, force=args.force)
        step_times[step.num] = time.time() - t0

        if not success:
            print(f"\n{C.RED}{C.BOLD}Pipeline stopped at step {step.num}.{C.RESET}")
            if step.long_running and Path(step.output).exists():
                print(f"  Partial output exists. Re-run to resume from step {step.num}:")
                print(f"    python run_pipeline.py --skip-to {step.num}")
            else:
                print(f"  Re-run from this step:")
                print(f"    python run_pipeline.py --skip-to {step.num}")
            sys.exit(1)

    # Step timing table
    if len(step_times) > 1:
        print(f"\n{C.BOLD}  Step timings:{C.RESET}")
        for s in steps_to_run:
            if s.num in step_times:
                info(f"Step {s.num}: {fmt_time(step_times[s.num]):<10} {s.description}")

    print_summary(time.time() - t_start)


if __name__ == "__main__":
    main()
