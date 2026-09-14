# Data contract and provenance

## Official sources

- Index: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- Trips: `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_{YYYY-MM}.parquet`
- Lookup: https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
- Boundaries: https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip
- Yellow dictionary: https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf
- NYC Open Data terms: https://opendata.cityofnewyork.us/overview/#termsofuse

Initial months: 2025-12, 2026-01, 2026-02, 2026-03, 2026-04, 2026-05. Six raw files total 398,958,298 bytes. The source manifest records exact file-level hashes, bytes, source URLs, and retrieval times. Raw files remain unchanged. Public data is attributed to NYC TLC and its technology providers; the repository's MIT license does not relicense source data. TLC does not guarantee accuracy or completeness.

## Acquisition and storage

Run `uv run python scripts/download_data.py --start 2025-12 --end 2026-05`. Files stream to temporary paths and are atomically renamed after completion; Parquet metadata is validated. Three attempts handle transient network errors. Existing cached files are hash-verified without an unnecessary remote fetch. Upstream revisions require explicit local cache invalidation; cache hits do not claim to detect upstream changes.

- `raw/`: six original Parquet files (~399 MB), ignored by Git.
- `external/`: original lookup CSV and shapefile ZIP (~1 MB), ignored by Git.
- `processed/hourly_demand.parquet`: dense zone-hour count panel, ignored by Git.
- `../artifacts/`: model, metadata, validation predictions, ignored by Git.
- `../reports/`: small auditable aggregate results, source manifest and figures, committed.

## Schema and filtering

Require pickup/dropoff timestamps, pickup/dropoff zone IDs, passenger count, distance, fare, payment type. Pickup/dropoff timestamps must be timezone-naive timestamps; zone IDs must be integers. Timestamp schema drift fails loudly.

Count only rows with a pickup in the nominal file month and a lookup ID in the five NYC boroughs. Unknown/outside-NYC IDs 264/265 and Newark Airport ID 1 are excluded. Quality flags include out-of-month times, missing passenger counts, nonpositive distance/duration, and negative fares. Flags overlap; accepted/excluded totals use the actual eligibility filter. Fare/distance/dropoff flags do not remove pickups because filtering on future trip outcomes changes the target population. Raw rows have no reliable universal trip ID; no speculative deduplication is applied. Duplicate-record sensitivity remains a follow-on task.

Aggregate pickup timestamps to local hours with DuckDB, then localize to `America/New_York` and convert to UTC. Impossible spring timestamps are excluded and counted. Ambiguous fall-back dates are unsupported until a defensible resolution policy exists; densification fails instead of inventing demand. Populate every NYC zone at every valid elapsed hour. Missing zone-hours become zero only after all requested monthly source files are present; undetected source outages remain a limitation.

Output: `zone_id` (integer), `hour` (UTC timestamp at start of target interval), `demand` (nonnegative integer), `borough`, `Zone`. Key: `(zone_id, hour)`; unique, contiguous one-hour steps per zone. Target interval is `[hour, hour + 1 hour)`.

Densification rejects counts outside the declared zones/time interval rather than silently discarding them. It also rejects invalid counts, overflow and naive/missing timestamps, and asserts count conservation.

## Optional development data-quality audit

`uv run nyc-mobility audit-quality` inspects December–April only by default. All source-file hashes must match the acquisition manifest, and independently reconstructed demand must match the canonical panel. Exact duplicate groups use every original source column under DuckDB SQL equality, with equal NULL values grouped together. Recompute all five baselines under the hypothetical exact-deduplication policy; do not overwrite recorded counts or promote a model based on changed-label scores.

The audit also checks city/provider volume against preceding weekly-hour medians. These are investigation flags, not proof of outages or instructions to impute demand. A zero count from a small provider is not sufficient evidence of a missing feed. All-column exact duplication is narrower than physical-trip duplication; near-duplicates and corrections are not resolved.

Small reports and immutable audit metadata are committed under `reports/quality_audits/`. Full alternate-label and reporting-volume Parquet files stay ignored under `artifacts/quality_audits/`. Each run can require temporary DuckDB spill space in `work/`; its configured working memory limit is 2 GB. See [the measured review](../reports/DATA_QUALITY_REVIEW.md) and [latest audit record](../reports/latest_quality_audit.json).

## Geographic and future weather joins

Join lookup and geometry by `LocationID` / `zone_id`, never by a fuzzy zone name. Dissolve multipart/duplicate geographic IDs before joining. Maps use EPSG:2263; NYC membership comes from the official borough lookup. Geometry is not yet a model feature.

Weather is not integrated yet. Planned observations: NOAA station measurements, parsed in UTC with station provenance and quality flags. Feature availability must precede the forecast boundary; future realized weather is prohibited. Reanalysis and archived observations are not interchangeable with weather forecasts. Evaluate weather on development folds with an ablation and retain negative results.
