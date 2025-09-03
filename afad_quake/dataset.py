from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence

import pandas as pd
import numpy as np

from constants import CANONICAL_FIELDS, DEFAULT_TZ
from logger import get_logger


class EarthquakeDataset:
    """
    Lightweight container over AFAD event records with DataFrame utilities.

    Key features:
    - Normalize raw records to a canonical schema (columns always exist, may be null).
    - Client-side filters (date/magnitude/depth/mag_type).
    - Energy conversion: E[J] = 10 ^ (a + b * M), defaults a=1.44, b=5.24.
    - Daily aggregations with options (one row per day if requested).
    - Single save() for CSV/JSON.

    Parameters
    ----------
    records : list[dict]
        Raw event list as returned by AfadAPI.
    logger_name : str
        Optional custom logger name.

    Examples
    --------
    >>> ds = EarthquakeDataset.from_records(raw_items)
    >>> (ds.filter_by_magnitude(min_mag=5.0)
    ...    .convert_energy()   # E = 10 ** (1.44 + 5.24*M)
    ...    .aggregate_daily(mode="daily_energy_sum", fill_empty_days=True)
    ...    .to_dataframe())
    """

    def __init__(self, records: List[Dict[str, Any]], logger_name: str = "afad_quake") -> None:
        self._logger = get_logger()
        self._raw = records or []
        self._df: Optional[pd.DataFrame] = None  # built lazily

    # ------------- Constructors -------------
    @classmethod
    def from_records(cls, records: List[Dict[str, Any]]) -> "EarthquakeDataset":
        """Create dataset from raw AFAD records."""
        return cls(records)

    # ------------- Core -------------
    def to_dataframe(self) -> pd.DataFrame:
        """
        Return the internal DataFrame, building it once from raw records.

        - Ensures all canonical columns exist (possibly null).
        - Parses 'time' to tz-aware Europe/Istanbul.
        - Casts numeric fields to float where applicable.
        """
        if self._df is not None:
            return self._df

        rows: List[Dict[str, Any]] = [self._normalize_record(r) for r in self._raw]
        df = pd.DataFrame(rows)

        # Ensure canonical columns exist even if missing in data
        for col in CANONICAL_FIELDS:
            if col not in df.columns:
                df[col] = np.nan

        # Coerce numeric types
        for col in ("latitude", "longitude", "depth_km", "magnitude", "rms"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # Parse time → Europe/Istanbul (tz-aware)
        if "time" in df.columns:
            t = pd.to_datetime(df["time"], errors="coerce", utc=False)
            # If tz-naive → localize to DEFAULT_TZ; if tz-aware → convert.
            if getattr(t.dt, "tz", None) is None:
                t = t.dt.tz_localize(DEFAULT_TZ)
            else:
                t = t.dt.tz_convert(DEFAULT_TZ)
            df["time"] = t

        # Order columns: canonical first, then the rest
        other_cols = [c for c in df.columns if c not in CANONICAL_FIELDS]
        df = df[CANONICAL_FIELDS + other_cols]

        self._df = df
        return self._df

    def save(self, path: str, *, fmt: Literal["csv", "json"] = "csv", **kwargs) -> "EarthquakeDataset":
        """
        Save the current DataFrame to disk.

        Parameters
        ----------
        path : str
            File path.
        fmt : {'csv','json'}
            Output format.
        kwargs :
            Passed to pandas writer. For JSON, defaults to orient='records', date_format='iso'.

        Examples
        --------
        >>> ds.convert_energy().aggregate_daily("daily_energy_sum", fill_empty_days=True).save("quakes.json", fmt="json")
        """
        df = self.to_dataframe().copy()
        if fmt == "csv":
            df.to_csv(path, index=False, encoding=kwargs.pop("encoding", "utf-8"), **kwargs)
        elif fmt == "json":
            kwargs.setdefault("orient", "records")
            kwargs.setdefault("date_format", "iso")
            kwargs.setdefault("force_ascii", False)
            df.to_json(path, **kwargs)
        else:
            raise ValueError("fmt must be 'csv' or 'json'")
        return self

    # ------------- Filters (in-place; chainable) -------------
    def filter_by_date(
        self,
        *,
        start: Optional[str | pd.Timestamp] = None,
        end: Optional[str | pd.Timestamp] = None,
    ) -> "EarthquakeDataset":
        """
        Keep rows within [start, end] (inclusive) in Europe/Istanbul.

        Examples
        --------
        >>> ds.filter_by_date(start="2025-08-01 00:00:00", end="2025-08-07 23:59:59")
        """
        df = self.to_dataframe()
        t = df["time"]
        if start is not None:
            s = pd.Timestamp(start, tz=DEFAULT_TZ)
            df = df[t >= s]
        if end is not None:
            e = pd.Timestamp(end, tz=DEFAULT_TZ)
            df = df[t <= e]
        self._df = df
        return self

    def filter_by_magnitude(
        self,
        *,
        min_mag: Optional[float] = None,
        max_mag: Optional[float] = None,
    ) -> "EarthquakeDataset":
        """
        Keep rows where magnitude is within [min_mag, max_mag].

        Examples
        --------
        >>> ds.filter_by_magnitude(min_mag=5.0)
        """
        df = self.to_dataframe()
        mag = df["magnitude"]
        if min_mag is not None:
            df = df[mag >= float(min_mag)]
        if max_mag is not None:
            df = df[mag <= float(max_mag)]
        self._df = df
        return self

    def filter_by_depth(
        self,
        *,
        min_depth_km: Optional[float] = None,
        max_depth_km: Optional[float] = None,
    ) -> "EarthquakeDataset":
        """
        Keep rows where depth_km is within [min_depth_km, max_depth_km].

        Examples
        --------
        >>> ds.filter_by_depth(min_depth_km=0, max_depth_km=70)
        """
        df = self.to_dataframe()
        d = df["depth_km"]
        if min_depth_km is not None:
            df = df[d >= float(min_depth_km)]
        if max_depth_km is not None:
            df = df[d <= float(max_depth_km)]
        self._df = df
        return self

    def filter_by_mag_type(
        self,
        *,
        allowed: Sequence[str] = ("Mw", "ML", "Md", "Mb"),
        case_insensitive: bool = True,
    ) -> "EarthquakeDataset":
        """
        Keep rows where mag_type in allowed.

        Examples
        --------
        >>> ds.filter_by_mag_type(allowed=["Mw"])
        """
        df = self.to_dataframe()
        col = df["mag_type"].astype("string")
        if case_insensitive:
            allowed_set = {a.lower() for a in allowed}
            mask = col.str.lower().isin(allowed_set)
        else:
            mask = col.isin(allowed)
        self._df = df[mask]
        return self

    # ------------- Energy -------------
    def convert_energy(
        self,
        *,
        a: float = 1.44,
        b: float = 5.24,
        out_col: str = "energy_J",
        preferred_types: Sequence[str] = ("Mw", "ML"),
    ) -> "EarthquakeDataset":
        """
        Compute earthquake energy per event using log formula:

            log10(E[J]) = a + b * M   →   E = 10 ** (a + b*M)

        Notes
        -----
        - If 'mag_type' exists, rows preferring types in `preferred_types` are treated the same;
          preference matters when you pre-filter by mag_type upstream.
        - Rows with NaN magnitude produce NaN energy.

        Examples
        --------
        >>> ds.convert_energy()               # defaults: a=1.44, b=5.24 → E[J]
        >>> ds.convert_energy(out_col="E")    # write to a custom column
        """
        df = self.to_dataframe().copy()
        m = pd.to_numeric(df["magnitude"], errors="coerce")
        e = np.where(m.notna(), np.power(10.0, a + b * m), np.nan)
        df[out_col] = e
        self._df = df
        return self

    # ------------- Daily aggregation -------------
    def aggregate_daily(
        self,
        mode: Literal[
            "all_events",
            "daily_max_mag",
            "daily_mag_threshold",
            "daily_energy_sum",
            "daily_energy_max",
        ] = "all_events",
        *,
        threshold: Optional[float] = None,
        energy_col: str = "energy_J",
        fill_empty_days: bool = False,
        start: Optional[str | pd.Timestamp] = None,
        end: Optional[str | pd.Timestamp] = None,
    ) -> "EarthquakeDataset":
        """
        Aggregate events by day (Europe/Istanbul). Returns one-row-per-day for daily_* modes.

        Modes
        -----
        - 'all_events'        : no aggregation; returns self unchanged.
        - 'daily_max_mag'     : keep only the max magnitude per day.
        - 'daily_mag_threshold': per day, consider only events with magnitude >= threshold,
                                 then keep the max magnitude among them (requires threshold).
        - 'daily_energy_sum'  : sum of energy per day (auto-computes energy if missing).
        - 'daily_energy_max'  : max energy per day (auto-computes energy if missing).

        fill_empty_days=True → include missing days with:
          time=day 00:00 (tz), energy=0.0, magnitude=NaN, event_count=0

        Examples
        --------
        >>> (ds.convert_energy()
        ...   .aggregate_daily(mode="daily_energy_sum", fill_empty_days=True)
        ...   .to_dataframe())
        """
        if mode == "all_events":
            return self

        df = self.to_dataframe().copy()

        # Define day key in Istanbul TZ
        day = df["time"].dt.tz_convert(DEFAULT_TZ).dt.floor("D")
        df = df.assign(__day=day)

        # Optional date window for aggregation
        if start is not None:
            s = pd.Timestamp(start, tz=DEFAULT_TZ).floor("D")
            df = df[df["__day"] >= s]
        if end is not None:
            e = pd.Timestamp(end, tz=DEFAULT_TZ).floor("D")
            df = df[df["__day"] <= e]

        def _ensure_energy(local_df: pd.DataFrame) -> pd.DataFrame:
            if energy_col not in local_df.columns:
                # compute with defaults if not present
                m = pd.to_numeric(local_df["magnitude"], errors="coerce")
                local_df[energy_col] = np.where(m.notna(), np.power(10.0, 1.44 + 5.24 * m), np.nan)
            return local_df

        result: pd.DataFrame

        if mode == "daily_max_mag":
            idx = df.groupby("__day")["magnitude"].idxmax()
            result = df.loc[idx, :].copy()
            result["event_count"] = df.groupby("__day")["event_id"].transform("count").loc[idx].values
            # Normalize 'time' to day 00:00
            result["time"] = result["__day"]
            result = result.drop(columns=["__day"])

        elif mode == "daily_mag_threshold":
            if threshold is None:
                raise ValueError("threshold must be provided for 'daily_mag_threshold'")
            sub = df[df["magnitude"] >= float(threshold)]
            if sub.empty:
                # construct empty daily frame later with fill_empty_days
                result = sub.copy()
            else:
                idx = sub.groupby("__day")["magnitude"].idxmax()
                result = sub.loc[idx, :].copy()
                result["event_count"] = df.groupby("__day")["event_id"].size().reindex(result["__day"]).values
                result["time"] = result["__day"]
                result = result.drop(columns=["__day"])

        elif mode in ("daily_energy_sum", "daily_energy_max"):
            df = _ensure_energy(df)
            agg_fn = "sum" if mode == "daily_energy_sum" else "max"
            grp = df.groupby("__day")
            out = grp.agg(
                energy_J=(energy_col, agg_fn),
                event_count=("event_id", "count"),
                magnitude=("magnitude", "max"),  # keep daily max magnitude as reference
            ).reset_index(names="time")

            result = out.copy()
            ts = pd.to_datetime(result["time"], utc=False)

            # Ensure tz-aware 'time'
            if getattr(ts.dt, "tz", None) is None:
                ts = ts.dt.tz_localize(DEFAULT_TZ)
            else:
                ts = ts.dt.tz_convert(DEFAULT_TZ)
            result["time"] = ts

        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Fill missing days, if requested
        if fill_empty_days:

            if start is None:
                start_day = (
                    (df["__day"].min() if not df.empty else pd.Timestamp.now(tz=DEFAULT_TZ))
                    .floor("D")
                )
            else:
                start_day = pd.Timestamp(start, tz=DEFAULT_TZ).floor("D")
            if end is None:
                end_day = (
                    (df["__day"].max() if not df.empty else start_day)
                    .floor("D")
                )
            else:
                end_day = pd.Timestamp(end, tz=DEFAULT_TZ).floor("D")

            full_idx = pd.date_range(start=start_day, end=end_day, freq="D", tz=DEFAULT_TZ)
            result = result.set_index("time").reindex(full_idx).rename_axis("time").reset_index()

            # Empty-day defaults
            if "energy_J" in result.columns:
                result["energy_J"] = result["energy_J"].fillna(0.0)
            result["event_count"] = result.get("event_count", pd.Series(index=result.index)).fillna(0).astype(int)
            if "magnitude" in result.columns:
                # magnitude stays NaN for empty days
                pass

        # Keep canonical columns if present; otherwise return what we have
        self._df = result
        return self

    # ------------- Helpers -------------
    @staticmethod
    def _normalize_record(r: Dict[str, Any]) -> Dict[str, Any]:
        """Map heterogeneous AFAD keys to our canonical schema."""
        def g(*names: str) -> Any:
            for n in names:
                if n in r:
                    return r[n]
            return None

        out = {
            "event_id": g("eventid", "eventId", "eventID", "id"),
            "time": g("time", "date", "datetime", "eventDate", "lastOccurrenceTime"),
            "latitude": g("latitude", "lat"),
            "longitude": g("longitude", "lon", "lng"),
            "depth_km": g("depth_km", "depth"),
            "magnitude": g("magnitude", "mag"),
            "mag_type": g("type", "magType"),
            "location": g("location", "title", "place"),
            "province": g("province", "il"),
            "district": g("district", "ilce"),
            "country": g("country"),
            "neighborhood": g("neighborhood", "mahalle"),
            "rms": g("rms"),
            "is_event_update": g("iseventupdate", "isEventUpdate"),
            "last_update_time": g("lastupdatedate", "lastUpdate", "last_update_time"),
        }
        # Ensure every canonical field exists even if None (already covered by dict keys above)
        return out
