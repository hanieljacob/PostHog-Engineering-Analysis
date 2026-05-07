#!/usr/bin/env python3
"""
Fetch merged PRs from PostHog/posthog (last 90 days) via GitHub GraphQL API.
Output: merged_prs.json

Usage:
    python fetch_merged_prs.py   # reads GITHUB_TOKEN from .env
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from pathlib import Path

import requests

# ── Configuration ─────────────────────────────────────────────────────────────

def _load_env(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no-op if missing)."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

_load_env()

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN or GITHUB_TOKEN == "your_github_token_here":
    print("Error: set GITHUB_TOKEN in .env or as an environment variable.", file=sys.stderr)
    sys.exit(1)

GRAPHQL_URL = "https://api.github.com/graphql"
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json",
}
OUTPUT_FILE = "merged_prs.json"
SINCE_DATE = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

# ── GraphQL queries ───────────────────────────────────────────────────────────

# Date is embedded at module load time; only $cursor is a runtime variable.
SEARCH_QUERY = f"""
query FetchMergedPRs($cursor: String) {{
  rateLimit {{
    remaining
    resetAt
  }}
  search(
    query: "repo:PostHog/posthog is:pr is:merged merged:>={SINCE_DATE}"
    type: ISSUE
    first: 20
    after: $cursor
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    issueCount
    nodes {{
      ... on PullRequest {{
        id
        number
        title
        body
        createdAt
        mergedAt
        author {{
          login
        }}
        labels(first: 20) {{
          nodes {{
            name
          }}
        }}
        reviews(first: 100) {{
          totalCount
          nodes {{
            author {{
              login
            }}
            state
          }}
        }}
        reviewThreads(first: 1) {{
          totalCount
        }}
        files(first: 100) {{
          totalCount
          pageInfo {{
            hasNextPage
            endCursor
          }}
          nodes {{
            path
            additions
            deletions
          }}
        }}
        closingIssuesReferences(first: 20) {{
          nodes {{
            number
            title
          }}
        }}
      }}
    }}
  }}
}}
"""

FILES_QUERY = """
query FetchPRFiles($number: Int!, $cursor: String) {
  repository(owner: "PostHog", name: "posthog") {
    pullRequest(number: $number) {
      files(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { path additions deletions }
      }
    }
  }
}
"""

REVIEWS_QUERY = """
query FetchPRReviews($number: Int!, $cursor: String) {
  repository(owner: "PostHog", name: "posthog") {
    pullRequest(number: $number) {
      reviews(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          author { login }
          state
        }
      }
    }
  }
}
"""

# ── HTTP / retry helper ───────────────────────────────────────────────────────

def run_query(query: str, variables: Optional[dict] = None, max_retries: int = 6) -> dict:
    """Execute a GraphQL query with exponential-backoff retry on rate limits and errors."""
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                GRAPHQL_URL,
                json={"query": query, "variables": variables or {}},
                headers=HEADERS,
                timeout=60,
            )

            # HTTP-level rate limit
            if resp.status_code in (429, 403):
                wait = int(resp.headers.get("Retry-After", 60))
                print(f"\n  HTTP {resp.status_code} — sleeping {wait}s…", flush=True)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            payload = resp.json()

            # GraphQL-level errors
            if "errors" in payload:
                rate_limited = False
                for err in payload["errors"]:
                    if err.get("type") == "RATE_LIMITED":
                        wait = 60 * (2 ** attempt)
                        print(f"\n  GraphQL rate-limited — sleeping {wait}s…", flush=True)
                        time.sleep(wait)
                        rate_limited = True
                        break
                if rate_limited:
                    continue
                # Partial data with non-rate-limit errors: surface and raise
                raise RuntimeError(f"GraphQL errors: {payload['errors']}")

            data: dict = payload.get("data") or {}

            # Proactive back-off when the remaining point budget is almost gone
            rl = data.get("rateLimit")
            if rl and rl["remaining"] < 50:
                reset = datetime.fromisoformat(rl["resetAt"].replace("Z", "+00:00"))
                wait = max((reset - datetime.now(timezone.utc)).total_seconds() + 2, 0)
                print(
                    f"\n  Rate limit low ({rl['remaining']} remaining) — "
                    f"sleeping {wait:.0f}s…",
                    flush=True,
                )
                time.sleep(wait)

            return data

        except requests.RequestException as exc:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"\n  Request error ({exc}) — retry in {wait}s…", flush=True)
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"All {max_retries} retries exhausted")


# ── Pagination helpers ────────────────────────────────────────────────────────

def paginate_files(pr_number: int, page_info: dict) -> list:
    """Fetch file pages beyond the first 100, starting from page_info cursor."""
    extra: list = []
    while page_info["hasNextPage"]:
        data = run_query(FILES_QUERY, {"number": pr_number, "cursor": page_info["endCursor"]})
        page = data["repository"]["pullRequest"]["files"]
        extra.extend(page["nodes"])
        page_info = page["pageInfo"]
    return extra


def fetch_all_reviews(pr_number: int) -> list:
    """Fetch all review nodes for a PR (used only when totalCount > 100)."""
    reviews: list = []
    cursor = None
    while True:
        data = run_query(REVIEWS_QUERY, {"number": pr_number, "cursor": cursor})
        page = data["repository"]["pullRequest"]["reviews"]
        reviews.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return reviews


# ── Text-parsing helpers ──────────────────────────────────────────────────────

_CLOSES_RE = re.compile(
    r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)",
    re.IGNORECASE,
)
_REVERTS_RE = re.compile(r"revert[sd]?\s+#(\d+)", re.IGNORECASE)


def parse_closing_issues(body: str) -> list:
    if not body:
        return []
    return sorted({int(m) for m in _CLOSES_RE.findall(body)})


def parse_reverted_pr_numbers(title: str, body: str) -> list:
    """
    Extract PR numbers that this revert PR is undoing.
    Covers:
      - "#1234" anywhere in the title  (GitHub auto-format includes the number)
      - "Reverts #1234" in the body
    """
    numbers: set = set()
    for m in re.findall(r"#(\d+)", title or ""):
        numbers.add(int(m))
    for m in _REVERTS_RE.findall(body or ""):
        numbers.add(int(m))
    return sorted(numbers)


# ── PR node → output dict ─────────────────────────────────────────────────────

def process_pr(node: dict) -> dict:
    created_dt = datetime.fromisoformat(node["createdAt"].replace("Z", "+00:00"))
    merged_dt = datetime.fromisoformat(node["mergedAt"].replace("Z", "+00:00"))
    merge_hours = (merged_dt - created_dt).total_seconds() / 3600

    # Reviews (first 100 from search query)
    review_nodes: list = node["reviews"]["nodes"]
    review_total: int = node["reviews"]["totalCount"]
    distinct_reviewers = {
        r["author"]["login"] for r in review_nodes if r.get("author")
    }
    changes_requested = any(r["state"] == "CHANGES_REQUESTED" for r in review_nodes)

    # Files (first 100; pagination handled later)
    file_nodes: list = node["files"]["nodes"]
    files_page_info: dict = node["files"]["pageInfo"]

    # Linked issues: merge GraphQL closing refs + body-parsed refs
    closing_refs = [
        {"number": i["number"], "title": i["title"]}
        for i in node["closingIssuesReferences"]["nodes"]
    ]
    seen_issue_numbers = {i["number"] for i in closing_refs}
    for num in parse_closing_issues(node.get("body") or ""):
        if num not in seen_issue_numbers:
            closing_refs.append({"number": num, "title": None})
            seen_issue_numbers.add(num)

    title = node.get("title") or ""
    body = node.get("body") or ""

    return {
        "id": node["id"],
        "number": node["number"],
        "title": title,
        "body": body,
        "author": node["author"]["login"] if node.get("author") else None,
        "labels": [lbl["name"] for lbl in node["labels"]["nodes"]],
        "reviews": {
            "total_count": review_total,
            "distinct_reviewer_count": len(distinct_reviewers),
            "distinct_reviewers": sorted(distinct_reviewers),
            "total_review_comments": node["reviewThreads"]["totalCount"],
            "changes_requested": changes_requested,
        },
        "files": [
            {"path": f["path"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in file_nodes
        ],
        "files_changed_count": node["files"]["totalCount"],
        "linked_issues": closing_refs,
        "created_at": node["createdAt"],
        "merged_at": node["mergedAt"],
        "merge_time_hours": round(merge_hours, 2),
        "reverted": False,
        # Private fields removed before final output
        "_files_page_info": files_page_info,
        "_reviews_total_count": review_total,
        "_is_revert": "revert" in title.lower(),
        "_reverts_prs": parse_reverted_pr_numbers(title, body),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Fetching merged PRs from PostHog/posthog since {SINCE_DATE}…", flush=True)

    prs: list[dict] = []
    cursor: Optional[str] = None
    total_expected: Optional[int] = None

    # ── Phase 1: paginate the PR search ──────────────────────────────────────
    while True:
        data = run_query(SEARCH_QUERY, {"cursor": cursor})
        search = data["search"]

        if total_expected is None:
            total_expected = search["issueCount"]
            print(f"  Total PRs reported by API: {total_expected}", flush=True)

        for node in search["nodes"]:
            # The search API can return Issue nodes; skip them
            if "number" not in node or "mergedAt" not in node:
                continue
            prs.append(process_pr(node))

        print(f"  Fetched {len(prs)} / {total_expected} PRs…", end="\r", flush=True)

        page_info = search["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]

    print(f"\n  Done fetching: {len(prs)} PRs.", flush=True)

    # ── Phase 2: paginate files for large PRs (>100 changed files) ───────────
    files_paginated = 0
    for pr in prs:
        page_info = pr.pop("_files_page_info")
        if page_info["hasNextPage"]:
            extra = paginate_files(pr["number"], page_info)
            pr["files"].extend(extra)
            files_paginated += 1

    if files_paginated:
        print(f"  Paginated files for {files_paginated} large PRs.", flush=True)

    # ── Phase 3: re-fetch reviews for PRs with >100 review submissions ───────
    reviews_refetched = 0
    for pr in prs:
        total = pr.pop("_reviews_total_count")
        if total > 100:
            all_reviews = fetch_all_reviews(pr["number"])
            distinct = {r["author"]["login"] for r in all_reviews if r.get("author")}
            cr = any(r["state"] == "CHANGES_REQUESTED" for r in all_reviews)
            pr["reviews"]["distinct_reviewers"] = sorted(distinct)
            pr["reviews"]["distinct_reviewer_count"] = len(distinct)
            pr["reviews"]["changes_requested"] = cr
            reviews_refetched += 1

    if reviews_refetched:
        print(f"  Re-fetched reviews for {reviews_refetched} PRs with >100 reviews.", flush=True)

    # ── Phase 4: detect reverts (within 7 days of the original merge) ────────
    pr_by_number = {pr["number"]: pr for pr in prs}
    merged_times = {
        pr["number"]: datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
        for pr in prs
    }
    revert_count = 0

    for pr in prs:
        is_revert = pr.pop("_is_revert")
        reverts_prs = pr.pop("_reverts_prs")
        if is_revert:
            revert_merged = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
            for orig_num in reverts_prs:
                if orig_num in pr_by_number:
                    orig_merged = merged_times[orig_num]
                    delta_hours = (revert_merged - orig_merged).total_seconds() / 3600
                    if 0 <= delta_hours <= 7 * 24:
                        pr_by_number[orig_num]["reverted"] = True
                        revert_count += 1

    print(f"  Detected {revert_count} reverted PRs.", flush=True)

    # ── Write output ──────────────────────────────────────────────────────────
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(prs, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(prs)} PRs to {OUTPUT_FILE}", flush=True)

    # Summary
    reverted = sum(1 for pr in prs if pr["reverted"])
    avg_hours = sum(pr["merge_time_hours"] for pr in prs) / len(prs) if prs else 0
    total_files = sum(pr["files_changed_count"] for pr in prs)
    print(f"\nSummary:")
    print(f"  PRs fetched:     {len(prs)}")
    print(f"  Reverted PRs:    {reverted}")
    print(f"  Avg merge time:  {avg_hours:.1f}h")
    print(f"  Total files:     {total_files}")


if __name__ == "__main__":
    main()
