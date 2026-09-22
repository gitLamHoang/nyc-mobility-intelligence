# Paired XGBoost uncertainty · frozen September 22, 2026

Commit this document and [configuration](../configs/xgboost_uncertainty.toml)
before resampling. The two candidates' point estimates have already been seen;
this is a planned analysis of existing development errors, not an untouched
selection experiment. May remains sealed and no model promotion is permitted.

## Question, inputs and fixed family

How sensitive are the observed XGBoost MAE differences to resampling development
days? Use only the hash-pinned `metrics.json` and `daily_mae.csv` from XGBoost run
`20260922T032057Z-3ecc9d`. These tracked files contain 712 daily/model summaries
(89 NYC dates × eight models), with 559,370 zone-hour targets per model. No trip
records, target/forecast Parquet, serving artifacts or model binaries are needed.
Do not refit models or reconstruct ignored control predictions.

Exactly two contrasts: depth 4 minus histogram control and depth 6 minus histogram
control. Keep both, including the worse candidate. The primary family contains
these **two pooled MAE differences** at the seven-day block setting. Negative
candidate-minus-reference values favor XGBoost. Relative MAE reduction is
100 × (1 − candidate/reference); it is descriptive, with marginal intervals only.
No weekly, subgroup, RMSE or extra model contrasts belong to this study.

## Sampling and intervals

Reuse the existing tested fold-stratified circular-day bootstrap. Independently
resample whole NYC days within each February/March/April fold using fixed-length
wrapping blocks, trim to each fold's original number of days, and use the same
indices for every model. Pool sampled absolute-error totals and actual row counts,
not unweighted daily means. March 8 contributes 6,026 rows/model (23 × 262), while
ordinary days contribute 6,288. Keep the original 174-hour warm-up, six-hour
training embargo and zero-delay observation contract implicit in the saved errors.

Use **10,000 replicates** each for **7 days (primary)** and **1/14 days (fixed
sensitivities)**, NumPy `default_rng(SeedSequence([42, block_days]))`. Never choose
block length, seed or replicate count based on the resulting intervals. No new
sampling dependency. Reuse one draw matrix per block setting for every statistic.

Report both contrasts' marginal 95% percentile intervals for the absolute MAE
difference and relative reduction (2.5th/97.5th percentiles, linear interpolation).
For the two **absolute-difference** contrasts, also report Bonferroni-adjusted
percentile intervals: nominal family confidence 95%, individual confidence
1 − 0.05/2 = **97.5%**, with **1.25th/98.75th percentiles**. Derive the family size
from the validated two contrasts and check it against the configuration. Do not
apply the correction only to the selected winner. The primary decision uses these
adjusted absolute-difference intervals, not the narrower marginal intervals.

Each sensitivity setting repeats the same two-contrast adjustment but remains a
diagnostic; there is no joint coverage claim across the three block settings.
Relative intervals have no family adjustment, and no joint coverage claim is
made across absolute and relative statistics. Report endpoint/point estimates,
nominal levels, family size, quantile method, block role and all six comparison
rows. Keep draw arrays ignored; publish compact evidence and a figure.

## Validation and limitations

Before sampling, require pinned hashes/identifier, nonempty complete daily
coverage, unique date/fold/model keys, finite nonnegative errors, equal model row
counts with DST, chronological folds entirely before the sealed test boundary,
and exact row-weighted reconciliation with source fold/pooled MAEs within the
existing numerical tolerances. Reject missing/extra days or models; do not drop
them. Verify the protocol/inputs remain unchanged during sampling. Keep previous
uncertainty reports and all data/serving artifacts unchanged; use separate
`reports/xgboost_uncertainty/` and `reports/latest_xgboost_uncertainty.json` outputs.

Bonferroni's union-bound rationale allocates the nominal error budget across the
two chosen contrasts. It does **not** fix miscalibrated individual bootstrap
intervals. These short monthly strata contain only 28–31 days, wrapping imposes
artificial end-to-start adjacency, and independent folds omit cross-month
correlation. Nominal family coverage is conditional on the adequacy of the
bootstrap approximation, fixed fitted models and fixed month composition; do
not claim exact 95% coverage or a probability that a model is best.

The adjustment addresses these two candidate contrasts only. It does not account
for prior loss/model comparisons, repeated development inspection, training
uncertainty, later tuning, new seasons, data revisions or operational latency.
Do not label exclusion of zero as unqualified significance or guaranteed future
improvement. Preserve the previously observed RMSE and sparse-demand tradeoffs
regardless of the interval result. Do not use May to resolve uncertainty.

After this bounded analysis, proceed to a precommitted spatial-feature ablation
rather than increasing the XGBoost search budget. Select no new experiment based
solely on whichever sensitivity interval looks most favorable.

## Method references

- [NIST Bonferroni method](https://itl.nist.gov/div898/handbook/prc/section4/prc473.htm):
  the general inequality motivates dividing alpha by the number of contrasts;
  this project applies that error allocation to approximate bootstrap intervals,
  not NIST's ANOVA t-interval example.
- [arch time-series bootstraps](https://arch.readthedocs.io/en/stable/bootstrap/timeseries-bootstraps.html):
  defines fixed-length circular blocks and end-to-start wrapping.

Neither source validates coverage for this particular taxi experiment.
