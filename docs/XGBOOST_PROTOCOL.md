# XGBoost temporal comparison — frozen September 21, 2026 (Los Angeles)

This protocol is committed before installing XGBoost or fitting any candidate.
The executable budget is [configs/xgboost.toml](../configs/xgboost.toml).

## Question and bounded budget

Can a second boosted-tree implementation improve the established temporal model
without adding predictors? Prior walk-forward evidence favors squared-error
histogram boosting over linear models and its alternate losses. Test XGBoost
with maximum depths **4 and 6**, covering shallower and moderately deeper trees,
while holding the learning rate (0.08), tree count (120), L2 penalty (1), and
histogram bins (255) close to the established control. Different algorithms and
tree shapes mean these are not equivalent capacities. This is a bounded model
comparison, not an isolated causal test of depth or algorithm.

Exactly **two candidates × three folds = six fits**. No random/grid search,
additional objectives, seed search, early stopping, validation-driven tree
selection, or budget expansion after inspecting results. Fresh estimator and
preprocessor in every fold. XGBoost **3.4.1** is the released PyPI version checked
before this freeze; pin it and retain the existing locked dependencies.

## Matched data and availability

Use the zero-hour-delay control from latency run `20260921T021023Z-588968`.
Training expands from December 1, 2025; validation is February, March, and April
2026 in New York local dates. Keep its common **174-hour warm-up** and **six-hour
training embargo**, all 262 zones, unchanged observed pickup labels, and identical
validation targets. This is distinct from the original 168-hour backtest; compare
against the matched latency control rather than mixing training windows.

At target boundary t, the latest observed hour is y[t−1]. Lags, rolling windows
and calendar features retain the latency study's zero-delay semantics. The fit
never receives a validation evaluation set. Validation history advances using
completed observed hours. This is retrospective one-step evaluation conditional
on immediately available counts, not a claim that monthly TLC files are a live
feed. May stays sealed: push down the `< May 1 00:00 America/New_York` filter before
feature construction. No May metrics, fitting, or promotion.

Reuse saved zero-delay predictions for all five baselines and histogram boosting;
do not refit the twelve latency models. Pin the canonical panel, control metrics,
and three prediction file SHA-256 hashes in the TOML. Before any candidate fit,
verify those hashes, training target signatures and bounds, validation keys and
labels, and training-defined sparse cohorts. Require exact dense zone/hour
coverage, no overlap, and control metrics consistent with saved predictions.
Fail rather than silently regenerate or substitute controls. A fresh checkout
must restore these ignored artifacts from the documented source run before this
comparison; the reproducibility limitation must be explicit in its report.

## Representation and estimator

Use the existing 18 temporal/zone inputs: dense one-hot zone identity fitted on
training only, numeric features unchanged, dense float32 matrix. Real zeros stay
zeros; NaN is the missing marker, and incomplete warm-up rows are removed.
No target encoding, geographic variables, weather, or numeric zone rank.

Use CPU `hist`, `gbtree`, `depthwise`, `reg:squarederror`; the TOML fixes tree count,
learning rate, depth choices, histogram bins, regularization, row/column sampling,
seed and four threads. No early stopping. Clip negative predictions to zero as in
previous studies. Retain XGBoost's training-derived default base score. Save
resolved parameters, dependency versions, source/lock/config hashes, elapsed fit
and prediction times, and ignored out-of-fold predictions. Serving files remain
unchanged.

## Reporting and decision

Primary metric: MAE recomputed over all **559,370** common validation targets.
Also report fold MAE, pooled/fold RMSE, R² and SMAPE, plus existing borough,
hour, weekend/rush-hour, training-defined sparse/dense and zero/positive slices.
Sparse means training average ≤1 pickup/hour; report the known sparse-zone
weakness against the weekly baseline. Save 89 daily error aggregates per model
for later paired uncertainty without extra fitting.

Report every candidate, even if worse; no automatic serving promotion. An observed
leader is only a development candidate: repeated use of these folds and selecting
among two settings introduces selection optimism. Existing uncertainty intervals
for other comparisons do not transfer. Any subsequent uncertainty, latency,
feature ablation or tuning study needs its own precommitted protocol. Do not
interpret a small unquantified gain as established superiority.

## Official references checked before implementation

- [Installation and CPU package](https://xgboost.readthedocs.io/en/stable/install.html)
- [Parameters](https://xgboost.readthedocs.io/en/stable/parameter.html)
- [Sparse versus dense and missing values](https://xgboost.readthedocs.io/en/stable/faq.html)
- [PyPI release metadata](https://pypi.org/pypi/xgboost/3.4.1/json)

Use the normal macOS wheel and CPU-only Linux/Windows wheel to keep CPU CI small.
The exact resolved wheel hashes belong in `uv.lock`.
