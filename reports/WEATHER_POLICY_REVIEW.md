# Weather quality sensitivity and model-input preparation

September 27, 2026 · policy audit `20260927T200152Z-dbeed1` · feature preparation `20260927T200154Z-823e9c` · no weather model fits.

**A separate, explicitly unverified quality policy recovers most April coverage without changing the original strict audit.** It does not resolve the missing NOAA passed-check semantics or prove historical publication availability. The prepared feature bundle is ready for a bounded conditional comparison; no forecasting improvement has been measured yet.

## Evidence and declared choice

The official [source list](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-source-list.pdf), page 15, identifies source 412 as NCEI-decoded SYNOP/BUFR land observations and source 413 as NCEI-decoded METAR. The [manual](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf), pages 12–15, defines report types and legacy quality mappings but gives no general blank-quality passed-check rule for 412/413. The documents rechecked September 27 have the same hashes as the pinned September 26 copies; no new authoritative clarification was found. The hypothesis that the documentation supplies a transferable passed-check mapping failed. In particular, the source-382 precipitation convention and GHCN-Daily convention do not apply.

The versioned policy `documented-sources-with-unverified-v1` is an engineering sensitivity, not a NOAA quality endorsement:

- Keep the original source-223/QC-1 rules and label those accepted values `good` under their documented legacy mapping.
- Admit source-412 temperature/dew point only with blank quality/measurement fields and `FM12` or `FM94_1` reports. Admit source-413 temperature/dew point/wind only with blank quality/measurement and `FM15` or `FM16`. Wind must be nonnegative. Label all these additions `unverified`, meaning no documented passed-check status; this does not prove that no checks occurred.
- Keep missing and rejected statuses distinct. Reject unknown sources, nonblank unmapped quality codes and unexpected report/measurement combinations. Preserve original SI units, station identity and exact observation minute. Precipitation remains audit-only.
- Use the same six pinned raw archives, development window, station inventory and 0/1/3/6-hour delay scenarios. Quality admission was chosen before any weather-demand model scores. No target was removed to improve apparent coverage or accuracy.

Raw source flags remain in the pinned ignored files and grouped audit; prepared rows retain each variable's source and quality status. Status follows the exact observation selected by the strictly past as-of join, including missing/rejected values. It cannot be borrowed from an older complete observation.

## Measured coverage change

The same 84,763 December–April source rows yield the same 14,655 core observations. The new policy retains 43,174 core values: 34,288 under the original good rule and **8,886 explicitly unverified additions** (3,083 temperature, 3,081 dew point, 2,722 wind). Four calculated and two suspect source-223 readings remain excluded. All 11,581 nonmissing precipitation values remain excluded from features.

At an assumed three-hour delay and 12-hour maximum observation age, complete temperature/dew/wind snapshots are:

| Station | December | January | February | March | April |
|---|---:|---:|---:|---:|---:|
| LaGuardia | 740 / 744 | 744 / 744 | 672 / 672 | 743 / 743 | 717 / 720 |
| JFK | 739 / 744 | 743 / 744 | 672 / 672 | 743 / 743 | 717 / 720 |
| Central Park | 631 / 744 | 618 / 744 | 638 / 672 | 656 / 743 | 642 / 720 |

All complete April snapshots rely on unverified values; zero April values acquire a documented-good status through this change. At six hours, April complete counts are 717 / 717 / 640 respectively. All four delays, all five months and both good/unverified counts are published in [availability coverage](weather_policy/20260927T200152Z-dbeed1/availability_coverage.csv). The primary source transition remains a distribution change, not a solved operational-quality guarantee.

Native temperature coverage improves to 3,597 / 3,595 / 3,593 of 3,623 hours (LaGuardia/JFK/Central Park). Central Park wind has only 3,192 covered hours and a longest native missing run of 51 hours. [Native coverage](weather_policy/20260927T200152Z-dbeed1/native_coverage.csv) and [every quality/source group](weather_policy/20260927T200152Z-dbeed1/quality_flags.csv) preserve these gaps. No missing value is filled.

## Ready inputs and matched controls

The new `weather-prepare` stage creates two ignored **3,623 × 30** citywide predictor tables for three- and six-hour delay assumptions. Each station contributes temperature, dew point, wind, three missing indicators, three unverified indicators and observation age. NaNs remain for native histogram-boosting handling. There is no guessed station-to-zone assignment, precipitation feature or full zone-by-weather table stored. Sharing a unique hourly row across zones permits an exact many-to-one append without multiplying memory unnecessarily.

A no-fit preflight verifies unchanged training signatures, target keys/labels, sparse cohorts and all saved control scores for three folds. Training rows remain 342,696 / 518,760 / 713,426; validation remains 176,064 / 194,666 / 188,640, totaling **559,370 zone-hours per candidate**. Only the existing temporal warm-up is removed; missing weather never deletes a target. See [preflight](weather_features/20260927T200154Z-823e9c/control_preflight.csv) and [feature summaries](weather_features/20260927T200154Z-823e9c/feature_summary.csv).

The [six-fit protocol](../docs/WEATHER_ABLATION_PROTOCOL.md) is frozen with this publication: fixed histogram settings, three-hour primary and six-hour sensitivity across February/March/April, compared with the shared temporal control. The whole 30-feature bundle is the intervention; any future gain cannot be attributed solely to weather values instead of missingness or source-status indicators. No model is fitted or promoted today, and May remains sealed.

## Verification and reproduction

```bash
uv run nyc-mobility weather-audit --protocol configs/weather_inputs_v2.toml
uv run nyc-mobility weather-prepare
uv run python scripts/verify_weather_policy.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

`weather-prepare` uses the exact audit paths/hashes pinned in the protocol, not whichever audit was most recently created. Restore the ignored pinned snapshots and shared control forecasts for exact reproduction; do not rewrite the frozen protocol to make a missing input pass. NOAA annual URLs are mutable, so a fresh raw download may legitimately fail the recorded hash check. All large/raw tables stay ignored.

All **487 tests** and Ruff pass. Focused tests cover source-specific quality rules, unverified flags, stale/unmatched metadata, exact station/time coverage, missing-only preparation, sealed-window and hash failures, and absence of candidate fitting. Independent search-based verification checks all **43,476** station/target/delay rows, including status and source fields. Independent reshaping checks all **217,380** numeric bundle values. Re-execution in a weather-only isolated directory reproduces the three CSV and two Parquet outputs for both the legacy and new policies byte-for-byte. [Verification](weather_features/20260927T200154Z-823e9c/verification.json) preserves 28 prior model/data/evidence/policy files. No dependencies were added.

The [policy metrics](weather_policy/20260927T200152Z-dbeed1/metrics.json) and [preparation metrics](weather_features/20260927T200154Z-823e9c/metrics.json) record exact input, source, configuration, lock and output hashes. The original serving model, historical explorer, strict audit and May seal remain unchanged. Next implement and run exactly the frozen six candidate fits; report all negative results and slice tradeoffs without extending the search.
