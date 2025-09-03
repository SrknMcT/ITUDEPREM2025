from logger import configure_logging
from api import AfadAPI

configure_logging()

api = AfadAPI(base_url="https://servisnet.afad.gov.tr/apigateway/deprem")

# 1) latest earthquakes
latest = api.fetch_latest(limit=300)

# 2) earthquakes by date
events = api.fetch_by_filter(
    start="2025-08-01T00:00:00",
    end="2025-08-07T23:59:59",
    orderby="timedesc",
)

# 3) BBOX filter (Ege region)
ege = api.fetch_by_filter(
    start="2025-01-01T00:00:00",
    end="2025-01-31T23:59:59",
    bbox=(36.0, 26.0, 40.0, 29.5),  # (min_lat, min_lon, max_lat, max_lon)
    orderby="magnitude",
    extra_params={"minmag": 3.5},
)

# 4) circular search (İzmir center, 200 km)
izmir_circle = api.fetch_by_filter(
    start="2025-01-01T00:00:00",
    end="2025-01-31T23:59:59",
    radius=(38.4237, 27.1428, 200.0),  # lat, lon, km
    orderby="timedesc",
)
