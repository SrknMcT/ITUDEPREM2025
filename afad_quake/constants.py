"""Library-wide constants and defaults."""

# Primary public site
BASE_URL = "https://deprem.afad.gov.tr"
API_ROOT = "/apiv2"

# Endpoints we target
ENDPOINT_LATEST = "/event/latest"
ENDPOINT_FILTER = "/event/filter"

# Some deployments also expose the service via an API gateway:
# Example observed path:
#   https://servisnet.afad.gov.tr/apigateway/deprem/apiv2/event/filter
# We'll keep the client flexible to allow overriding base_url if needed.

ALT_GATEWAY_HINT = "https://servisnet.afad.gov.tr/apigateway/deprem"

# Time / timezone
DEFAULT_TZ = "Europe/Istanbul"
DEFAULT_TIMEOUT = 15.0  # seconds

# Canonical column names we aim to deliver in DataFrames (present even if null)
CANONICAL_FIELDS = [
    "event_id",
    "time",              # ISO 8601
    "latitude",
    "longitude",
    "depth_km",
    "magnitude",
    "mag_type",
    "location",          # human readable
    "province",
    "district",
    "country",
    "neighborhood",
    "rms",
    "is_event_update",
    "last_update_time",
]
