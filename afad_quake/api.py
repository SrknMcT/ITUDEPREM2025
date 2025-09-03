from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple, Union

import httpx

from constants import (
    BASE_URL, API_ROOT, ENDPOINT_LATEST, ENDPOINT_FILTER,
    DEFAULT_TIMEOUT, DEFAULT_TZ
)
from logger import get_logger

try:
    # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

# Types
BBox = Tuple[float, float, float, float]          # (min_lat, min_lon, max_lat, max_lon)
Radius = Tuple[float, float, float]               # (center_lat, center_lon, radius_km)
OrderBy = Literal["timedesc", "timeasc", "magnitude", "depth"]

class AfadAPI:
    """
    Low-level AFAD 'event-service' client.

    This class encapsulates HTTP concerns (base URL, timeouts) and exposes
    minimal methods to retrieve earthquake events. Higher-level filtering,
    energy conversion, and DataFrame shaping will be built on top in later steps.

    Notes
    -----
    - Default timezone is Europe/Istanbul for day-based operations.
    - Returned raw records will be post-processed by a higher-level Dataset class.

    Parameters
    ----------
    base_url : str, optional
        Base host, e.g., "https://deprem.afad.gov.tr". Can be overridden if the
        service is served via an API gateway.
    timeout : float, optional
        HTTP timeout in seconds.
    client : httpx.Client, optional
        An existing httpx client. If not provided, a new client will be created.

    Examples
    --------
    >>> from api import AfadAPI
    >>> api = AfadAPI()
    >>> # this will implement the HTTP calls below:
    >>> # latest = api.fetch_latest(limit=500)
    >>> # items = api.fetch_by_filter(
    ... #     start="2025-01-01T00:00:00",
    ... #     end="2025-01-15T23:59:59",
    ... #     orderby="timedesc",
    ... # )
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._logger = get_logger()
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self._client = client  # We'll create one lazily if not provided.

    # ---------- Lifecycle ----------
    def _ensure_client(self) -> httpx.Client:
        self._client = httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "afad-quake/0.1 (+https://example.local)",
            },
        )
        return self._client

    def close(self) -> None:
        """Close the underlying HTTP client if we created it."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "AfadAPI":
        self._ensure_client()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------- URL helpers ----------
    def _url(self, endpoint: str) -> str:
        return f"{self.base_url}{API_ROOT}{endpoint}"

    # ---------- Time helpers ----------
    @staticmethod
    def _to_iso8601(
        dt: Union[str, _dt.datetime, _dt.date],
        *,
        assume_tz: str = DEFAULT_TZ,
    ) -> str:
        """
        Convert input into ISO8601 string (no timezone suffix), suitable for AFAD filters.

        AFAD endpoints commonly accept e.g. "2025-01-01T00:00:00".
        If a naive datetime is provided, we assume `assume_tz` then drop tz info.

        Parameters
        ----------
        dt : Union[str, datetime, date]
            The input date/time.
        assume_tz : str
            Timezone name to assume for naive datetime inputs.

        Returns
        -------
        str
            ISO string like "YYYY-MM-DDTHH:MM:SS".
        """
        if isinstance(dt, str):
            return dt
        if isinstance(dt, _dt.date) and not isinstance(dt, _dt.datetime):
            # Interpret date as local midnight start
            dt = _dt.datetime.combine(dt, _dt.time(0, 0, 0))
        if isinstance(dt, _dt.datetime):
            if dt.tzinfo is None:
                if ZoneInfo is not None:
                    dt = dt.replace(tzinfo=ZoneInfo(assume_tz))
            else:
                if ZoneInfo is not None:
                    dt = dt.astimezone(ZoneInfo(assume_tz))

            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        raise TypeError(f"Unsupported dt type: {type(dt)!r}")


    @staticmethod
    def _validate_bbox(bbox: BBox) -> None:
        min_lat, min_lon, max_lat, max_lon = bbox
        if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
            raise ValueError("Latitude must be in [-90, 90].")
        if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
            raise ValueError("Longitude must be in [-180, 180].")
        if max_lat <= min_lat or max_lon <= min_lon:
            raise ValueError("Invalid bbox: require max_lat>min_lat and max_lon>min_lon.")

    @staticmethod
    def _validate_radius(radius: Radius) -> None:
        lat, lon, r_km = radius
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError("Center (lat, lon) out of range.")
        if r_km <= 0:
            raise ValueError("Radius (km) must be positive.")

    # ---------- HTTP helper ----------
    def _get_json(self, url: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        client = self._ensure_client()
        self._logger.debug("GET %s params=%s", url, params)
        try:
            resp = client.get(url, params=params)
        except httpx.RequestError as e:
            raise RuntimeError(f"AFAD request error: {e!r}") from e

        if resp.status_code != 200:
            # AFAD sometimes returns text/html messages for invalid params
            raise RuntimeError(
                f"AFAD HTTP {resp.status_code}: {resp.text[:300]}"
            )
        if resp.status_code == 204:
            return []

        # The endpoint typically returns a JSON array of events.
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"AFAD returned non-JSON payload: {resp.text[:300]}") from e

        if isinstance(data, dict) and "data" in data:
            # Defensive: in case it's wrapped
            return data["data"]  # type: ignore[return-value]
        if isinstance(data, list):
            return data  # type: ignore[return-value]

        raise RuntimeError(f"Unexpected AFAD response type: {type(data)!r}")

    def fetch_by_filter(
        self,
        *,
        start: Union[str, _dt.datetime, _dt.date],
        end: Union[str, _dt.datetime, _dt.date],
        orderby: OrderBy = "timedesc",
        limit: Optional[int] = None,
        # Spatial filters (choose one style):
        bbox: Optional[BBox] = None,          # (min_lat, min_lon, max_lat, max_lon)
        radius: Optional[Radius] = None,      # (lat, lon, radius_km)
        # Direct parameter pass-through (advanced):
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch earthquakes by time window and optional spatial filters.

        Parameters
        ----------
        start, end : str | datetime | date
            Inclusive start and end bounds (interpreted in Europe/Istanbul by default).
            Will be formatted as "YYYY-MM-DDTHH:MM:SS".
        orderby : {'timedesc','timeasc','magnitude','depth'}
            Sort order as supported by the service.
        limit : int, optional
            Maximum number of records to return (if supported by the endpoint).
        bbox : tuple(min_lat, min_lon, max_lat, max_lon), optional
            Bounding box filter.
        radius : tuple(lat, lon, radius_km), optional
            Radial search filter (in kilometers).
        extra_params : dict, optional
            Power users can pass raw query params (e.g., eventID).

        Returns
        -------
        List[Dict[str, Any]]
            Raw event objects as returned by the service.

        Examples
        --------
        >>> api = AfadAPI()
        >>> # Istanbul TZ day range:
        >>> events = api.fetch_by_filter(
        ...     start="2025-05-13T00:00:00",
        ...     end="2025-05-13T23:59:59",
        ...     orderby="timedesc",
        ... )
        >>> len(events)
        42  # for example
        """

        if bbox and radius:
            raise ValueError("Provide either 'bbox' or 'radius', not both.")

        start_iso = self._to_iso8601(start)
        end_iso = self._to_iso8601(end)

        params: Dict[str, Any] = {
            "start": start_iso,
            "end": end_iso,
            "orderby": orderby,
        }
        if limit is not None:
            params["limit"] = int(limit)

        # Spatial filters
        if bbox is not None:
            self._validate_bbox(bbox)
            min_lat, min_lon, max_lat, max_lon = bbox
            # AFAD filter param names (as observed in open-source tooling & examples)
            params.update({
                "minlat": min_lat,
                "maxlat": max_lat,
                "minlon": min_lon,
                "maxlon": max_lon,
            })
        elif radius is not None:
            self._validate_radius(radius)
            lat, lon, r_km = radius
            # AFAD filter supports circular search with lat/lon and radius.
            # Some docs mention minrad/maxrad where minrad can be empty (meaning circular).
            params.update({
                "lat": lat,
                "lon": lon,
                "maxrad": r_km,
                "minrad": 0,
            })

        if extra_params:
            # User-provided params take precedence
            params.update(extra_params)

        url = self._url(ENDPOINT_FILTER)
        items = self._get_json(url, params)
        self._logger.info(
            "Fetched %d events for window %s..%s (orderby=%s)",
            len(items), start_iso, end_iso, orderby
        )

        return items

    def fetch_latest(
            self,
            *,
            limit: int = 500,
            window_hours: int = 24,
            fallback_to_filter: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Fetch the most recent earthquakes.

        If the /event/latest endpoint is unavailable on this deployment (404/405/…),
        optionally fall back to /event/filter for the last `window_hours`.

        Parameters
        ----------
        limit : int, optional
            Desired number of items (server may cap).
        window_hours : int, optional
            Time window for the fallback filter call (default 24).
        fallback_to_filter : bool, optional
            If True, call /event/filter with [now-window_hours, now] when /latest fails.

        Returns
        -------
        List[Dict[str, Any]]
        """
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = int(limit)

        url = self._url(ENDPOINT_LATEST)
        try:
            items = self._get_json(url, params)
            self._logger.info("Fetched %d latest events via /event/latest", len(items))
            return items
        except RuntimeError as e:
            msg = str(e)
            self._logger.warning("Latest endpoint failed: %s", msg)

            if not fallback_to_filter:
                raise

            # Fallback: use /event/filter with a recent window (Istanbul time)
            now = _dt.datetime.now(tz=ZoneInfo(DEFAULT_TZ)) if ZoneInfo else _dt.datetime.now()
            start_dt = now - _dt.timedelta(hours=window_hours)

            start_iso = self._to_iso8601(start_dt)
            end_iso = self._to_iso8601(now)

            self._logger.info(
                "Falling back to /event/filter window=%s..%s orderby=timedesc limit=%s",
                start_iso, end_iso, limit
            )
            return self.fetch_by_filter(
                start=start_iso,
                end=end_iso,
                orderby="timedesc",
                limit=limit,
            )