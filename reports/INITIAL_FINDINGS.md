# Initial findings · April 2026 validation

This is an initial retrospective experiment, not a final performance claim. Data acquisition, aggregation, fitting and scoring were executed locally against official TLC records. Bootstrap records explicitly state that they ran before the first Git commit. Training now records Git revision state, source-file hashes and the environment lock hash. All eight candidates use the same 188,640 validation zone-hours.

## Model comparison

Histogram gradient boosting achieved MAE **3.480** versus **4.305** for the same elapsed hour one week earlier: a **19.2% MAE reduction**. RMSE declined from 13.014 to 9.700. Linear regression and Ridge achieved 4.148 and 4.151 MAE, respectively. Weekly seasonality was the strongest of the five baselines. The first boosting experiment uses 120 iterations, learning rate 0.08, at most 31 leaves, L2 regularization 1.0, and random seed 42, with random early-stopping validation disabled.

Boosting's SMAPE is **104.05%**, versus **57.40%** for the weekly baseline. This is a material limitation, not a detail to omit: small positive forecasts in zero-demand hours incur 200% SMAPE. Of 73,595 zero-demand validation rows, boosting predicts a positive value on 99.986%, with mean prediction 0.5505; the weekly baseline's mean prediction is 0.3896. The next review should compare sparse-zone behavior and count-aware losses while preserving honest MAE comparisons. Aggregate R² of 0.972 is partly aided by large differences between busy and quiet zones; it is not evidence of equally good forecasting everywhere.

## Where the errors occur

| Borough | April MAE | April R² |
|---|---:|---:|
| Bronx | 0.860 | 0.464 |
| Brooklyn | 1.530 | 0.763 |
| Manhattan | 9.333 | 0.964 |
| Queens | 1.922 | 0.958 |
| Staten Island | 0.241 | -2.201 |

Staten Island has low absolute errors but negative R² and SMAPE near 198.5%, so the model is unsuitable for claiming uniform borough performance. JFK Airport (zone 132) and LaGuardia Airport (138) have the largest zone MAEs, 31.33 and 28.23. Penn Station/Madison Sq West (186) follows at 25.23. Busy Manhattan zones also contribute substantial errors. High-demand targets above the training 99th-percentile threshold of 288 pickups have MAE 43.36; targets with zero or one pickup have MAE 0.60. These are descriptive slices selected using training-based quantile thresholds, not additional model-selection scores.

## Data patterns and caveats

The geographic figures show pickup concentration in Manhattan and the airports. The hourly profiles differ sharply between weekdays and weekends. Daily totals show large winter troughs; weather, outages and holidays remain hypotheses until independently checked. Do not attach causal explanations to these plots.

The six-month audit accepts 23,263,775 of 23,304,288 records. All months contain substantial missing passenger-count data, nonpositive-distance records and negative fares. These fields are audited, but the pickup target does not depend on completed-trip outcomes. Unknown/non-NYC zones and out-of-month pickup timestamps account for exclusions in this data range. No ambiguous or impossible DST pickups remained in the accepted aggregation.

The source has no universal unique trip ID. Duplicate reporting and corrections may inflate counts, and absent records may conceal vendor outages. The initial model treats counts as recorded; sensitivity analysis is a high-priority next task.

## Verification and next decisions

The local API was exercised with 168 real prior hours for zone 237 and an April 8 target. Its prediction matched the offline validation prediction exactly; shortened history was rejected. Automated tests cover feature causality, DST, aggregation conservation, cache integrity, chronological boundaries, metrics and API validation. Unit-test fixtures are artificial and never used as reported observations.

May test labels are excluded from fitting, feature exploration and residual reports. Raw schema/data-quality auditing includes May to validate acquisition, but no May model scores have been computed. Walk-forward validation, block-bootstrap uncertainty, observation-latency sensitivity, spatial predictors, and weather ablations are required before the final October model freeze. No statistical significance or weather benefit is claimed from this first comparison.
