# Data-quality review · September 14, 2026

The development-period audit found **zero exact repeated rows among 19,179,942 eligible pickups** and **no citywide zero-pickup hours**. The canonical target is retained. Unusual reporting volume is an investigation signal, not a reason to erase observations.

## Reproduce and inspect

```bash
uv run nyc-mobility audit-quality
```

Run after acquisition and preparation. This optional audit is separate from `nyc-mobility all` because it groups every source column and performs two complete baseline evaluations. It uses only source months before the configured test boundary: December 2025–April 2026 under the default configuration. May trip records are not opened by this audit. The ordinary six-month preparation stage was also rerun to verify that new integrity checks preserve its output byte-for-byte; no May model metrics were computed.

The [latest audit](latest_quality_audit.json) records the exact source/code/environment hashes, configuration, Git revision and working-tree state. The [measured run](quality_audits/20260914T183522Z-419381/audit.json) is immutable. Small CSV reports live beside it. Full reporting-volume and alternate-label Parquet tables are stored under ignored `artifacts/quality_audits/<audit_id>/`. No model artifact or model-selection record is changed.

## Exact-duplicate sensitivity

An exact repeated group has equal values in **every original Parquet column**, including VendorID, payment/fare fields and any additional source columns. DuckDB `GROUP BY ALL` groups equal NULL values together; it does not use a lossy hash or a partial pickup key. A group with `n` copies contributes `n - 1` excess rows to the alternate scenario. This is a sensitivity definition, not proof that multiple reported rows represent one physical trip. See the [DuckDB grouping documentation](https://duckdb.org/docs/current/sql/query_syntax/groupby) for the SQL behavior.

Eligibility is the same as preparation: a pickup within its source month and the development interval, in an NYC borough zone, and with resolvable local time. Out-of-month records, non-NYC locations and invalid DST hours do not enter either scenario. Audit counts must exactly match the canonical development panel before sensitivity evaluation can proceed.

| Month | Eligible recorded pickups | Exact excess rows |
|---|---:|---:|
| December 2025 | 4,296,671 | 0 |
| January 2026 | 3,718,466 | 0 |
| February 2026 | 3,394,422 | 0 |
| March 2026 | 3,945,656 | 0 |
| April 2026 | 3,824,727 | 0 |
| **Total** | **19,179,942** | **0** |

The alternate scenario rebuilds all lags, rolling features and training-only historical averages after subtracting exact excess rows. All five April baseline scores are therefore unchanged here, including the weekly baseline MAE of **4.3054707379**. This is a negative result for exact-duplicate cleaning, not an improvement in forecasting. Near-duplicates, revisions with changed fare fields, and duplicates outside the eligible population remain outside this audit's claim. There is still no universal trip ID that establishes physical-trip uniqueness.

## Reporting-volume checks

Create a dense hourly series for the city and each observed VendorID over the **3,623 development hours**. For each hour, compare recorded pickups with the median at offsets 168, 336, 504 and 672 elapsed hours earlier. Flag a ratio below 10% only when at least three prior matches exist and their median is at least 100 pickups. References never include the current or future observations, and each vendor has its own history. Offsets are elapsed hours; clock-time alignment can differ around DST. This retrospective check is not yet an operational monitoring service or a model feature.

| Series | Total pickups | Zero-count hours | Low-volume flags |
|---|---:|---:|---:|
| City | 19,179,942 | 0 | 4 |
| Vendor 1 | 3,686,716 | 0 | 9 |
| Vendor 2 | 15,219,500 | 0 | 1 |
| Vendor 6 | 33,442 | 386 | 0 |
| Vendor 7 | 240,284 | 44 | 5 |

The 19 flags include overlapping city and vendor observations, not 19 independent incidents. Small providers can legitimately have zero-count hours. The minimum-reference rule means an absence of flags does not establish complete reporting for low-volume vendors.

### February 23: citywide extreme conditions

All four city flags occur at **07:00–10:00 NYC local time on February 23, 2026**. Counts were 314, 401, 424 and 456, respectively, approximately 8.7–9.8% of their trailing weekly medians.

The National Weather Service reports blizzard conditions across all five NYC counties on February 23. [NWS event summary](https://www.weather.gov/okx/20260222_23). NYC's Emergency Executive Order No. 3 restricted most vehicular traffic from 21:00 February 22 through noon February 23, with specified exceptions. [Official order](https://www.nyc.gov/mayors-office/news/2026/02/emergency-executive-order-no--3).

**Inference:** a real change in taxi activity is plausible during these hours, so automatically treating them as a vendor outage would be unjustified. These sources establish event overlap, not the fraction of the pickup decline caused by weather or restrictions, and they do not prove reporting completeness. Retain the observations. Historical weather remains a planned feature ablation; these event notes are not forecast-time inputs.

### January 5–6: vendor-specific anomaly remains unresolved

Vendor 7 has zero recorded pickups at **17:00 and 18:00 NYC time on January 5**, against historical medians of 134 and 132.5. The city records 6,715 and 6,484 pickups in those hours—roughly 73.6% and 71.5% of its corresponding medians. Vendor 7 also flags at 16:00 January 5 and 16:00 January 6; its remaining flag is January 1 at 08:00.

This is more localized than the February citywide drop, but source counts alone cannot distinguish service reductions from missing submissions. Preserve the labels and mark the January 5–6 interval for provider-level follow-up. Do not impute absent trips or silently remove these hours. A future sensitivity experiment can explicitly mask suspect observation lags, without changing ground truth, and compare predictions on development folds.

## Engineering verification and decision

- Densification now rejects out-of-scope keys, invalid/noninteger counts, integer overflow, missing or naive timestamps, and invalid interval bounds, and asserts conservation of accepted pickups.
- **45 tests pass**, including equal-NULL duplicate groups, all-column identity, duplicate-free inputs, test-file exclusion, canonical-artifact preservation, corrupted source hashes, causal reporting references and vendor isolation. Synthetic fixtures are used only in tests.
- Ruff lint and formatting pass. The real audit runs successfully and repeated audits reproduce monthly findings, reporting flags and baseline scores.
- The hardened six-month preparation reproduces the original Parquet SHA-256 exactly: `4b05fc7b7ec8bac8967361ce0086979f08275d02623181380a92108b1e43fb80`.

**Decision:** keep the recorded-count target and the existing model. Exact-duplicate removal provides no benefit in the audited population. Investigate the localized vendor anomaly and retain the weather-associated low-volume period. The next modeling work should address sparse-zone overprediction with development-only walk-forward evaluation. May remains held out from model evaluation.
