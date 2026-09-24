# Changelog

## September 24, 2026 · measured borough feature ablation

- Added `nyc-mobility borough` and executed exactly six fits under the protocol frozen in `b92b982`. Reused shared control integrity/coverage checks, unchanged temporal features and independent per-fold preprocessing; recorded actual transformed dtypes, column order and resolved parameters.
- Indicators lower pooled MAE 0.079024%; indicators plus past-only peer demand lower MAE 0.415762% (3.695750 → 3.680385) and RMSE 10.278490 → 10.240313. Sparse-zone and zero-target MAE worsen against temporal in every fold for the peer bundle. Reported every candidate and slice without promotion or May evaluation.
- Published eight pooled scores, 24 fold scores, 12 contrasts, 888 slices, 712 daily errors and a visually verified figure. Added a no-fit verifier that reconciles all pooled/fold MAE/RMSE and daily rows against saved forecasts. Preserved 14 existing data/model/evidence/lock files; full forecast tables remain ignored.
- Expanded to 189 passing tests covering frozen budgets, append-only representations, fresh preprocessing, invalid controls/source mutation and held-out exclusion. Ruff and the actual study/verifier/plot pass. No dependencies added. Froze three-contrast paired uncertainty before resampling; execution is next, followed by authoritative weather preparation.

## September 23, 2026 · spatial source audit and borough features

- Added `nyc-mobility spatial-prepare` with pinned official sources, full development-window and peer coverage checks, geometry identity/topology audits and isolated output provenance. Current geometry yields 604 boundary edges and five isolates, but historical availability is unverified. The older June 2025 release duplicates IDs 56/103 and omits 57/104/105; no guessed remapping or polygon modeling.
- Prepared five borough indicators and two past-only other-zone means over 949,226 real December–April rows (905,210 complete after temporal warm-up), using the older lookup. Existing temporal columns match exactly, repeated feature tables are byte-identical and 1,048 real peer checks have zero discrepancy.
- Verified all matched-control training signatures, cohorts and 559,370 validation targets without fitting; preserved 13 existing data/model/evidence/lock files. Published compact numeric audits, feature summaries, provenance and a visually checked map; raw sources and the full table remain ignored.
- Expanded to 166 passing tests, including unavailable-tail perturbations at all four delays, focal-zone exclusion, truncated peer coverage, invalid/overlapping geometry, source integrity and held-out exclusion. Ruff and the real stage/plot pass. Froze the next six-fit static/context borough ablation before fitting; comparison execution remains the next milestone. No serving change or May evaluation.

## September 22, 2026 · paired XGBoost uncertainty

- Froze both candidate contrasts and Bonferroni error allocation in `fccf7b4` before resampling. Added `nyc-mobility xgboost-uncertainty`, reusing the unchanged tested circular-day/bootstrap alignment functions and publishing separate reports.
- Executed 10,000 paired replicates per 7/1/14-day block setting from the tracked 712 daily errors. The primary depth-6 MAE difference −0.028244 has adjusted interval [−0.042128, −0.014221]; depth 4's +0.159922 has [0.142768, 0.176634]. Both directions persist across settings. Marginal relative intervals are explicitly distinct from the two-contrast-adjusted absolute intervals.
- Published six comparison rows, exact provenance, ignored draw arrays and a visually verified figure. Reproduced every result and all draw arrays in an isolated directory without data or pre-existing artifacts, using the same locked environment. Eleven prior data/model/evidence/lock files are unchanged.
- Expanded to 137 passing tests covering family membership, percentile arithmetic, no-fit/no-model/no-Parquet behavior, invalid/held-out inputs and protocol mutation. Ruff and the real analysis/plot stages pass. The small MAE gain does not resolve worse RMSE or sparse-demand weaknesses; no promotion or May evaluation. Next: official geometry audit and a frozen spatial-feature ablation.

## September 21, 2026 · bounded XGBoost comparison

- Froze the six-fit protocol in `9a9d282` before installation or fitting. Added `nyc-mobility xgboost`, XGBoost 3.4.1 platform-aware CPU dependencies, dense zone encoding with real zeros, and prefit control/data/feature/coverage integrity checks. Existing locked versions and the serving model are unchanged. macOS requires libomp.
- Executed depths 4 and 6 over three expanding folds with the matched zero-delay latency contract. Depth 6 lowers pooled MAE 0.76422% (3.695750 → 3.667507) but worsens RMSE (10.278490 → 10.334616); depth 4 increases MAE 4.32719%. Sparse and zero-target limitations remain. No additional search, promotion or May evaluation.
- Saved eight pooled scores, 24 fold scores, 888 slices, 712 daily paired errors and exact provenance in `20260922T032057Z-3ecc9d`. Reused all controls without refitting, reconciled metrics and DST day weights, and verified nine unchanged artifacts. Six new fit/predict operations took 18.522615 seconds locally.
- Expanded to 118 passing tests covering dense-zero semantics, unknown zones, frozen budgets, independent fits, test exclusion, control tampering/absence and artifact preservation. Ruff, the real comparison stage and visually checked plotting pass. Documented the ignored-control prerequisite and small-gain uncertainty limitation. Next: precommitted paired uncertainty for both new contrasts, then spatial features.

## September 20, 2026 · observation-latency sensitivity

- Implemented `nyc-mobility latency` and executed the previously frozen protocol: exactly twelve model fits for 0/1/3/6-hour delays with common 174-hour warm-up, six-hour training-label embargo and all 559,370 validation zone-hours per setting.
- Added availability-aware recent lags, trailing windows and trend while preserving target-anchored seasonal lags and calendars. The default zero-delay API path remains identical. Shared fold fitting now records training-target hashes and supports explicit warm-up/embargo without changing the original backtest defaults.
- Measured pooled MAEs of 3.69575, 4.16821, 4.43988 and 4.54341. Delays increase MAE 12.78%, 20.13% and 22.94%; boosting's advantage over the weekly baseline falls from 27.59% to 10.99%. Published all candidate/fold/slice results, paired daily errors and a figure. No new tuning, model promotion or May evaluation.
- Expanded to 105 passing tests, including unavailable-tail perturbations, delayed rolling boundaries, seasonal/calendar alignment, matched training labels, fresh fits and held-out exclusion. Ruff and the real twelve-fit/plot stages pass.
- Verified identical zero-delay features on 903,638 development rows, exact reproduction of 188,640 original April forecasts, eight unchanged data/model/evidence files, shared targets and daily metric reconciliation. The next milestone is a frozen, bounded XGBoost comparison.

## September 19, 2026 · paired block uncertainty

- Froze the uncertainty protocol in `4ee6c4b` before resampling. Added `nyc-mobility uncertainty` using immutable, hash-pinned daily errors; no model fitting or target-Parquet access is required.
- Executed 10,000 paired circular-block replicates each at 1-, 7- and 14-day lengths. Preserved model pairing, monthly composition and each day's zone-hour weight, including March 8's 23 hours. Added coverage/integrity/reconciliation checks and isolated output provenance.
- The observed 27.65% MAE reduction versus weekly has a primary nominal 95% interval of 22.63%–31.93%. All three planned comparison directions persist across block lengths. Published all nine intervals, a reproducible figure, and explicit limits on conditional inference; no model promotion or May evaluation.
- Expanded to 84 passing tests covering block sampling, paired errors, deterministic seeds, percentile calculations, DST weighting, input failures and artifact preservation. Ruff and the actual uncertainty/plot stages pass. Seven existing data/model/evidence files remain byte-identical.
- Froze the next observation-latency study: delays 0/1/3/6 hours, twelve fixed model fits, matched training coverage, preserved target-time calendars and seasonal lags, availability-safe recent history, and unchanged validation coverage. The latency study has not run yet.

## September 17, 2026 · expanding walk-forward loss comparison

- Executed the protocol frozen September 16 in `15db976`: three expanding development folds, ten candidates and exactly fifteen model fits, with no May targets or hyperparameter search.
- Added `nyc-mobility backtest`, complete zone/hour coverage checks, independent fold preprocessing/refits, train-defined sparse cohorts, pooled metrics, borough/calendar/zero-demand diagnostics and daily paired MAE summaries. Results are isolated from the serving model and original April experiment.
- Evaluated 559,370 real February–April zone-hours per candidate. Squared-error boosting leads every fold: pooled MAE 3.69295 versus weekly baseline 5.10423 (27.65% lower). Poisson and absolute-error losses improve sparse-zone MAE but worsen overall MAE and RMSE. Published the tradeoff with immutable provenance, tables and a reproducible figure.
- Corrected constant-target R² to null rather than a forced finite value. Existing immutable experiment reports retain their original results; all eight original April aggregate scores reproduce exactly.
- Expanded to 59 passing tests covering folds/DST, equal coverage, fresh pipelines, training-only cohorts, pooled metrics, test exclusion and serving-state preservation. Ruff and the complete real backtest pass. Verified that six existing data/model/evidence files remain byte-identical.

## September 14, 2026 · data-quality hardening

- Added `nyc-mobility audit-quality`: development-only exact all-column duplicate search, hash-verified source preflight, canonical count reconciliation, and a separate alternate-label baseline sensitivity evaluation.
- Audited 19,179,942 eligible December–April pickups: no exact duplicates, unchanged baseline metrics, no citywide zero-count hours. Retained all recorded labels and the existing model.
- Added causal historical reporting-volume references for city/vendor series. Documented 19 overlapping investigation flags, official February 23 blizzard/travel-restriction context, and an unresolved January 5–6 Vendor 7 anomaly. Flags are not automatic outage labels.
- Hardened densification against silent out-of-range count loss, noninteger/invalid counts, overflow and invalid timestamps. The six-month real preparation reproduces the existing Parquet byte-for-byte.
- Expanded the suite from 26 to 45 passing tests, including source-integrity failures, duplicate definitions, temporal causality, test-file exclusion and canonical-artifact preservation. Ruff passes. Saved immutable, reproducible audit evidence without evaluating May model performance.

## 0.1.0 · initial milestone

- Created public repository, Python package, locked environment, and CI.
- Implemented official TLC acquisition, source hashes, schema checks, data-quality audit and UTC hourly aggregation.
- Added strict past-only features, chronological development evaluation, five baselines and three classical regressors.
- Added experiment records, temporal EDA, geographic demand/error maps and validation error slices.
- Added validated local prediction API using the same feature builder as training.
- Added behavioral tests for temporal leakage, daylight-saving time, splits, metrics, missing values and prediction contracts.
- Executed the real six-month pipeline: 23.26 million accepted pickups, 262 zones, five baselines and three classical models. Initial April MAE improved 19.17% over the weekly baseline; documented the worse SMAPE and sparse-zone behavior.
- Verified 26 local tests, Linux GitHub CI, actual API/offline parity, official geometry maps, cache integrity and exact repeat-run metrics. May model evaluation remains sealed.
- Activated daily development at 09:00 Pacific for September 14–October 13, with durable state and an explicit end condition.

See PROJECT_STATE.md for execution evidence and remaining work; this is the beginning of the month-long project, not its final release.
