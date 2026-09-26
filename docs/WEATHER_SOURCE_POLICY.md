# Weather source and preparation policy

This stage prepares and audits observed weather for a later, separately specified development experiment. It fits no models, selects no weather-informed champion, and does not evaluate May taxi targets. Eligible observations are not evidence of a useful model improvement or of operational availability.

## Official source and station identity

Use NOAA NCEI's [Global Historical Climatology Network hourly (GHCNh)](https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly), version 1.1.0. Its UTC observations and per-variable source/quality fields support an explicit preparation policy. [LCDv2](https://www.ncei.noaa.gov/products/land-based-station/local-climatological-data) also derives hourly observations from GHCNh; deprecated ISD/LCDv1 stopped receiving updates in August 2025 and cannot cover this project's full development period.

The [official station inventory](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.txt) identifies these three NYC stations. ICAO identifiers also appear in their observation-level source fields.

| Station | GHCNh ID | ICAO | Latitude | Longitude |
|---|---|---|---:|---:|
| LaGuardia Airport | USW00014732 | KLGA | 40.7794 | -73.8803 |
| JFK International Airport | USW00094789 | KJFK | 40.6392 | -73.7639 |
| New York City Central Park | USW00094728 | KNYC | 40.7789 | -73.9692 |

Download station-year files for 2025 and 2026. The explicit Parquet URL pattern is:

```text
https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/{year}/parquet/GHCNh_{station_id}_{year}.parquet
```

For example: [LaGuardia 2025](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/2025/parquet/GHCNh_USW00014732_2025.parquet) and [LaGuardia 2026](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/access/by-year/2026/parquet/GHCNh_USW00014732_2026.parquet). The same station-year names are available as PSV under `psv/` with a `.psv` extension.

These are distinct weather stations, not a dense measurement network covering every taxi zone. Any later station-to-zone assignment needs an explicit rule and a measured sensitivity analysis.

## Schema, timestamps and units

The [GHCNh manual, pages 6–7](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf), defines observation times in UTC. `DATE` can look timezone-naive, such as `2026-01-01T00:51:00`; parse it as UTC, retaining its minute. Do not localize it to New York or round it forward before joining.

| Variable | Unit in the downloaded values |
|---|---|
| `temperature`, `dew_point_temperature` | Degrees Celsius, already decimal-scaled |
| `wind_speed` | Meters per second |
| `precipitation` | Millimeters; accumulation interpretation matters |

For example, `temperature = -0.6` means −0.6 °C, not −0.06 °C. Field-name parsing must use the [v1.1.0 column definitions](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-columns.pdf), including `STATION` and `DATE`, rather than older positional layouts.

The [version-change document, page 2](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-version-updates.pdf), changes the old `9-Missing` representation to blank fields. Preserve absent measurements as missing. The main manual separately documents `-9999` as a precipitation missing sentinel for source 382; this is not permission to treat every negative number as missing. Negative air temperatures are valid.

## Conservative eligibility rule

The current project policy uses **temperature, dew point and wind speed only**. Each value must be numeric and finite, with its own `Source_Code` exactly `223` and `Quality_Code` exactly `1`. Temperature/dew point require a blank measurement code; wind speed requires `C`, `N` or `V` and a nonnegative value. Report types must be `FM12`, `FM15` or `FM16`. Codes remain strings; do not silently coerce or reinterpret unknown codes.

This deliberately restrictive selection is an engineering choice, not NOAA's complete definition of usable data. Retain counts for missing values, suspected/bad observations and policy exclusions separately. In particular, a calculated value or an unmapped source is not automatically an erroneous measurement.

The [manual's source-specific QC table, page 13](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf), defines source 223's numeric codes as follows:

| Code | Documented meaning | Project treatment |
|---|---|---|
| `0` | Not checked | Policy-excluded |
| `1` | Good | Eligible if the remaining checks pass |
| `2` | Suspect | Rejected as suspect |
| `3` | Erroneous | Rejected as erroneous |
| `4` | Calculated | Policy-excluded |
| `5` | Removed | Rejected |

Other source families reuse numeric codes differently. GHCNh also applies letter-coded checks to core variables. Never use a source-independent numeric allowlist, and never equate a blank quality field with a passed check.

The [source list, pages 2 and 15](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-source-list.pdf), maps `223` to the USAF surface database indexed by ICAO identifier; `412` and `413` identify NCEI-decoded SYNOP/BUFR and METAR observations starting in 2026. The downloaded main manual does not provide their legacy numeric QC mapping. Their exclusion here is a documented policy restriction, not a judgment that those sources are bad. Report the resulting station/month coverage before designing a weather model comparison.

## Precipitation is audited, not a model feature

The [manual, pages 10–11 and 16–17](https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf), distinguishes trace, inaccurate, incomplete and accumulated amounts. Trace may appear as `T` or source-specific `2`. FM15/FM16 subhourly precipitation reports can contain running totals; summing them double-counts rain. The manual's hourly extraction guidance uses the last report in the hour.

Defer precipitation features until report selection and accumulation periods have their own tested rule. A missing amount must not become an observed zero, and an unquantified trace must not become an invented positive rainfall depth.

## Availability and reproducibility boundary

[NOAA's dataset metadata](https://www.ncei.noaa.gov/metadata/geoportal/rest/metadata/item/gov.noaa.ncdc:C01688/html) specifies **daily** updates. It does not establish an hourly publication service-level guarantee. The current station-year files contain historical observations retrieved later, with subsequent harmonization and quality processing. An observation timestamp records when weather was measured; it does not prove when that exact archived value became available to a forecaster.

Preserve the URL, retrieval timestamp, content hash, file size, HTTP `Last-Modified` and ETag for each downloaded source and document. These identify the snapshot we used, not its historical publication time. Store raw files and download sidecars under ignored `data/external/weather/`; publish compact provenance and quality summaries only.

A future evaluation must use strictly past observations at each prediction boundary, state its assumed weather delay and maximum staleness, preserve missingness, and prohibit backward filling from future observations. Delay sensitivity can test that assumption; it cannot establish archival as-of availability. Do not describe an analysis using these retrospective observations as demonstrated live forecasting.

For any later weather comparison, freeze the eligible target population and compare a matched temporal control. Report coverage-driven exclusions and sparse-zone behavior so that a different row population cannot masquerade as a weather benefit. The preparation stage itself does not authorize model promotion or opening the sealed May test.

## Documentation snapshot

The downloaded manual identifies version 1.1.0, updated March 10, 2026. The four documents below were retrieved with the existing verified-download helper on September 26, 2026; full HTTP metadata lives in their adjacent JSON sidecars.

| Document in `data/external/weather/` | SHA-256 |
|---|---|
| `ghcnh_DOCUMENTATION.pdf` | `df5694efdc2d498f006a343165bae65701d14809174b9bed660149bd4fe591b7` |
| `ghcnh-version-updates.pdf` | `dbbc3475685764b0f42351cb1c853f823127a1191573a59c24f14c0493136532` |
| `ghcnh-source-list.pdf` | `4f6a18c0b18825f28e72af04cc3a2ac8a26bd7015910798d1a0cee2a114f689d` |
| `ghcnh-columns.pdf` | `2eb051a2919be41a57c5c49ae6aa0f077194fe1983417a2e8ba4fbbaf16ea7b5` |

Data citation: Menne et al. (2023), *Global Historical Climatology Network-Hourly (GHCNh)*, NOAA NCEI, [doi:10.25921/jp3d-3v19](https://doi.org/10.25921/jp3d-3v19), the three stations and years listed above, accessed September 26, 2026.
