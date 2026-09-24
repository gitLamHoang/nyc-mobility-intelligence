# Borough spatial ablation — frozen September 23, 2026 (Los Angeles)

Commit this protocol before fitting. The preparation stage has built and audited
features but has fitted **zero** models. This document and
[configs/borough_spatial.toml](../configs/borough_spatial.toml) define the next
milestone; the comparison runner is not implemented yet.

## Question and six-fit budget

Does grouping zones by borough, then adding recent demand from other zones in the
same borough, improve the fixed temporal histogram-boosting model? Compare two
bundles, each retaining every original temporal/zone input:

1. `borough_static`: five borough indicator columns from the official lookup.
2. `borough_context`: the five indicators plus mean other-zone borough demand at
   elapsed-hour lags 1 and 24.

Exactly **two bundles × three folds = six fits**. No new tuning, seeds, losses,
early stopping, graph thresholds, candidate selection or budget expansion after
seeing scores. Zone identity already implies borough membership, so indicators
add a representation rather than new raw information; improvement is uncertain.
The context-minus-static contrast describes the incremental change from the two
lagged aggregates. Report both candidates versus the temporal control regardless
of direction. No automatic serving promotion.

## Availability and coverage

Use the hash-pinned TLC lookup whose recorded HTTP Last-Modified timestamp is
February 22, 2024. Treat that timestamp as the declared availability evidence;
it is not an independently archived 2024 download. Borough labels are fixed for
the complete development window. Reject lookup mismatch, missing/duplicate
zone-hours, inconsistent borough labels, or any shorter peer history. No missing
zone becomes a zero. All 262 NYC zones participate, with no Newark/unknown IDs.

For zone z in borough b with n zones, a peer feature at lag k is
`(sum(y[j, t-k] for j in b) - y[z, t-k]) / (n-1)`.
The focal zone is excluded. Every actual borough has at least 20 zones. The
builder's explicit singleton convention is zero with peer count zero; a leading
unobserved lag remains missing. `borough_other_count` is diagnostic only, not a
model input. There are no contemporaneous counts, target encodings or future
aggregates. No rolling selection of neighbors. The established temporal columns
must remain exactly identical.

At target t, only counts through t−1 are assumed available. This is retrospective
one-step evaluation; TLC monthly publications are not a live feed. The builder
also tests 1/3/6-hour delays, but this study fits only zero delay. Peer lag 1 shifts
by 1+delay; lag 24 retains its elapsed-hour anchor because it is already available.

## Historical geometry decision

The [geometry review](../reports/SPATIAL_PREPARATION_REVIEW.md) found that the
current unique-ID shapefile carries February 2026 timestamps, after the training
origin. The older NYC Open Data release reports June 2025 publication but has
duplicate IDs 56/103 and missing IDs 57/104/105. Historical polygon-to-pickup-ID
correspondence is unresolved. Do not guess a remapping from row order, names,
OBJECTID, or proximity. **Adjacency, area and centroid features are ineligible for
this complete-window study.** A later verified historical mapping would require
its own precommitted experiment. The 604-edge current graph is audit evidence.

## Matched estimator and controls

Retain histogram gradient boosting with squared-error loss, 120 iterations,
learning rate 0.08, 31 maximum leaves, L2=1, 255 bins, seed 42, and early stopping
disabled. Preserve the existing dense zone one-hot encoder, unscaled numeric
passthrough and output dtype behavior. Append only the declared five or seven
numeric columns; no scaler, ordinal zone rank, categorical recoding or other
model changes. Fit a new preprocessor and estimator per fold, using training
only. Clip negative predictions to zero as in the control. Record all resolved
estimator parameters, actual transformed dtypes and column order, versions,
source/config/lock hashes and fit/predict times.

Reuse zero-delay controls from latency `20260921T021023Z-588968`, including all
five baselines and histogram boosting. Pin the canonical panel, control metrics,
three prediction tables, lookup and feature source hashes as in the TOML. Before
any fit, verify control scores against saved predictions, exact training label
signatures/bounds, validation keys/labels, full zone/hour coverage, and the
training-defined sparse cohorts. Fail on any mismatch; never silently regenerate
controls. The unchanged ignored control files remain a fresh-checkout prerequisite.

Training expands from December 1, 2025; February, March and April 2026 are the
three validation months, using NYC local midnights. Keep the **174-hour warm-up**
and **six-hour training-label embargo** from the control, even at zero delay.
Expected training rows: 342,696 / 518,760 / 713,426; validation rows:
176,064 / 194,666 / 188,640, totaling **559,370**. March has 743 elapsed hours.
Filter out May at the Parquet read before feature construction. Retain the same
complete 262-zone frame when aggregating peers and then selecting training or
validation targets. No May metrics or fitting; serving files stay unchanged.

## Reporting and limitations

Primary metric is pooled MAE over all common targets. Also publish monthly MAE,
RMSE, R², SMAPE, borough/calendar slices, zero/positive targets, and train-defined
sparse/dense zones (sparse mean ≤1 pickup/hour). Save all predictions outside Git
and 89 daily error summaries per model for future paired analysis. Verify daily
weighted MAE reconciliation and exact shared targets. Report incremental
context-versus-static MAE as descriptive evidence, without claiming significance.

These months have been used repeatedly during development. No test score or
future-performance claim follows from a small observed gain. Any subsequent
uncertainty analysis or additional modeling needs its own frozen protocol.
Polynomial/graph/weather interactions, XGBoost feature comparisons and a new
serving API contract are outside this six-fit budget.
