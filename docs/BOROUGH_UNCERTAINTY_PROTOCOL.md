# Paired borough uncertainty — frozen September 24, 2026

Commit this document and [configuration](../configs/borough_uncertainty.toml)
before resampling. The point estimates and slices in [the ablation review](../reports/BOROUGH_REVIEW.md)
have already been seen. This is a fixed follow-up on observed development errors,
not an untouched model-selection experiment. No fitting, serving promotion or
May access. The uncertainty runner has not been implemented or executed yet.

## Inputs and three-contrast family

Use only the hash-pinned `metrics.json` and `daily_mae.csv` from borough run
`20260924T162406Z-c35816`: 712 summaries, 89 NYC dates and eight models, each
covering 559,370 targets. Use no trip/forecast Parquet or model binaries.

Exactly three absolute-MAE contrasts form the family: indicators minus temporal
control, indicators-plus-peer-lags minus temporal, and peer bundle minus static
indicators. Keep all three regardless of interval direction. This separates
overall feature-bundle changes from the incremental peer-demand change. Negative
differences favor the candidate. Relative reductions are descriptive with
marginal intervals only. No subgroup, RMSE, weekly or XGBoost contrast is added.

## Fixed sampling and intervals

Reuse the existing tested fold-stratified circular-day bootstrap: wrap fixed-size
blocks within each February/March/April fold, trim to the original fold day count,
and share sampled dates across every model. Preserve actual weights, including
March 8's 6,026 rows/model versus 6,288 on ordinary days. Pool sampled error totals
and rows rather than averaging daily means without weights. Do not refit models
or alter the study's 174-hour warm-up, six-hour embargo or zero-delay assumptions.

Use 10,000 replicates each for seven-day primary and one-/fourteen-day sensitivity
blocks; `default_rng(SeedSequence([42, block_days]))`. No adaptive block, seed,
replicate or contrast selection. Reuse one paired draw matrix per setting.

Publish marginal 95% percentile intervals for absolute MAE difference and relative
reduction, with linear quantile interpolation. Also publish three-contrast
Bonferroni-adjusted absolute-difference intervals: nominal family confidence 95%,
per-contrast confidence `1 - 0.05/3` (98.333333…%), quantiles `0.05/(2*3)` and
`1 - 0.05/(2*3)` (0.833333…th / 99.166666…th percentiles). Derive the family size
from the validated contrasts and compare it to the configuration. The primary
interpretation uses adjusted absolute intervals. Do not adjust only a winner.

Each sensitivity repeats the same family but makes no joint coverage claim
across block lengths, nor across absolute and relative statistics. Publish all
nine comparison rows with exact endpoints, nominal levels, roles, method and
source/protocol/lock hashes; keep draw arrays ignored. Use separate
`reports/borough_uncertainty/` and `reports/latest_borough_uncertainty.json` outputs.

## Validation and limits

Require exact hashes and run identity, complete unique date/fold/model keys,
finite nonnegative errors, equal model row counts with DST, pre-May chronological
folds, and source fold/pooled MAEs reconciled from weighted daily errors. Reject
missing or extra days/models instead of dropping them. Recheck protocol and
inputs after sampling; preserve all previous evidence and serving files.

Validate the family arithmetic, output quantiles and deterministic draws. Reproduce
all outputs in an isolated directory using only tracked source/config/lock and
the two published input files in the same environment. No fit or target read is
needed. Rendering and verification must not rerun the six-fit ablation.

The approximate intervals are conditional on fixed models and the observed
months. Short 28–31-day strata, artificial wraparound and omitted cross-month
dependence limit coverage. Bonferroni allocation does not repair bootstrap
miscalibration, account for the full history of development selection, or imply
future superiority. Preserve the sparse/zero-demand harm regardless of the result.
The method and its limitations follow the [earlier uncertainty protocol](XGBOOST_UNCERTAINTY_PROTOCOL.md),
with a declared three-contrast family replacing the prior two-contrast family.

After this bounded analysis, move to authoritative NOAA hourly weather acquisition
and availability auditing before any weather-model protocol. Do not expand the
borough fit budget or open May to resolve uncertainty.
