# Project state

Updated: September 20, 2026 (America/Los_Angeles), frozen observation-latency study completed.

Repository: https://github.com/gitLamHoang/nyc-mobility-intelligence · public · main.

## Verified

- Six official months downloaded, 2025-12 through 2026-05, plus lookup and boundaries.
- 23,263,775 accepted NYC yellow-taxi pickups, 262 zones, 4,367 UTC hours, 1,144,154 panel rows.
- Acquisition and aggregation executed against real data.
- 105 behavioral tests passed; Ruff lint and formatting checks passed.
- Five baselines and three classical models trained on 716,570 zone-hours and scored on 188,640 April validation zone-hours.
- Best validation MAE: histogram gradient boosting 3.47999; weekly baseline 4.30547 (19.17% reduction). RMSE 9.69976, R² 0.97157. SMAPE 104.05% is materially worse than weekly baseline 57.40%.
- Rendered and visually inspected real temporal EDA and demand/error maps using official geometries. Fixed loading of the official ZIP's nested shapefile directory.
- HTTP API smoke test with 168 real prior hours: zone 237, April 8 00:00 NYC target, prediction 26.63416 vs actual 31. API matched offline output exactly; short history returned HTTP 422.
- Daily continuation active at 09:00 America/Los_Angeles, September 14–October 13 inclusive. Automation ID: `build-nyc-mobility-intelligence`; stop/pause instructions and an October 13 end limit are saved.
- September 14 `audit-quality`: all-column exact duplicate search found zero excess rows among 19,179,942 eligible December–April pickups. Five alternate-label baseline scores exactly equal the original scores. No canonical labels or model artifacts were changed.
- Reporting-volume audit: zero citywide zero-count hours; 19 overlapping city/vendor flags. Four city flags are February 23 07:00–10:00 NYC during independently documented blizzard/travel restrictions. A localized Vendor 7 anomaly on January 5–6 remains unresolved. See [DATA_QUALITY_REVIEW.md](reports/DATA_QUALITY_REVIEW.md).
- Densification now rejects silent count loss, invalid counts and overflow. The real six-month preparation rerun reproduces the original Parquet byte-for-byte. May was processed only for unchanged ingestion verification, not model evaluation.
- September 17 `backtest`: executed the September 16 frozen protocol across February, March and April, with fifteen model fits and five baselines per fold. All ten candidates cover the same 559,370 zone-hours. Each pipeline refits independently; March contains 743 validation hours.
- Squared-error boosting leads every fold and pooled MAE: 3.69295 versus weekly baseline 5.10423 (27.65% reduction), pooled RMSE 10.26719, R² 0.96689 and SMAPE 102.58%. Poisson and absolute-error losses improve sparse-zone MAE in every month but worsen overall MAE/RMSE. Squared-error boosting loses to the weekly baseline on sparse-zone MAE in every fold. See [WALK_FORWARD_REVIEW.md](reports/WALK_FORWARD_REVIEW.md).
- Saved immutable fold/slice metrics, 89 days of paired daily MAE, and exact provenance in backtest `20260917T165035Z-e037f0`. Forecast Parquet files remain ignored. No model promotion, tuning or test evaluation occurred. Rendered and visually inspected the comparison figure.
- September 19 `uncertainty`: reused the 890 saved daily/model summaries, with 10,000 paired circular-block replicates each for 1-, 7- and 14-day blocks. No model refits or target-Parquet reads. The primary seven-day interval for squared-error boosting's 27.65% MAE reduction versus weekly is 22.63%–31.93% (nominal 95%). All three comparison directions persist across block lengths. These are conditional, marginal intervals rather than future-performance guarantees; see [UNCERTAINTY_REVIEW.md](reports/UNCERTAINTY_REVIEW.md).
- Uncertainty run `20260919T230732Z-d57c88` records fixed inputs, parameters and hashes. Coverage checks enforce every date/model and the 23-hour DST day; paired draws retain actual row weights. Seven existing data/model/evidence files are unchanged. Rendered and visually inspected the interval figure.
- September 20 `latency`: completed twelve fixed squared-error boosting fits for delays 0/1/3/6 hours across the three development folds. Every setting uses common training targets (174-hour warm-up and six-hour label embargo) and the same 559,370 validation zone-hours. Recent history respects availability; day/week lags and target-time calendars stay aligned.
- Pooled MAE rises from 3.69575 at zero delay to 4.16821, 4.43988 and 4.54341 at 1/3/6 hours: increases of 12.78%, 20.13% and 22.94%. The weekly baseline stays at 5.10423; boosting's MAE advantage shrinks from 27.59% to 10.99%. Every validation month degrades, and sparse-zone weakness persists. See [LATENCY_REVIEW.md](reports/LATENCY_REVIEW.md).
- Latency run `20260921T021023Z-588968` uses a UTC identifier but was executed September 20 Pacific. Saved all 24 pooled candidate/setting scores, 72 fold scores, 2,136 daily errors, cohort diagnostics and exact provenance. The plotted real results were visually inspected. No model promotion or May evaluation occurred.

## Publication and reproducibility checks

- Implementation published to `main` in commit `587f897d19141b6f0f65454450cf7d17e936c6f5`.
- [GitHub CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/34812627304): locked Linux installation, Ruff lint/format and pytest.
- September 14 audit published in `bb5091b74bb2be1f8faad96f9a0d597232b0d072`; [its GitHub CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/34882238312) with the expanded test suite. The working tree was clean after push.
- The initial model experiment describes the September 13 source snapshot; subsequent CLI/preparation/audit code changes are recorded separately by source hashes in [latest_quality_audit.json](reports/latest_quality_audit.json). Model features, fitted artifact, dependency lock and processed-data content remain unchanged. API evidence still references the original model experiment ID.
- Repeated full model fitting reproduced all eight candidates' validation metrics exactly. This is a reproducibility check, not an independent statistical trial.
- Download cache rechecked successfully for all eight official assets. Staged-file audit confirmed no raw data, processed Parquet, model binaries or virtual environment were published.
- Local API processes were stopped after smoke verification. Restart with the README command when needed.
- Walk-forward protocol was committed before execution in `15db9760a6fb0b74a0693d68f5e54ea55b4b4a0f`; [that commit's CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/35134528450). The new run records this parent revision plus exact hashes of the implemented runner's twenty source files. Its worktree-dirty flag is intentional and documented.
- [Backtest verification](reports/backtests/20260917T165035Z-e037f0/verification.json) confirms exact reproduction of all eight original April candidates' metrics, matching source/protocol/lock hashes, and unchanged canonical data, serving artifact/metadata, original predictions, original experiment pointer and API smoke evidence. Prepublication local checks: 59 tests, Ruff, full real-data backtest and figure generation passed. Published implementation commit `04e6f1d80d426a7bc8d2ac2f97917a73b2461e2e`; [GitHub CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/35249870571), including locked Linux installation and all 59 tests.
- Uncertainty protocol was frozen in `4ee6c4b0103ea14894836350c468b41f5df4ab0b` before intervals were computed; [its CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/35474976873). The implemented runner's source hashes identify the executed worktree. [Verification evidence](reports/uncertainty/20260919T230732Z-d57c88/verification.json) confirms matching source/input/protocol/lock hashes and unchanged existing artifacts. Prepublication checks: all 84 tests, Ruff, actual uncertainty stage and plotting passed.
- Uncertainty implementation and the next latency protocol were published in `59e6f1f99401319f765171471cf3f5ae1c5b59a6`; [GitHub CI passed](https://github.com/gitLamHoang/nyc-mobility-intelligence/actions/runs/35475526538), including locked Linux installation, Ruff and all 84 tests. No raw observations, model binaries or bootstrap draw arrays were staged. The local working tree matched `origin/main` after publication.
- [Latency verification](reports/latency/20260921T021023Z-588968/verification.json) confirms matching source/protocol/lock hashes and eight unchanged data/model/evidence files. Original zero-delay features match exactly on 903,638 development rows; the existing artifact reproduces all 188,640 original April predictions. Training hashes and validation targets match across delays; invariant baselines and daily weighted MAEs reconcile. All 105 tests, Ruff, the actual twelve-fit stage and plotting passed locally.

## Validation contract

Original serving experiment: train Dec–Mar (168-hour feature warm-up), validation April, test May. Development backtest: expanding training from Dec 1, validating February, March and April in separate nonoverlapping windows. The separate latency experiment uses common 174-hour warm-up and a six-hour training-label embargo, with matched zero-delay and delayed controls. All boundaries are local NYC midnight; stored timestamps are UTC. May labels are excluded by Parquet filters before feature construction. Test metrics remain null. The original API still assumes complete prior-hour counts; the latency study measures fixed delayed-history alternatives without promoting them. Development months were previously inspected or used for training; do not call them independent untouched tests. Constant-target R² is now null; older immutable reports preserve their original values.

## Next development priority

Exact-duplicate sensitivity is completed with a negative result; retain recorded counts. Follow up on Vendor 7's January 5–6 anomaly without inventing or removing trips. Keep February 23 low-volume hours: the independently documented weather/travel event makes automatic outage labeling inappropriate.

Walk-forward losses, paired uncertainty and the frozen latency experiment are complete. Next freeze a small, justified XGBoost comparison budget before installing/configuring its new estimator and fitting it. Use the established February–April folds, shared target coverage and explicit input availability; compare against both the current boosting control and weekly baseline. Keep delay sensitivity as a reference and do not imply that model improvements supply a live observation feed. State which training contract is used so scores are not mixed between the original backtest and the matched latency control.

Do not repeat the twelve latency fits merely to summarize existing results. The published daily errors and ignored forecast tables support further analysis if justified by a new protocol. The original API remains unchanged; its 168-hour request contract supports the original zero-delay model only. Delayed models were not saved or promoted. May stays sealed, and spatial/weather ablations, interpretation, interactive display and deployment/monitoring work remain open.

Keep the serving artifact unchanged until a subsequent promotion decision is justified. In April, absolute-error loss cuts sparse-zone MAE from 0.47240 to 0.31002, but raises citywide MAE from 3.47999 to 3.73363; simple loss replacement is not an aggregate improvement. Freeze a budget before new tuning, XGBoost or spatial/weather comparisons. The initial API is local and retrospective; weather, spatial predictors, interactive display, drift monitoring, final test and deployment packaging remain open.

Locked packages produce upstream pandas/NumPy and Starlette/httpx deprecation warnings; tests pass. Review compatible dependency upgrades during hardening rather than suppressing warnings.

## Continuity

Canonical decisions and remaining work live in this file and ROADMAP.md. The user's original supplied specification is preserved in [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md). Raw data is ignored and cached locally. Each substantive commit requires tests, lint, and execution of the changed stage. Update CHANGELOG.md and this file with exact evidence. Never equate a planned feature with a delivered result. Local scheduled runs require the computer powered on and Codex running with repository access.
