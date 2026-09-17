# Delivery roadmap · September 14–October 13, 2026

Dates are working targets, not claims of completed work. Deliver vertical improvements with tests and measured evidence. Prefer fixing validity problems over adding models.

| Window | Outcome | Acceptance evidence |
|---|---|---|
| Sep 14–16 | Harden acquisition, schema, timezone and quality audit | Six official months; hashes; conservation and failure-mode tests; outage/duplicate sensitivity |
| Sep 17–19 | Baseline and EDA review | Measured five-baseline scores; zero-demand, zone, hour, borough and rush-hour errors; useful geographic plots |
| Sep 20–22 | Walk-forward model comparison | Expanding chronological folds inside Dec–Apr; compare linear/Ridge/boosting and XGBoost; no test access |
| Sep 23–25 | Bounded tuning and uncertainty | Recorded parameter search budget; paired daily block bootstrap of improvements; demand-latency ablation |
| Sep 26–28 | Spatial modeling | Geometry-derived adjacency and area; strictly lagged neighbor/borough demand; spatial feature ablations |
| Sep 29–Oct 1 | NOAA weather | Real observations, UTC joins, explicit availability lag and quality flags; measured weather ablation |
| Oct 2–4 | Interpretation and statistical review | Temporal permutation importance or justified alternative; hard-zone cases; forecast-vs-actual examples |
| Oct 5–7 | Prediction and interactive display | API consumes shared transformations; real forecast map with time/zone controls; deployment packaging |
| Oct 8–10 | Monitoring and reproducibility | Drift and missing-feed checks; clean-install full reproduction; CI; model/data versioning |
| Oct 11 | Freeze model selection | Commit protocol, champion, feature list and final hyperparameters before test execution |
| Oct 12 | Final held-out test | One recorded May evaluation with slices and intervals; no test-driven retuning |
| Oct 13 | Portfolio release | Honest model card, final README, limitations, screenshots, release and final state |

## Already implemented in the initial milestone

- Official cached acquisition, hashes, schema audit and dense hourly panel.
- Leakage-safe lags and rolling features; chronological development partitions.
- Five baselines plus linear regression, Ridge and histogram gradient boosting.
- JSON experiment tracking, data-quality reports and analytical maps.
- Shared-feature local FastAPI inference and automated tests.

See PROJECT_STATE.md for whether each component has actually been executed and verified.

## September 14 progress

Completed a reproducible all-column exact-duplicate audit and alternate-target baseline evaluation over December–April: zero exact excess rows and unchanged baseline scores. Added source-hash preflight, reporting-volume investigation flags, and stronger densification integrity checks; 45 tests pass. The canonical dataset is reproduced byte-for-byte. [The data-quality review](reports/DATA_QUALITY_REVIEW.md) distinguishes February 23 weather-related context from an unresolved Vendor 7 anomaly on January 5–6. No flagged hours are removed. Next: development-only walk-forward validation and a fixed sparse-zone loss comparison protocol; provider follow-up remains open.

## September 17 progress

Completed the frozen expanding walk-forward study ahead of the target window: ten candidates, three development folds, fifteen fits and 559,370 forecasts per candidate. Squared-error boosting leads every fold and reduces pooled MAE 27.65% against the weekly baseline. Alternative losses improve sparse-zone MAE but worsen overall MAE and RMSE; no automatic promotion. All original April metrics reproduce exactly, May remains sealed, and 59 tests pass. See the [measured review](reports/WALK_FORWARD_REVIEW.md). XGBoost and bounded tuning remain unimplemented; establish paired uncertainty and observation-latency sensitivity before expanding the candidate budget. API artifact and canonical observations are unchanged.

## Working rules

Read PROJECT_STATE.md and the latest experiment before selecting the next bounded task. Inspect local Git state; preserve user changes. Use the single public repository `gitLamHoang/nyc-mobility-intelligence` and primary branch `main`. Do not create a differently named repository or force-push. Run relevant tests, Ruff, and the changed pipeline stage before substantive commits. Commit and push completed verified work; inspect CI. Record failed hypotheses and negative results. Never invent data, metrics or completed work. Keep raw data/model binaries out of Git. Never optimize on May test results.

Daily continuation is intended at 09:00 America/Los_Angeles from September 14 through October 13, 2026, returning to the same Codex task. Finish the current bounded milestone on each run, update state/changelog, and notify only for meaningful progress, failures, completion or necessary user action. End the scheduled development after October 13; do not silently extend the project.
