# Paired uncertainty protocol v1 · September 19, 2026

Freeze this document and `configs/uncertainty.toml` in Git before executing the resampling analysis. The September 17 point estimates and model ranking have already been examined. This is a planned analysis of existing development errors, not a prospective model-selection experiment or an untouched test evaluation.

## Inputs and estimand

Use only the immutable `metrics.json` and `daily_mae.csv` from backtest `20260917T165035Z-e037f0`, with their SHA-256 values fixed in the configuration. There are 89 NYC dates, ten models and 559,370 validation zone-hours across February, March and April. Do not refit models or read trip records, forecast Parquet files or May labels.

For each candidate/reference pair, estimate the difference in pooled MAE, **candidate minus reference** (negative favors the candidate), plus the relative MAE reduction, **100 × (1 − candidate/reference)** (positive favors the candidate). Pooled MAE is the sum of daily absolute errors divided by the sum of daily row counts. Recover daily absolute-error totals as saved daily MAE × rows. Keep the 23-hour March 8 day at its actual row weight. Never give short and ordinary days equal weight when calculating the zone-hour estimand.

The three fixed comparisons are squared-error boosting versus the weekly baseline, Poisson versus squared-error boosting, and absolute-error versus squared-error boosting. No extra contrasts, subgroup intervals or new candidate selection are part of v1. Report all three without choosing whichever looks most favorable.

## Resampling

Use a fold-stratified **circular block bootstrap of whole NYC days**. For each replicate and each monthly fold, draw starting dates uniformly with replacement, append fixed-length consecutive day blocks modulo that fold's number of days, then truncate to the original fold's day count. Blocks may wrap from a month's end to its beginning; they never cross folds. Use the same sampled indices and counts for every model, preserving paired errors and within-day dependence across all zones and hours. Sample the monthly strata independently and concatenate their sampled error totals/counts before computing pooled MAE.

Primary block length: **7 days**, motivated by weekly demand dependence rather than selected from results. Fixed sensitivities: **1 day** and **14 days**. One-day resampling retains within-day spatial/hourly dependence but drops between-day dependence; it is a diagnostic comparator, not the primary method. Fourteen-day blocks probe sensitivity to longer dependence but have very few effective blocks in a month. Longer blocks need not produce wider intervals in a short empirical sample.

Generate **10,000 replicates per block length**, NumPy `default_rng(SeedSequence([42, block_days]))`. Use identical draws for all comparisons within a block setting. Report the point estimate and the **2.5th/97.5th percentiles**, using NumPy's linear quantile interpolation, for both statistics. The implementation uses NumPy already in the lockfile; no extra bootstrap dependency is needed. Save the draw arrays outside Git and publish compact summaries and input/source/protocol/lock hashes.

## Validation and interpretation

Before resampling, require unique fold/date/model keys, complete expected NYC dates for every model, exact zone-hour row counts (including DST), finite nonnegative MAEs, and agreement between row-weighted daily MAEs and saved pooled/fold MAEs within numerical tolerance. Reject changed input hashes and any fold ending after the sealed test boundary. An absent day/model or an extra held-out date is an error, not silently dropped data.

The nominal 95% percentile intervals describe sensitivity to resampling these development days with fixed fitted models and fixed month composition. They are not prediction intervals, probabilities that a model is best, or coverage guarantees for future months. They do not capture model-training uncertainty, selection bias, new seasons, data revisions or acquisition latency. Independent monthly resampling also omits dependence across fold boundaries. Circular wrapping creates artificial end-to-start adjacency and assumes roughly comparable error behavior within each monthly stratum. Only 28–31 days are available per fold; report these limitations alongside every substantive conclusion.

These are three marginal comparisons, without simultaneous-coverage or multiple-testing correction. Do not turn exclusion of zero into an unqualified significance claim. May remains sealed, serving artifacts stay unchanged, and no automated model promotion is permitted.

Method references: [arch's time-series bootstrap documentation](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html) defines fixed-length circular blocks; [Forecasting: Principles and Practice](https://otexts.com/fpp3/bootstrap.html) explains why temporal dependence motivates block resampling. Their general guidance motivates this protocol; neither validates coverage for this particular taxi experiment.
