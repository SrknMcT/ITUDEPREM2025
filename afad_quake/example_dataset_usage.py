from api import AfadAPI
from dataset import EarthquakeDataset
from logger import configure_logging

configure_logging()

api = AfadAPI(base_url="https://servisnet.afad.gov.tr/apigateway/deprem")
raw = api.fetch_by_filter(
    start="2025-08-01 00:00:00",
    end="2025-08-07 23:59:59",
    orderby="timedesc",
    extra_params={"minmag": 3.5},
)

ds = (EarthquakeDataset.from_records(raw)
        .filter_by_magnitude(min_mag=2.0)
        .convert_energy()  # E = 10 ** (1.44 + 5.24*M)
        .aggregate_daily(mode="daily_energy_sum", fill_empty_days=True))

ds.save("quakes.csv", fmt="csv")
