# Changelog

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
