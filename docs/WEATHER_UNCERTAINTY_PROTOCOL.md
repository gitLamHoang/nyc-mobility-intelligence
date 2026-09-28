# Paired weather uncertainty protocol

Freeze date: September 28, 2026. Execute only after this document and its populated configuration are committed. No bootstrap has been run under this protocol.

Use only the published daily/model absolute-error summaries from the frozen six-fit weather comparison. Pin its metrics JSON and daily CSV by hash in `configs/weather_uncertainty.toml`. Do not fit models, load taxi targets, select weather quality rules or evaluate May.

The family contains exactly two candidate-minus-reference absolute-MAE contrasts: `weather_3h` versus `hist_gradient_boosting`, and `weather_6h` versus `hist_gradient_boosting`. Keep three hours as the primary candidate and six hours as its declared delay sensitivity regardless of their observed ranking. The direct three-versus-six difference remains descriptive and outside this inferential family.

Use the existing fold-stratified paired circular-day bootstrap with actual zone-hour row weights. Resample the same days for all eight models within each February/March/April fold. Preserve 89 local dates, including March 8's 23 hours, and 559,370 validation targets per model. Reject missing/duplicate dates, altered folds, inconsistent row counts and input mutation.

Run 10,000 paired replicates with seed 42 at a primary seven-day block length; publish one- and fourteen-day block sensitivities using the same seed. Allocate nominal family error 0.05 across the two absolute-MAE contrasts using Bonferroni: 97.5% per-contrast intervals with tails 0.0125 and 0.9875. Use linear empirical quantiles. Relative-MAE reduction intervals remain marginal 95% (tails 0.025 and 0.975), explicitly separate from family-adjusted absolute intervals. Publish every contrast at every block length, with exact parameters and input/source/lock hashes, plus ignored paired draw arrays.

Reconcile daily weighted MAE with the published pooled points before sampling. Independently verify percentile arithmetic and reproduce results from tracked summaries in an isolated directory. Preserve all model/data/evidence artifacts and keep May metrics null.

These approximate intervals condition on the observed development period, the frozen weather bundle, source-quality policy and hypothetical observation delays. They do not repair unverified historical publication/revision availability, prove causality, account for the entire sequence of earlier model selection, or guarantee future results. The unknown source-quality semantics and March/April source transition remain limitations. Report sparse/zero-target and RMSE tradeoffs beside aggregate intervals. No serving promotion or expanded tuning follows automatically from interval direction.
