# PostHog Engineering Impact

Ranks the top 5 contributors to [PostHog/posthog](https://github.com/PostHog/posthog) over the last 90 days and publishes a single-page dashboard.

## How it works

| Step | Script | Output |
|------|--------|--------|
| 1 | `fetch_merged_prs.py` | Fetch all merged PRs via GitHub GraphQL |
| 2 | `score_prs.py` | Heuristic score per PR (review depth, file diversity, labels) |
| 3 | `rank_engineers.py` | Select top-20 candidates by structural score |
| 4 | `llm_score_prs.py` | LLM assigns high/medium/low impact tier to each candidate PR |
| 5 | `final_ranking.py` | Re-rank combining tier score (50%), collaboration (30%), structural (20%) |
| 6 | `generate_narratives.py` | One-sentence summary per engineer via LLM |
| 7 | `generate_dashboard.py` | Build `index.html` |

Scores are normalized to 0–100 against the top engineer so the number is immediately comparable across runs.

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com) running locally with `llama3.1:8b` pulled
- A GitHub personal access token (read-only, public repos is enough)

```bash
pip install requests
ollama pull llama3.1:8b
```

## Setup

Copy `.env.example` to `.env` and fill in your token:

```
GITHUB_TOKEN=your_token_here
```

## Running

```bash
# Full pipeline
python run_pipeline.py

# Skip already-completed steps
python run_pipeline.py --skip-to 4

# Re-run a single step
python run_pipeline.py --only 7

# Force re-run everything
python run_pipeline.py --force
```

Step 4 (LLM scoring) is long-running and fully resumable — safe to Ctrl-C and re-run.

## Output

- `outputs/` — intermediate JSON files from each step
- `index.html` — dashboard, ready to open in a browser or deploy via GitHub Pages
