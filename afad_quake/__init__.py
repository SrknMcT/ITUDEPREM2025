"""
afad_quake
A tiny client to query AFAD 'event-service' and transform results into pandas DataFrames.
"""

__version__ = "0.1.0"

from .api import AfadAPI
from .dataset import EarthquakeDataset

__all__ = ["AfadAPI", "EarthquakeDataset"]