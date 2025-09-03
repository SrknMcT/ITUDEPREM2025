# afad_quake

Small Python toolkit to query AFAD’s **event-service** and return earthquake data as **pandas DataFrames**, with simple filtering, daily aggregations, energy conversion, and CSV/JSON export.

> **Note:** AFAD’s filter endpoint requires explicit time bounds. This library focuses on `GET /apiv2/event/filter`. A “latest” helper is included but not all deployments expose `/event/latest`, so prefer the filter workflow shown below.

---

## Features

- **HTTP client for AFAD** (`/apiv2/event/filter`), with redirect support and configurable base URL.
- **Normalization to a canonical schema** (columns exist even when values are missing).
- **Client-side filters:** by date, magnitude, depth, magnitude type.
- **Energy conversion:** `log10(E[J]) = 1.44 + 5.24 * M` → `E = 10 ** (1.44 + 5.24*M)`.  
  Mw is typically preferred; you can filter by type.
- **Daily aggregations:**
  - `all_events` (no aggregation)
  - `daily_max_mag`
  - `daily_mag_threshold` (requires a threshold)
  - `daily_energy_sum`
  - `daily_energy_max`
  - Optional **fill empty days** with `energy=0.0`, `event_count=0`.
- **Export:** `save(path, fmt='csv'|'json')`.
- **Logging** utilities.

---

## Installation

```bash
pip install -r requirements.txt
```

`requirements.txt`:
```
pandas>=2.1
httpx>=0.27,<1.0
tzdata>=2024.1
numpy>=2.1
```

---

## Quick start

```python
from afad_quake.logger import configure_logging
from afad_quake.api import AfadAPI
from afad_quake.dataset import EarthquakeDataset

configure_logging()  # optional: prints basic logs to stdout

# Tip: many browsers are redirected to the AFAD gateway.
# Using the gateway base URL avoids DNS/redirect problems on some networks.
api = AfadAPI(base_url="https://servisnet.afad.gov.tr/apigateway/deprem")

# 1) Fetch by time window (required by AFAD filter)
raw = api.fetch_by_filter(
    start="2025-08-01 00:00:00",   # Europe/Istanbul local wall time
    end="2025-08-07 23:59:59",
    orderby="timedesc",
    # Optional server-side params:
    # bbox=(min_lat, min_lon, max_lat, max_lon),
    # radius=(lat, lon, km),
    # extra_params={"minmag": 3.5},
)

# 2) Build dataset → filter → energy → daily aggregation
ds = (
    EarthquakeDataset.from_records(raw)
    .filter_by_mag_type(allowed=["Mw","ML"])      # prefer Mw, then ML
    .filter_by_magnitude(min_mag=4.0)             # client-side filter
    .convert_energy()                              # E[J] = 10 ** (1.44 + 5.24*M)
    .aggregate_daily(mode="daily_energy_sum", fill_empty_days=True)
)

# 3) Use the DataFrame or save it
df = ds.to_dataframe()
print(df.head())

ds.save("quakes.csv", fmt="csv")   # or: ds.save("quakes.json", fmt="json")
```

---

## Project layout

```
afad_quake/
  api.py         # Low-level AFAD HTTP client
  dataset.py     # DataFrame layer: normalize, filters, energy, daily aggregations, save
  constants.py   # Defaults and canonical columns
  logger.py      # Logging helpers
```

---

## Endpoints & parameters

- Base host (choose one):
  - `https://servisnet.afad.gov.tr/apigateway/deprem`  ← recommended default
  - `https://deprem.afad.gov.tr`
- API root: `/apiv2`
- Filter endpoint: `/event/filter`  
  **Time parameters are required** (`start`, `end`) and should be formatted as `"YYYY-MM-DD HH:MM:SS"`.

**Spatial filters** (optional):
- Bounding box: `bbox=(min_lat, min_lon, max_lat, max_lon)` → sent as `minlat, minlon, maxlat, maxlon`
- Circular: `radius=(lat, lon, km)` → sent as `lat, lon, maxrad, minrad=0`

**Other server-side params** can be passed via `extra_params` (e.g. `{"minmag": 4}`).

---

## Canonical columns

The dataset attempts to provide these columns even when values are missing:

```
event_id, time, latitude, longitude, depth_km, magnitude, mag_type,
location, province, district, country, neighborhood, rms,
is_event_update, last_update_time
```

Any extra fields from AFAD are kept as additional columns.

---

## Filters (client-side)

```python
ds.filter_by_date(start="2025-08-01 00:00:00", end="2025-08-07 23:59:59")
ds.filter_by_magnitude(min_mag=5.0, max_mag=7.0)
ds.filter_by_depth(min_depth_km=0, max_depth_km=70)
ds.filter_by_mag_type(allowed=["Mw", "ML"])  # case-insensitive by default
```

---

## Energy conversion

```python
# Default: log10(E[J]) = 1.44 + 5.24 * M
ds.convert_energy(a=1.44, b=5.24, out_col="energy_J")
```

- Rows with missing `magnitude` yield `NaN` energy.
- Prefer Mw magnitudes by filtering (see above).

---

## Daily aggregations

All daily operations use **Europe/Istanbul** timezone.

```python
# No aggregation (event-level)
ds.aggregate_daily(mode="all_events")

# One max magnitude per day
ds.aggregate_daily(mode="daily_max_mag")

# One max magnitude per day (only events >= threshold)
ds.aggregate_daily(mode="daily_mag_threshold", threshold=5.0)

# Energy per day (sum or max); computes energy if missing
ds.convert_energy().aggregate_daily(mode="daily_energy_sum", fill_empty_days=True)
ds.convert_energy().aggregate_daily(mode="daily_energy_max")
```

Options:
- `fill_empty_days=True` → inserts missing days with:
  - `energy_J = 0.0` (for energy modes)
  - `event_count = 0`
  - `magnitude = NaN`
- `start`/`end` can be passed again to aggregation to explicitly bound the daily window.

---

## BBox & Radius examples

```python
# Bounding box (e.g., Western Turkey)
raw = api.fetch_by_filter(
    start="2025-01-01 00:00:00",
    end="2025-01-31 23:59:59",
    orderby="magnitude",
    bbox=(36.0, 26.0, 40.0, 29.5),         # (min_lat, min_lon, max_lat, max_lon)
    extra_params={"minmag": 3.5},
)

# Circular (e.g., Izmir within 200 km)
raw = api.fetch_by_filter(
    start="2025-01-01 00:00:00",
    end="2025-01-31 23:59:59",
    radius=(38.4237, 27.1428, 200.0),      # lat, lon, km
    orderby="timedesc",
)
```

---

## Timezone

- Input strings for `start`/`end` are interpreted as **Europe/Istanbul** local wall time.  
- The DataFrame `time` column is tz-aware (`Europe/Istanbul`).

---

## Logging

```python
from afad_quake.logger import configure_logging
configure_logging()     # default INFO level
```

Logs include request info and basic counts. Attach your own handlers as needed.

---

## Troubleshooting

- **302/redirect, 404, or DNS issues:**  
  Use the AFAD gateway base URL:
  ```python
  AfadAPI(base_url="https://servisnet.afad.gov.tr/apigateway/deprem")
  ```
- **Empty results:**  
  Double-check your `start`/`end` bounds and consider broadening filters (`minmag`, bbox/radius).
- **Timezone errors in pandas:**  
  Make sure you’re on `pandas>=2.1` and do not re-localize already tz-aware timestamps.

---

## License

MIT (add your preferred license text/file).
