# Walk-forward protocol v1 · frozen September 16, 2026

This protocol is committed before executing the real-data comparison. It is a development study, not the final test evaluation. April results were already inspected in the initial experiment; the February and March labels were previously included in training and data-quality review. None of these periods is a fresh untouched test set.

## Question and candidates

Does the initial temporal model improve on legitimate baselines across several chronological periods, and can an alternative boosting loss reduce sparse-zone overprediction without unacceptable errors at busy zones?

The fixed candidates are the five existing baselines (previous hour, previous 24/168 hours, training-only zone/hour mean, trailing 24-hour mean), linear regression, Ridge, and histogram gradient boosting with squared-error, Poisson and absolute-error losses. This is ten candidates, with fifteen total fitted-model runs across three folds; baselines do not consume a model search budget. No hyperparameter search, target rounding, post-hoc zero threshold, feature addition, training reweighting, or date exclusion is allowed in v1.

Poisson loss is a count-compatible alternative with a log link; absolute-error loss tests an objective aligned with MAE and estimates a conditional median rather than a conditional mean. The loss change is an experiment, not an assumption of improvement. See [the estimator documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html). All losses use the same current features, one-hot zone encoding, 120 boosting iterations, learning rate 0.08, 31 maximum leaves, L2 penalty 1.0 and seed 42. Early stopping is disabled to avoid random internal validation. Ridge alpha remains 10 with the existing LSQR solver.

## Fold boundaries

All intervals are half-open and boundaries are `America/New_York` local midnight.

| Fold | Training target interval | Validation target interval |
|---|---|---|
| February | Dec 1, 2025–Feb 1, 2026 | Feb 1–Mar 1, 2026 |
| March | Dec 1, 2025–Mar 1, 2026 | Mar 1–Apr 1, 2026 |
| April | Dec 1, 2025–Apr 1, 2026 | Apr 1–May 1, 2026 |

The initial 168 elapsed hours are feature warm-up. March validation contains 743 real hours because of daylight-saving time. Validation windows do not overlap and every fold refits every estimator and preprocessor using only its training rows. Earlier validation labels may be used in later folds once they are historical. Models stay fixed within each monthly fold; forecasts advance hourly using newly observed prior-hour counts.

Read the processed Parquet with a strict `hour < May 1` filter before feature construction. All zones must have exactly the expected hourly grid and the same forecast targets must be scored by every model. Features retain their strict past-only contract. No gap is needed under the existing assumption that the completed previous hour's counts are available at the next boundary; ingestion latency remains an unverified operational assumption and a later sensitivity experiment.

## Outcomes and reporting

Primary ranking: **pooled MAE across all validation zone-hours**, with each row equally weighted. Recompute pooled RMSE, R² and zero-safe SMAPE from the concatenated out-of-fold predictions; do not average fold RMSE or R². Also report per-fold scores and each fold's best baseline. Comparisons across folds are dependent because their training histories overlap; this run does not assert statistical significance.

For every model and fold, report borough, local-hour, weekday/weekend, rush-hour, and sparse/dense-zone slices. Define sparse zones using the **current fold's training mean <=1 pickup/hour**, never validation averages. Report observed-zero and observed-positive target diagnostics separately; these labels are diagnostic grouping criteria, never features. For zero-demand rows report MAE/mean prediction, the fraction of strictly positive predictions and row counts. Constant-target R² is undefined and must be null. Preserve daily paired MAE summaries for later uncertainty analysis.

Store exact fold boundaries, effective training dates, row counts, parameters, feature list, package lock/source/data/protocol hashes, elapsed fitting times, and immutable metrics. Large out-of-fold prediction tables remain outside Git. The latest development backtest pointer is separate from the current API artifact and the original April experiment.

## Decision and limits

Report the lowest pooled-MAE candidate as the development ranking leader, along with every fold result and sparse-zone tradeoff. Do not automatically promote it or refit a final model. No scores, feature selection, tuning or claims based on May are permitted. Keep original recorded-count labels and all audited anomalous periods; no demand imputation or deletion is introduced.

Interpret the results before a subsequent bounded experiment. Any changed settings require a new protocol version or a clearly documented amendment before its execution. Final model selection will be frozen before the one planned May test evaluation in October.
