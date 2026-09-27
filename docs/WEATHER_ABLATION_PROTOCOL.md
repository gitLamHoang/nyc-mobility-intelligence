# Frozen conditional weather comparison

Freeze date: September 27, 2026. No weather model has been fitted. This protocol takes effect when committed together with the preparation evidence, before any candidate fitting.

## Question and evidence limits

Does adding a fixed citywide weather-and-quality bundle improve retrospective hourly taxi demand forecasts against the existing temporal histogram-boosting control? The primary weather delay is three hours; six hours is a declared sensitivity. These delays describe assumptions, not measured publication latency. Finalized NOAA archives do not establish historical publication or revision availability. Results will be conditional development evidence, not a live-service claim, causal weather effect or held-out test.

NOAA's source list documents 412 as NCEI-decoded SYNOP/BUFR and 413 as NCEI-decoded METAR. The source-specific main manual still supplies no passed-check meaning for their blank quality codes. The [versioned policy review](../reports/WEATHER_POLICY_REVIEW.md) therefore marks retained 412/413 values **unverified**, preserving the original strict audit. No claim is made that NOAA performed no checks. Neither the GHCN-Daily convention nor source-382 precipitation rules transfer to these fields.

## Fixed inputs and features

[weather_ablation.toml](../configs/weather_ablation.toml) pins the source audit, ignored snapshots, feature implementation, original quality-policy documents, TLC panel and shared control forecasts. The preparation stage verifies all three control folds before fitting is possible. Reusing exact snapshots is required; a new raw download with different bytes requires a new audit and protocol revision before fitting.

Use all three named stations as citywide inputs in fixed order: LaGuardia, JFK, Central Park. There is no inferred station-to-zone mapping, polygon feature or borough-context addition. At each target boundary, use the latest core observation with `observation_time + delay < target`, with observation age at most 12 hours. Preserve each field's missing/unverified status from that same observation. Never replace a missing/rejected field with an older reading or a future value.

Append exactly 30 features to the unchanged temporal predictors: per station, temperature (°C), dew point (°C), wind speed (m/s), three missing indicators, three unverified indicators and observation age (hours). Keep numeric NaNs; histogram boosting handles missing values. No weather-driven row deletion, interpolation, median imputation, scaling, weather-source selection or outcome-based feature selection. All features are shared at an hour across zones. Any measured difference belongs to the whole bundle, including quality and missingness; it does not isolate meteorological values from their indicators. The source transition is a distribution change and must be discussed in fold-level results.

Precipitation, forecasts of future weather, weather at the target hour, daily/monthly summaries, polygon mapping and extra weather parameters are excluded. The strict source-223 policy remains a published preparation sensitivity, not another model candidate with a different target population.

## Chronological comparison and fit budget

- Train from December 1, 2025; validate February, March and April in three separate expanding folds. May remains sealed.
- Use the shared zero-delay taxi control: 174 elapsed hours of common warm-up, six-hour training-label embargo, identical train signatures and sparse-zone cohorts. Taxi history availability remains the same zero-delay retrospective assumption for control and candidates.
- Exactly **six new fits**: three-hour weather and six-hour weather × three folds. Fresh preprocessing/model per fit. Reuse the hash-pinned temporal histogram and five baseline forecasts without refitting.
- Histogram squared-error boosting: random seed 42, 120 iterations, learning rate 0.08, 31 maximum leaf nodes, L2 1.0, 255 bins, early stopping off; keep the original nonordinal zone one-hot encoding and other locked estimator defaults. Append numeric features through the shared preprocessing pattern. Record resolved parameters, transformed dtype/column order, per-fit elapsed time, versions and hashes.
- Every candidate must predict the same **559,370** validation zone-hours: February 176,064; March 194,666; April 188,640. Training rows are 342,696 / 518,760 / 713,426. Inference is rolling one step ahead; no fold refit using validation labels. Clip negative forecasts to zero as in the control.
- Do not expand the search, alter source rules, retune delays or remove inconvenient targets after seeing candidate scores. Any failure stops the study and is reported; it does not silently authorize replacement fits.

## Required reporting and decisions

Primary descriptive contrast: three-hour weather versus temporal histogram, pooled MAE. Publish the six-hour contrast even if it is worse; also report three-versus-six descriptively without choosing a winner after inspecting it. Publish each fold and pooled MAE, RMSE, R² and SMAPE; sparse/dense, zero/positive, borough, rush-hour and local-hour slices; and paired daily absolute-error totals and row counts. Discuss quality/missingness differences by month using the already published audit.

Save ignored full validation forecasts with exact control keys. Reconcile scores from saved predictions and verify original artifacts remain unchanged. Do not report statistical significance from point estimates. Any later interval analysis must precommit pairing/block lengths and a family covering both weather-versus-temporal contrasts before resampling. Earlier XGBoost/borough intervals do not apply. Repeated development selection remains a limitation even after such an analysis.

No serving-model promotion, May evaluation or automatic operational deployment is authorized by an aggregate gain. Preserve sparse/zero-demand and RMSE tradeoffs and archive-availability limitations. Failure to improve the primary metric is a valid result; do not add models merely to obtain a positive outcome.
