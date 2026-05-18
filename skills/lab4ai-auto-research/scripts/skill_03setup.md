# Step 3: Project setup (Gate Step 1)

**Prerequisites:** `skill_01lab_instance.md` 阶段已按 Gate 处理（Lab=no 可为 skipped）；`skill_02policies.md` 已完成（Gate log、命令展示、确认策略）。

When starting a new experiment, follow these steps:

1. **Confirm project path (required)**: Ask the user to confirm the exact project root path before doing anything else.
   Do not continue if the project path is not explicitly confirmed.
2. **Choose an experiment tag**: Use a date or task-based name (e.g., `apr1`), and use a branch like `autoresearch/<tag>`.  
   `run_tag` does **not** require user confirmation; generate it directly unless the user explicitly specifies one.
3. **Create an experiment branch**: Create a new branch from the current main development branch.  
   `base_branch` does **not** require user confirmation; use the project default branch (prefer `main`, fallback `master` if needed).
4. **Read project docs first**: Fully read `README.md` (and `docs/`, `CONTRIBUTING`, etc.) and extract:
   - Recommended environment and dependency installation method
   - Training launch command
   - Data preparation requirements
   - Allowed/disallowed file modification scope
   - Primary metric and optimization direction (higher is better or lower is better)
5. **Auto-detect the training entrypoint**: Prefer the command in README; then check common entrypoints:
   - `train.py`, `main.py`, `run.py`, `fit.py`
   - `src/**/train.py`, `scripts/train.py`, `tools/train.py`
   - `python -m <module>` (mapped to `__main__.py`)
   - `console_scripts` in `pyproject.toml` / `setup.cfg` / `setup.py`
   - **Multiple candidates:** If more than one plausible training entrypoint exists and README does not uniquely specify which to use, list every candidate (path and suggested launch command) and **require the user to confirm exactly one** before continuing. Do not pick arbitrarily.
6. **Auto-detect hyperparameter/search config files**: Focus on:
   - `configs/**`, `conf/**`
   - `sweep.yaml`, `wandb_sweep.yaml`
   - `optuna*.yaml`, `*_study.yaml`
   - `ray_tune.yaml`, `tune_config.py`
   - `search_space.*`, `hparams.*`, `params.*`
   If there is no standalone config file, treat hyperparameter constants/dictionaries in the training entrypoint as a "code-based config."
7. **Confirm detection results (required)**: Send the following to the user and wait for confirmation before continuing:
   - **Single chosen** training entrypoint (file path or module) and full launch command—if multiple were candidates, this must be the user-confirmed choice
   - Hyperparameter/search config file path (or code-based config location)
   - How config is passed into training (e.g., `--config` / `--config-name` / framework mechanism)
8. **Check data availability / dataset downloads (mandatory user choice when multiple)**:
   - Ensure data paths, caches, and preprocessing artifacts are ready before training.
   - **If the project requires downloading or preparing more than one distinct dataset** (e.g. multiple benchmarks, optional splits, README lists several `download_*.sh` / Kaggle / HuggingFace datasets, or “choose one of A/B/C”), **you must ask the user which dataset(s) to download or use**—list each option with a short label (name, rough size or source if known) and **wait for an explicit choice**. **Do not** download “everything by default,” **do not** pick one dataset arbitrarily, and **do not** start large downloads until the user has confirmed which subset applies to their experiment.
   - If only a single required dataset path is documented with no alternatives, you may proceed after confirming paths with the user as in step 7.
9. **Initialize results table**: Create `results.tsv` (header only) to record each experiment.

**Example commands for Step 1 (substitute confirmed project path and detected names; show these to the user before running):**

```bash
cd "<project_root>"
git status
git fetch origin
git checkout <base_branch>    # e.g. main or master; must match project default
git pull --ff-only
git checkout -b "autoresearch/<tag>"

# Header only; replace <primary_metric> with the real metric key name, e.g. val_loss
printf 'commit\t<primary_metric>\tmemory_gb\tstatus\tdescription\n' > results.tsv
```

Only enter the experiment loop after **explicit user confirmation** of Step 1 items (especially step 7) **and** Step 5 pre-loop stop conditions. Do not enter the loop on assumed approval.

---

**Previous:** `skill_02policies.md` — **Next:** `skill_04environment.md`
