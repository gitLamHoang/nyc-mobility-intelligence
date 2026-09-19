# Observation-latency protocol v1 · frozen September 19, 2026

This protocol specifies the next development experiment. It is committed before implementing or running the latency comparison. No latency results are available yet. The existing uncertainty analysis does not assess whether immediate prior-hour counts would actually be available in a deployed system.

## Question and fixed budget

How much does forecasting accuracy depend on access to the most recent counts? Compare additional observation delays of **0, 1, 3 and 6 elapsed hours**. At target hour `t`, delay `d` means the latest available pickup count is `y[t − 1 − d]`. This is a controlled retrospective delay sensitivity, not a claim about TLC's actual monthly publication lag or an available live feed.

Use the same three expanding February/March/April validation folds, all 262 zones, unchanged recorded targets and all 559,370 validation rows. Use squared-error histogram boosting at the existing fixed settings in `configs/latency.toml`: **twelve model fits**, one per delay/fold. Fit five availability-safe baselines per setting; their deterministic calculations do not consume a model-search budget. No tuning, new model family, spatial/weather feature, anomaly deletion, thresholding or May evaluation is allowed.

## Availability-safe features

Calendar features and zone identity refer to the actual forecast target `t` for every delay. Rebuild every demand-derived feature according to the following explicit rule; do not shift the completed feature row, which would also shift calendar information.

| Feature | Value at target `t`, delay `d` |
|---|---|
| Recent observation 1/2/3 (existing lag_1/2/3 columns) | `y[t − (1+d)]`, `y[t − (2+d)]`, `y[t − (3+d)]` |
| Target-anchored lag_24 and lag_168 | `y[t − 24]`, `y[t − 168]`, unchanged because all delays are less than 24 hours |
| Rolling mean 3/24/168 | Past window ending at `t − 1 − d`, with all requested observations present |
| Rolling standard deviation 24 | Same delayed trailing 24-hour window, population standard deviation |
| Recent trend | Latest available count minus the preceding available count |

The short-lag names retain the existing model input schema but now describe position in available recent history; record their effective offsets in every run. Keep the long lags anchored to the target's prior day/week: those observations are already available and shifting them would confound availability with a different seasonal feature. Limit this protocol to the four specified delays; longer delays require a revised rule.

Baselines: rename `previous_hour` to `latest_available` for this study; it predicts `y[t − 1 − d]`. Previous-day and previous-week baselines retain their target-anchored lags. The trailing 24-hour mean uses only the delayed window. The historical zone/hour mean uses only the common training targets defined below. Report every baseline in each setting, including unchanged baselines.

## Fair training and scoring coverage

All settings use **174 elapsed hours of warm-up** (168 + maximum delay) and end training **six hours before each validation boundary**, exclusive. Thus the zero-delay control and every delayed variant fit the same target rows, and none uses training labels unavailable under the largest delay. Refit preprocessing and estimator independently for each delay/fold. Training feature rows simulate their own forecast-time availability using the same delay as validation.

Expected training rows: 342,696 for February, 518,760 for March and 713,426 for April. These remove twelve hours per zone from the original backtest training coverage: six extra warm-up hours and six unavailable hours at the end. Validation dates and row counts remain unchanged. Report the interval bounds and assert equal coverage explicitly.

The zero-delay control will have slightly different training data from the original experiment, so exact equality with the September 17 metric is not required. Use this study's matched zero-delay control as the delay effect reference. A zero-delay feature parity test on the common grid must still match the original feature builder exactly.

## Evidence and safeguards

Read development targets with the existing Parquet filter before features are built. Test that changing counts in the unavailable tail `t−d` through `t−1`, the current target, or later rows cannot affect a target's features. Test that changing the latest available count can affect permitted features. Verify delayed rolling boundaries, target-anchored day/week lags, target-time calendars around DST, shared coverage, label availability at each fold's fit time, and zero-delay parity.

Report pooled and per-fold MAE, RMSE, R² and SMAPE for every candidate; absolute/relative MAE changes against the matched zero-delay model; borough and training-defined sparse-zone diagnostics; and daily paired errors for later uncertainty work. Sparse zones use the shared training target mean ≤1 pickup/hour. Store exact effective lags, train/validation bounds, parameters, source/protocol/data/lock hashes and fit times. Keep large predictions outside Git and publish all settings, including negative results.

Do not promote a delayed model or change the original API artifact automatically. The current API remains a zero-delay retrospective prototype. A measured delay sensitivity cannot establish that any assumed live observation feed exists. May remains sealed until the final October model freeze and planned test evaluation.
