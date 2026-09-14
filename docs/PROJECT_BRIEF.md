You are responsible for creating, building, maintaining, and continuously improving a serious end-to-end data science portfolio project for me.

Do not ask me to choose technologies, repository names, datasets, models, schedules, architecture, or implementation details unless proceeding is genuinely impossible.

Make reasonable senior-engineer decisions yourself.

==================================================
0. FIXED PROJECT CONFIGURATION
==============================

GitHub repository name:

nyc-mobility-intelligence

Repository visibility:

PUBLIC

Repository description:

End-to-end NYC taxi demand forecasting using real trip, geospatial, temporal, and weather data.

Primary language:

Python

Project duration:

September 14, 2026 through October 13, 2026.

Primary development branch:

main

Create the repository automatically if it does not already exist.

If GitHub CLI is authenticated, use an appropriate command such as:

gh repo create nyc-mobility-intelligence
--public
--description "End-to-end NYC taxi demand forecasting using real trip, geospatial, temporal, and weather data."
--clone

If the repository already exists, clone or open it instead.

Never create a second repository with a different name.

Never ask me what repository to use.

==================================================

1. PROJECT OBJECTIVE
   ==================================================

Build NYC Mobility Intelligence.

This must become a serious data science portfolio project, not a tutorial, toy Kaggle notebook, or collection of disconnected scripts.

The central problem is:

Predict short-term taxi pickup demand across New York City Taxi Zones.

The primary prediction task is:

For every NYC Taxi Zone and hourly time interval, predict taxi pickup demand one hour into the future.

Conceptually:

Given the location, recent taxi activity, historical patterns, calendar information, spatial context, and eventually weather, predict where transportation demand will be highest in NYC during the next hour.

The final repository should demonstrate competence in:

* real-world data acquisition
* large tabular datasets
* data cleaning
* exploratory data analysis
* feature engineering
* time-series forecasting
* geospatial analysis
* machine learning
* leakage prevention
* temporal validation
* model comparison
* hyperparameter optimization
* error analysis
* interpretability
* statistical reasoning
* experiment tracking
* Python software engineering
* testing
* visualization
* API development
* deployment-oriented design
* reproducibility
* Git/GitHub workflow
* technical communication

==================================================
2. REAL DATA ONLY
=================

Use official or reputable real public data.

PRIMARY DATA

Use official NYC Taxi & Limousine Commission Trip Record Data.

Prefer official TLC-hosted Parquet files rather than Kaggle copies.

Use real trip records containing fields such as:

* pickup timestamp
* dropoff timestamp
* pickup Taxi Zone
* dropoff Taxi Zone
* passenger count
* trip distance
* fare information
* payment information

GEOGRAPHIC DATA

Use official NYC Taxi Zone data:

* Taxi Zone lookup table
* Taxi Zone shapefile/geographic boundaries

WEATHER DATA

Later integrate reputable historical NYC weather observations, preferably NOAA or another authoritative source.

Possible variables:

* temperature
* precipitation
* snowfall
* wind
* visibility
* weather conditions

Never fabricate observations.

Never fabricate model metrics.

Never create synthetic results and present them as real.

==================================================
3. INITIAL DATA RANGE
=====================

Start with approximately six months of NYC taxi data.

Choose a recent complete six-month period for which official TLC files are available and stable.

Document the exact months used.

Do not immediately download many years.

The initial dataset should still contain millions of real trips.

Once the pipeline is efficient and stable, expanding the history is allowed if it meaningfully improves the project.

Never commit raw multi-GB datasets to GitHub.

Instead implement reproducible acquisition.

For example:

python scripts/download_data.py --start YYYY-MM --end YYYY-MM

Prefer Parquet.

Use caching.

Avoid unnecessary repeated downloads.

==================================================
4. REPOSITORY STRUCTURE
=======================

Create a professional but restrained architecture.

Use approximately:

nyc-mobility-intelligence/
│
├── README.md
├── PROJECT_STATE.md
├── ROADMAP.md
├── CHANGELOG.md
├── pyproject.toml
├── .gitignore
│
├── configs/
│
├── data/
│   └── README.md
│
├── notebooks/
│
├── reports/
│   └── figures/
│
├── scripts/
│
├── src/
│   └── nyc_mobility/
│       ├── data/
│       ├── features/
│       ├── models/
│       ├── evaluation/
│       ├── visualization/
│       └── api/
│
└── tests/

Modify this structure if strong engineering reasons justify it.

Do not create empty complexity.

==================================================
5. BUILD STRATEGY
=================

Build vertically.

A complete simple system is better than several unfinished advanced systems.

Develop approximately through this sequence:

PHASE 1
Repository initialization and data acquisition

PHASE 2
Schema validation and data-quality analysis

PHASE 3
Hourly Taxi Zone demand aggregation

PHASE 4
Exploratory data analysis

PHASE 5
Naive forecasting baselines

PHASE 6
Leakage-safe temporal features

PHASE 7
Classical ML models

PHASE 8
Chronological / walk-forward validation

PHASE 9
Model comparison and tuning

PHASE 10
Detailed error analysis

PHASE 11
Geospatial features and analysis

PHASE 12
Historical weather integration

PHASE 13
Model interpretation

PHASE 14
Experiment tracking

PHASE 15
Prediction API

PHASE 16
Interactive demand visualization

PHASE 17
Monitoring / drift analysis

PHASE 18
Final cleanup, reproducibility, and portfolio presentation

Do not blindly follow the sequence when evidence suggests another task has higher priority.

==================================================
6. BASELINES FIRST
==================

Before sophisticated machine learning, establish legitimate baselines.

Implement useful baselines such as:

* previous-hour demand
* same hour previous day
* same hour previous week
* historical zone/hour average
* rolling historical mean

Record actual validation performance.

Every sophisticated model must be compared against these baselines.

==================================================
7. FEATURE ENGINEERING
======================

Potential temporal features:

* hour
* day of week
* weekend
* month
* holiday
* rush-hour indicator
* cyclic hour encoding
* cyclic weekday encoding

Potential historical features:

* lag 1 hour
* lag 2 hours
* lag 3 hours
* lag 24 hours
* lag 168 hours
* rolling means
* rolling standard deviations
* recent trend
* demand momentum

Potential spatial features:

* Taxi Zone
* borough
* neighboring-zone demand
* borough-level demand
* spatial lag features

Potential weather features:

* temperature
* precipitation
* snowfall
* wind
* weather category

CRITICAL:

Every feature must contain only information available at prediction time.

Explicitly test leakage-sensitive transformations.

==================================================
8. MODELING
===========

Model progression should approximately be:

1. Naive baselines
2. Linear regression
3. Ridge / regularized regression
4. Random Forest if appropriate
5. Gradient boosting
6. XGBoost
7. LightGBM or CatBoost if justified

Do not use neural networks initially.

Deep learning is allowed only if:

* the classical pipeline is mature
* baselines are strong
* evaluation is rigorous
* sufficient data exists
* there is a defensible reason to expect benefit

Do not add deep learning merely for prestige.

==================================================
9. TEMPORAL VALIDATION
======================

This is forecasting data.

Never use naive random train/test splitting if it allows future information into training.

Use chronological partitions.

Maintain conceptually separate:

TRAIN

VALIDATION

TEST

Record exact time periods.

Do not repeatedly optimize against the test set.

When appropriate, implement:

walk-forward validation

or

rolling-window validation.

==================================================
10. METRICS
===========

Use appropriate metrics such as:

MAE

RMSE

R²

SMAPE where appropriate

Avoid blindly relying on MAPE when demand can approach zero.

Analyze errors by:

* Taxi Zone
* borough
* hour
* weekday/weekend
* demand quantile
* rush hour
* weather condition
* geography

A model is not considered understood merely because one aggregate metric is good.

==================================================
11. DATA ENGINEERING
====================

Create reproducible data acquisition and preprocessing.

Document:

* source
* exact files
* date range
* schema
* storage format
* expected disk usage
* preprocessing
* geographic joins
* weather joins
* attribution/license when applicable

Raw datasets belong outside Git.

Use .gitignore.

Use Parquet for large processed tables.

Consider DuckDB or Polars when they materially improve processing efficiency.

Do not introduce technology merely because it sounds sophisticated.

==================================================
12. EXPLORATORY ANALYSIS
========================

Investigate real patterns.

Examples:

* demand by hour
* demand by weekday
* weekday vs weekend
* busiest Taxi Zones
* borough differences
* temporal seasonality
* anomalous demand spikes
* missing values
* outliers
* distribution of demand
* geographic clustering
* long-term trends

Produce useful figures.

Do not generate decorative charts with no analytical purpose.

==================================================
13. GEOSPATIAL COMPONENT
========================

The project must contain a meaningful geospatial component.

Use actual NYC Taxi Zone geometries.

Eventually investigate:

* pickup-demand maps
* forecast maps
* residual maps
* zone-level model errors
* borough-level behavior
* neighboring-zone relationships
* high-demand clusters

Use GeoPandas or an appropriate alternative.

==================================================
14. WEATHER COMPONENT
=====================

Integrate weather only after the basic forecasting system works.

Use reputable historical observations.

Join weather according to correct timestamp and timezone behavior.

Explicitly measure whether weather improves forecasting.

If weather does not improve performance, report that honestly.

Negative results are legitimate results.

==================================================
15. EXPERIMENT TRACKING
=======================

Track meaningful experiments.

For each important experiment record:

* experiment ID
* date
* dataset range
* feature set
* model
* hyperparameters
* train period
* validation period
* test period when applicable
* validation metrics
* test metrics when legitimately evaluated
* notes
* conclusion

Start with lightweight tracking such as:

CSV
JSON
SQLite
or structured Markdown.

Introduce MLflow only if project maturity warrants it.

==================================================
16. INTERPRETABILITY
====================

After establishing a strong model, explain it.

Possible tools:

* permutation importance
* model-native feature importance
* partial dependence
* SHAP

Answer questions such as:

* How important is recent demand?
* How strong is weekly seasonality?
* Which temporal features matter most?
* Does rain affect predictions?
* What causes the largest errors?
* Which NYC zones are hardest to forecast?

==================================================
17. TESTING
===========

Maintain real automated tests.

Test important behavior including:

* schema validation
* timestamps
* timezone conversion
* hourly aggregation
* Taxi Zone IDs
* temporal splits
* lag generation
* rolling features
* leakage protection
* missing values
* model input shape
* model output shape
* metric calculations

Use pytest.

Before substantive commits:

run relevant tests

run linting

execute the changed pipeline component.

Never knowingly commit broken code.

==================================================
18. CODE QUALITY
================

Write maintainable Python.

Prefer:

* focused functions
* meaningful names
* reusable modules
* useful type hints
* centralized configuration
* minimal duplication
* clear interfaces
* reproducible CLI commands

Use Ruff or equivalent linting.

Keep dependencies disciplined.

=========
