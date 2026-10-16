# Reproduce the pipeline and research studies

[Project overview](../README.md) · [Browser demo setup](EXPLORER.md)

The browser demo runs from committed data. The Python pipeline needs the data and artifact prerequisites below. Each study keeps its original frozen protocol.

## Initial pipeline

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git, then:

```bash
git clone https://github.com/gitLamHoang/nyc-mobility-intelligence.git
cd nyc-mobility-intelligence
# macOS only: install the XGBoost OpenMP runtime
# brew install libomp
uv sync --frozen --python 3.12
uv run python scripts/download_data.py --start 2025-12 --end 2026-05
uv run nyc-mobility prepare
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility train
uv run nyc-mobility report
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`uv run nyc-mobility all` executes the four pipeline stages. Downloads are cached and verified with SHA-256. Reserve about 2 GB disk for raw data, aggregates, predictions and model artifacts, plus environment space; training can use several GB of RAM. No raw trip files, processed Parquet, or model pickle files are committed. The exact dependency graph is in `uv.lock`.

Run `uv run nyc-mobility audit-quality` after preparation for an optional development-only exact-duplicate and reporting-volume audit. It verifies source hashes and compares an alternate count policy without changing the canonical target or model. The [September 14 review](../reports/DATA_QUALITY_REVIEW.md) found no exact duplicates in 19.18 million eligible December–April pickups; it documents reporting anomalies and why they are retained.

Run the separate development backtest after preparation:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility backtest
# Use the backtest ID printed by the preceding command:
uv run python scripts/plot_backtest.py reports/backtests/<backtest-id>
```

The [frozen protocol](WALK_FORWARD_PROTOCOL.md) compares ten candidates across February, March and April, refitting each pipeline on expanding historical training data. It saves immutable scores and daily errors under `reports/backtests/`, and ignored forecast tables under `artifacts/backtests/`. It leaves the existing API artifact and April experiment unchanged. The `all` command retains its original four stages; it does not launch the backtest.

Reproduce the paired uncertainty analysis from the published daily summaries without downloading data or fitting models:

```bash
uv run nyc-mobility uncertainty
uv run python scripts/plot_uncertainty.py reports/uncertainty/<uncertainty-id>
```

The [uncertainty protocol](UNCERTAINTY_PROTOCOL.md) pins the original input hashes and uses paired circular blocks of NYC days, with actual row weights for daylight-saving time. The command saves a separate immutable report and keeps replicate arrays outside Git.

After data preparation, run the separate observation-latency sensitivity study:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility latency
uv run python scripts/plot_latency.py reports/latency/<latency-id>
```

The [frozen latency protocol](LATENCY_PROTOCOL.md) compares 0/1/3/6-hour delays with the same training targets and validation hours. Recent lags and trailing windows use the latest available counts; target-time calendars and already-available day/week lags retain their alignment. This stage saves separate evidence and does not replace the serving artifact.

The separate [XGBoost study](../reports/XGBOOST_REVIEW.md) reuses hash-pinned zero-delay control predictions:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility xgboost
uv run python scripts/plot_xgboost.py reports/xgboost/<xgboost-id>
```

This stage requires the three original ignored latency-control prediction files in addition to prepared data; see the review's fresh-checkout prerequisite. Missing or changed controls fail before fitting. Its [frozen protocol](XGBOOST_PROTOCOL.md) allows exactly six fits and leaves serving unchanged. The plot alone reproduces from tracked metric tables.

The [paired XGBoost uncertainty analysis](../reports/XGBOOST_UNCERTAINTY_REVIEW.md) runs entirely from tracked daily summaries, without the ignored prediction files or data downloads:

```bash
uv run nyc-mobility xgboost-uncertainty
uv run python scripts/plot_xgboost_uncertainty.py reports/xgboost_uncertainty/<uncertainty-id>
```

It preserves the original uncertainty report and uses a separate [precommitted protocol](XGBOOST_UNCERTAINTY_PROTOCOL.md) covering both depth settings, with nominal family correction for their absolute MAE differences.

Audit official spatial sources and prepare past-only borough features without fitting:

```bash
uv run nyc-mobility spatial-prepare
uv run python scripts/plot_spatial_audit.py reports/spatial_preparation/<run-id>
```

The [spatial review](../reports/SPATIAL_PREPARATION_REVIEW.md) documents why polygon features are currently ineligible for the full historical study: the current geometry has February 2026 timestamps, and an older official version has duplicate/missing IDs. Borough features use the older lookup and lagged other-zone observations. Raw sources and the prepared full table stay outside Git; exact source hashes are required.

The separate [six-fit borough ablation](../reports/BOROUGH_REVIEW.md) uses the same pinned ignored latency-control forecasts as the XGBoost stage:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility borough
uv run python scripts/verify_borough.py reports/borough/<run-id>
uv run python scripts/plot_borough.py reports/borough/<run-id>
```

Its [frozen protocol](BOROUGH_SPATIAL_PROTOCOL.md) compares static indicators and lagged peer demand while retaining identical training/validation targets. Peer context lowers pooled MAE 0.415762% (3.695750 → 3.680385) and RMSE (10.278490 → 10.240313), but worsens sparse-zone and zero-target MAE in every fold. No promotion or test access. The [three-contrast uncertainty plan](BOROUGH_UNCERTAINTY_PROTOCOL.md) was frozen before the completed follow-up below. The verifier needs ignored saved predictions; the plot reproduces from tracked reports alone.


The [borough uncertainty analysis](../reports/BOROUGH_UNCERTAINTY_REVIEW.md) reproduces entirely from tracked summaries:

```bash
uv run nyc-mobility borough-uncertainty
uv run python scripts/verify_borough_uncertainty.py reports/borough_uncertainty/<run-id>
uv run python scripts/plot_borough_uncertainty.py reports/borough_uncertainty/<run-id>
```

The primary three-contrast-adjusted interval includes zero for static indicators and excludes zero for both context contrasts. All sensitivities are published; sparse-zone harms remain and no model is promoted. The [frozen protocol](BOROUGH_UNCERTAINTY_PROTOCOL.md) preserves the May seal.

The [NOAA weather audit](../reports/WEATHER_PREPARATION_REVIEW.md) prepares strictly past observations without fitting:

```bash
uv run nyc-mobility weather-audit
uv run python scripts/verify_weather.py
```

Three official stations supply 14,655 development observations. The strict rule accepts no April features. A separate [quality sensitivity](../reports/WEATHER_POLICY_REVIEW.md) explicitly labels newer readings unverified and prepares 30 predictors without losing validation targets. The [six-fit comparison](../reports/WEATHER_ABLATION_REVIEW.md) is complete: adding weather worsens pooled MAE by 2.735676% at three hours and 2.317405% at six hours, with regressions in every validation month. Historical archive availability remains unverified. Exact reproduction requires pinned ignored snapshots because NOAA's annual URLs can change.

```bash
uv run nyc-mobility weather-audit --protocol configs/weather_inputs_v2.toml
uv run nyc-mobility weather-prepare
uv run python scripts/verify_weather_policy.py
```

The separate [weather ablation](../reports/WEATHER_ABLATION_REVIEW.md) preserves missing values, quality indicators and all shared targets:

```bash
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 uv run nyc-mobility weather-ablation
uv run python scripts/verify_weather_ablation.py reports/weather_ablation/<run-id>
uv run python scripts/plot_weather_ablation.py reports/weather_ablation/<run-id>
```

Fitting requires cached pinned weather inputs and original ignored latency controls. The plot uses tracked summaries alone. Both weather candidates worsen MAE and RMSE; they are not promoted. The [paired uncertainty follow-up](../reports/WEATHER_UNCERTAINTY_REVIEW.md) retains higher weather error across all declared block lengths. Primary adjusted MAE-difference intervals (weather minus temporal, 3h / 6h) are [+0.063437, +0.142011] and [+0.055109, +0.119552]. May remains sealed.

The [weather uncertainty analysis](../reports/WEATHER_UNCERTAINTY_REVIEW.md) reproduces from tracked summaries alone:

```bash
uv run nyc-mobility weather-uncertainty
uv run python scripts/verify_weather_uncertainty.py reports/weather_uncertainty/<run-id>
uv run python scripts/plot_weather_uncertainty.py reports/weather_uncertainty/<run-id>
```

Both weather variants remain worse under 1/7/14-day resampling, with no model fitting or test access. The intervals are conditional on the historical archive and fitted models; they do not establish real-time availability or future performance.

## Prediction API

Train first, then run:

```bash
uv run uvicorn nyc_mobility.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the request schema. `GET /health` reports loaded model metadata. `POST /predict` accepts one NYC `zone_id` and 168–744 hourly observations, each with an explicit UTC offset and a nonnegative integer `demand`. It returns the immediately following target interval and a nonnegative expected pickup count. Missing hours, duplicates, unknown zones, and targets inside the training period fail validation. A request-generation script and smoke test are in `scripts/smoke_api.py`.

The current artifact serves the lowest-MAE classical model from the initial April comparison; the metadata also records the overall champion including baselines. This distinction matters if a baseline wins. Development backtests do not automatically replace the serving model. Only trusted local model artifacts should be loaded. The API is a local prototype: public hosting, authentication, operational observation ingestion, and monitoring are not yet implemented.

