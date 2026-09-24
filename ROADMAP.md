# Delivery roadmap · September 14–October 13, 2026

Dates are working targets, not claims of completed work. Deliver vertical improvements with tests and measured evidence. Prefer fixing validity problems over adding models.

| Window | Outcome | Acceptance evidence |
|---|---|---|
| Sep 14–16 | Harden acquisition, schema, timezone and quality audit | Six official months; hashes; conservation and failure-mode tests; outage/duplicate sensitivity |
| Sep 17–19 | Baseline and EDA review | Measured five-baseline scores; zero-demand, zone, hour, borough and rush-hour errors; useful geographic plots |
| Sep 20–22 | Walk-forward model comparison | Expanding chronological folds inside Dec–Apr; compare linear/Ridge/boosting and XGBoost; no test access |
| Sep 23–25 | Bounded tuning and uncertainty | Recorded parameter search budget; paired daily block bootstrap of improvements; demand-latency ablation |
| Sep 26–28 | Spatial modeling | Audit geometry provenance/identity; lagged borough ablations; polygon features only after historical mapping is verified |
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

## September 19 progress

Completed the frozen paired uncertainty study from the existing daily errors, without refitting models: 10,000 paired replicates each for 1-, 7- and 14-day circular blocks within monthly folds. The primary nominal 95% interval for the 27.65% MAE improvement over weekly is 22.63%–31.93%; all three planned comparison directions persist under every block length. These conditional intervals do not guarantee future-month performance. Input integrity, model pairing, DST weights and artifact preservation are tested; 84 tests pass. See [UNCERTAINTY_REVIEW.md](reports/UNCERTAINTY_REVIEW.md). The [latency protocol](docs/LATENCY_PROTOCOL.md) is now frozen: twelve fits across delays 0/1/3/6 hours, matched training coverage and all original validation rows. Execution is the next milestone; no latency results are claimed.

## September 20 progress

Executed the frozen latency sensitivity: twelve independently fitted models for 0/1/3/6-hour delays, common training labels and identical validation targets. Pooled MAE increases 12.78%, 20.13% and 22.94% against the matched zero-delay control; the six-hour model retains a 10.99% advantage over weekly. Published all baselines, monthly/cohort metrics, daily errors and a reproducible figure. Zero-delay features and all original April predictions match exactly, existing artifacts are unchanged, and 105 tests pass. See [LATENCY_REVIEW.md](reports/LATENCY_REVIEW.md). Next: freeze a small XGBoost comparison budget with explicit availability and training coverage before further fitting; no live-feed or May-test claims.

## September 21 progress

Completed the XGBoost budget frozen in `9a9d282`: exactly six fits, two depths, three development folds and shared latency-control targets. Depth 6 lowers pooled MAE 0.76422% to 3.667507 but raises RMSE to 10.334616; depth 4 worsens MAE 4.32719%. Sparse/zero-demand weakness remains, no model is promoted, and May stays sealed. Published every candidate's fold/slice/daily evidence and a reproducible, visually checked figure; 118 tests and Ruff pass. See [XGBOOST_REVIEW.md](reports/XGBOOST_REVIEW.md). Next: freeze paired uncertainty for both new contrasts using saved daily errors, then spatial ablations. Do not add fits solely to chase the small gain. Clean-checkout reconstruction of pinned ignored controls remains a reproducibility hardening item.

## September 22 progress

Completed the precommitted paired XGBoost uncertainty analysis without fitting: 10,000 replicates each for 7/1/14-day blocks, with the same sampled dates for every model and actual DST row weights. The two-contrast-adjusted primary interval for depth 6's MAE difference is [−0.042128, −0.014221]; depth 4 remains worse at [0.142768, 0.176634]. All directions persist across sensitivities, with explicit conditional-coverage and repeated-selection limits. No serving promotion, dependency changes or May access. Published all six comparisons, draw hashes, a verified figure and isolated-directory reproduction; 137 tests and Ruff pass. See [XGBOOST_UNCERTAINTY_REVIEW.md](reports/XGBOOST_UNCERTAINTY_REVIEW.md). Next: official geometry audit and precommitted spatial ablation, with separate static/past-only demand bundles and matched controls.

## September 23 progress

Completed the official spatial-source audit and real borough-feature preparation. Current geometry has 604 qualifying boundary edges and five isolates, but February 2026 timestamps do not establish availability at the December training origin. The older June 2025 source duplicates IDs 56/103 and omits 57/104/105; a direct historical polygon join is ineligible. Prepared 905,210 complete rows using the older lookup, five borough indicators and two strictly lagged other-zone means. Existing temporal features and all 559,370 matched-control validation targets remain identical. Repeated feature tables and 1,048 independent peer checks match exactly; 13 existing artifacts are unchanged, 166 tests/Ruff pass, and no models were fitted. See [SPATIAL_PREPARATION_REVIEW.md](reports/SPATIAL_PREPARATION_REVIEW.md). Next: implement and execute the frozen [six-fit borough ablation](docs/BOROUGH_SPATIAL_PROTOCOL.md). Polygon predictors wait for verified historical ID mapping; May remains sealed.

## September 24 progress

Executed the six-fit borough budget frozen in `b92b982`. Indicators lower pooled MAE 0.079024%; adding lagged other-zone borough means lowers it 0.415762% versus temporal (3.695750 → 3.680385), with RMSE improving 10.278490 → 10.240313. The peer bundle improves aggregate MAE in every month but worsens sparse-zone and zero-target MAE versus temporal in all three folds. No automatic promotion. All 559,370 validation targets and saved controls match; 14 existing artifacts are preserved, 189 tests/Ruff pass, and all 712 daily errors independently reconcile. See [BOROUGH_REVIEW.md](reports/BOROUGH_REVIEW.md). Next execute the frozen [three-contrast paired uncertainty](docs/BOROUGH_UNCERTAINTY_PROTOCOL.md) without fits, then audit NOAA hourly weather coverage/availability. Polygon features remain deferred pending historical mapping; May stays sealed.

## Working rules

Read PROJECT_STATE.md and the latest experiment before selecting the next bounded task. Inspect local Git state; preserve user changes. Use the single public repository `gitLamHoang/nyc-mobility-intelligence` and primary branch `main`. Do not create a differently named repository or force-push. Run relevant tests, Ruff, and the changed pipeline stage before substantive commits. Commit and push completed verified work; inspect CI. Record failed hypotheses and negative results. Never invent data, metrics or completed work. Keep raw data/model binaries out of Git. Never optimize on May test results.

Daily continuation is intended at 09:00 America/Los_Angeles from September 14 through October 13, 2026, returning to the same Codex task. Finish the current bounded milestone on each run, update state/changelog, and notify only for meaningful progress, failures, completion or necessary user action. End the scheduled development after October 13; do not silently extend the project.
