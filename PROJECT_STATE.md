# Project state

Updated: initial milestone, September 13, 2026 (America/Los_Angeles).

Repository: https://github.com/gitLamHoang/nyc-mobility-intelligence · public · main.

## Verified

- Six official months downloaded, 2025-12 through 2026-05, plus lookup and boundaries.
- 23,263,775 accepted NYC yellow-taxi pickups, 262 zones, 4,367 UTC hours, 1,144,154 panel rows.
- Acquisition and aggregation executed against real data.
- 26 behavioral tests passed; Ruff lint and formatting checks passed.
- Five baselines and three classical models trained on 716,570 zone-hours and scored on 188,640 April validation zone-hours.
- Best validation MAE: histogram gradient boosting 3.47999; weekly baseline 4.30547 (19.17% reduction). RMSE 9.69976, R² 0.97157. SMAPE 104.05% is materially worse than weekly baseline 57.40%.
- Rendered and visually inspected real temporal EDA and demand/error maps using official geometries. Fixed loading of the official ZIP's nested shapefile directory.
- HTTP API smoke test with 168 real prior hours: zone 237, April 8 00:00 NYC target, prediction 26.63416 vs actual 31. API matched offline output exactly; short history returned HTTP 422.
- Daily continuation active at 09:00 America/Los_Angeles, September 14–October 13 inclusive. Automation ID: `build-nyc-mobility-intelligence`; stop/pause instructions and an October 13 end limit are saved.

## Publication and reproducibility checks

- Implementation published to `main` in commit `587f897d19141b6f0f65454450cf7d17e936c6f5`.
- [GitHub CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/34812627304): locked Linux installation, Ruff lint/format and pytest.
- All source-file, dependency-lock and processed-data hashes in the latest experiment match the local implementation and cached data. API evidence references the same experiment ID.
- Repeated full model fitting reproduced all eight candidates' validation metrics exactly. This is a reproducibility check, not an independent statistical trial.
- Download cache rechecked successfully for all eight official assets. Staged-file audit confirmed no raw data, processed Parquet, model binaries or virtual environment were published.
- Local API processes were stopped after smoke verification. Restart with the README command when needed.

## Validation contract

Train Dec–Mar (168-hour feature warm-up), validation April, test May. All boundaries are local NYC midnight; stored timestamps are UTC. May labels are excluded by Parquet filters in training/reporting. Test metrics remain null. This is one-step rolling observed-history evaluation with an immediate prior-hour availability assumption.

## Next development priority

Diagnose source coverage/duplicate sensitivity and the model's sparse-zone overprediction before expanding models. In April, 73,595 targets are zero: boosting predicts a positive value for 99.986% of them, averaging 0.5505 pickups; the weekly baseline averages 0.3896. Staten Island R² is -2.201. Implement development-only walk-forward validation, then bounded tuning and count-aware loss comparisons. The initial API is local and retrospective; weather, spatial predictors, interactive display, drift monitoring, final test and deployment packaging remain open.

Locked packages produce upstream pandas/NumPy and Starlette/httpx deprecation warnings; tests pass. Review compatible dependency upgrades during hardening rather than suppressing warnings.

## Continuity

Canonical decisions and remaining work live in this file and ROADMAP.md. The user's original supplied specification is preserved in [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md). Raw data is ignored and cached locally. Each substantive commit requires tests, lint, and execution of the changed stage. Update CHANGELOG.md and this file with exact evidence. Never equate a planned feature with a delivered result. Local scheduled runs require the computer powered on and Codex running with repository access.
