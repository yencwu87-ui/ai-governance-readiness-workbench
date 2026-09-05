# Step 5–6 patch

Unzip at the git root (`ai-governance-readiness-workbench/`, the folder that contains `repo/`):

    cd ~/Downloads/Projects/ai-governance-readiness-workbench
    cp -R ~/Downloads/step56/. .
    rm -rf repo/.github            # old workflow in the wrong place

What it contains:
- `.github/workflows/audit.yml`    at git root, runs inside repo/, writes bundles to the `evidence` branch
- `repo/caa/runner.py`             exception-aware CI gate (open, unexpired exceptions.csv rows don't block)
- `repo/caa/checks.py`             clamps negative ages
- `repo/controls/mcm.yaml`         MCM-07 severity medium -> high
