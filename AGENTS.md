# AGENTS.md

Instructions for coding agents working in this repository.

## Setup

Python 3 with the development dependencies: `pip install -r requirements-dev.txt`. Start the app with `./run.sh`, or `streamlit run app.py --server.port <port>` for a given port.

## Validation

Run `python3 -m pytest -q` from the repository root. It must pass before any change is
handed over. `factory/checks.sh` runs the same command.

## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python3 -m http.server`, then
open http://localhost:8000/dashboard.html.

Each job works in its own git worktree, a full checkout of the repo at
`.worktrees/<job-id>` (gitignored). A tool run from the repo root that doesn't
read `.gitignore` sees those copies too; exclude `.worktrees/` in its config.

The owner merges every pull request herself: the approver always escalates.
The factory files are third-party GPLv3 code; see `factory/THIRD_PARTY.md`.
