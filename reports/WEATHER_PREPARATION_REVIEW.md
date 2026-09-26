# NOAA weather acquisition and availability audit

September 26, 2026 · run `20260926T181034Z-9464c0` · no model fits.

The three-station NOAA archive supplies real development observations, but **the current conservative quality policy does not provide April features**. Source 223's last accepted temperature is March 26 at 16:51 UTC at all three stations; replacement sources 412/413 appear from March 27 at 00:51 UTC. Their blank quality codes are not mapped to a documented passed-check code in the downloaded main manual. This is a policy/metadata gap, not evidence that April weather is absent or erroneous. The hypothesis that one legacy quality rule covers the full development window failed.

## Measured coverage

We acquired six NOAA GHCNh station-year Parquet files plus the station inventory and four specification documents. Exact URLs, hashes, retrieval times, sizes, ETags and Last-Modified values are recorded in [metrics.json](weather/20260926T181034Z-9464c0/metrics.json). Source and schema decisions are documented in [the preparation policy](../docs/WEATHER_SOURCE_POLICY.md).

Bounds are December 1, 2025 05:00 UTC through May 1, 2026 04:00 UTC, end exclusive: 3,623 hourly prediction boundaries per station, including the 23-hour March DST day. Predicate pushdown limits the annual files to this window. There are 84,763 source rows and 14,655 rows with at least one core weather measurement. No taxi target table is read. The annual weather downloads contain later dates, but these do not enter the audit.

| Station | Core observation rows | Hours with any core observation | Hours with accepted temperature | Hours with accepted wind |
|---|---:|---:|---:|---:|
| LaGuardia | 5,218 | 3,597 | 2,757 | 2,757 |
| JFK | 4,985 | 3,595 | 2,756 | 2,755 |
| Central Park | 4,452 | 3,594 | 2,749 | 2,446 |

All counts use the same 3,623-hour denominator. All three stations have an 851-hour trailing interval without accepted core values under this policy. Central Park also has substantial earlier wind gaps. Missing values are retained; missing rain is never turned into zero.

The full [quality-code table](weather/20260926T181034Z-9464c0/quality_flags.csv) distinguishes source, quality, measurement code, report type, month, missing measurements and policy exclusions. Accepted core values total 34,288. The policy excludes 8,886 core values from sources 412/413, four source-223 calculated values and two source-223 suspect dew-point readings. These exclusions have different meanings; they must not all be described as bad data. Precipitation's 11,581 nonmissing values are audited but excluded from prepared features pending an accumulation/trace policy.

## Timing and availability

Prepared snapshots select the latest core observation satisfying `observed_at + assumed_delay < target_hour`, then require its observation age to be at most 12 hours. They retain missing or rejected fields on that observation, without substituting an older complete reading. The delays 0/1/3/6 hours are scenarios, not measured publication latencies. All four are reported; no preferred lag was selected using demand errors.

At the three-hour scenario, complete temperature/dew-point/wind snapshots are:

| Station | December | January | February | March | April |
|---|---:|---:|---:|---:|---:|
| LaGuardia | 740 / 744 | 744 / 744 | 672 / 672 | 623 / 743 | 0 / 720 |
| JFK | 739 / 744 | 743 / 744 | 672 / 672 | 623 / 743 | 0 / 720 |
| Central Park | 631 / 744 | 618 / 744 | 638 / 672 | 560 / 743 | 0 / 720 |

See [all 60 station/month/delay rows](weather/20260926T181034Z-9464c0/availability_coverage.csv) and [native coverage](weather/20260926T181034Z-9464c0/native_coverage.csv). Initial missing boundaries reflect the explicit development start without pre-window history. Historical publication times and archive revisions are unverified; neither a positive lag nor good coverage proves that today's finalized values were available at an old forecast boundary. No point-in-time operational claim is eligible.

## Verification and reproduction

```bash
uv run nyc-mobility weather-audit
uv run python scripts/verify_weather.py
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

All 342 tests and Ruff pass. Synthetic tests cover date bounds, source/quality handling, scaled negative temperatures, station identity, time ordering, DST, exact availability/staleness boundaries, future perturbations and failures before unverified input can be published. The actual stage prepares 43,476 station/target/delay rows. An independent search-based verifier checks all of them, including timestamps, ages and values. Re-execution in an isolated directory with only weather assets, source, configuration and lock produces byte-identical three CSV and two Parquet outputs. [Verification](weather/20260926T181034Z-9464c0/verification.json) confirms 20 existing data/model/evidence files are unchanged.

No dependency was added. Raw archives, documents and full observation/snapshot tables remain ignored. Tracked summaries reproduce the published audit narrative. Full stage reproduction needs the pinned raw snapshots: NOAA can revise its mutable annual URLs, so a fresh download may fail the hash check. Preserve the cached snapshot rather than silently accepting different bytes; any replacement requires a new audit. The original serving model and explorer remain unchanged, and May test metrics remain null.

## Next action

Resolve sources 412/413 using authoritative quality-control documentation or a clearly justified, separately tested treatment of unchecked observations. Re-audit the unchanged development window before freezing a bounded weather comparison with identical control targets and explicit missingness/availability assumptions. Do not restrict the comparison to convenient earlier months or silently relax the rule after seeing model scores. Precipitation and station-to-zone mapping need separate declared policies. If the source semantics remain unresolved, proceed with interpretation/reproducibility work and retain weather as an explicit limitation.
