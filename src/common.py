"""
common.py - settings shared by all the Phase 2+ scripts.

Keeping file paths and sensor names in ONE place means every script uses
the same values, and a change only has to be made here.
"""

from pathlib import Path

import pandas as pd

# The project folder is one level above this file's folder (src/).
# Building paths from this file's location means the scripts work no matter
# which folder you run them from.
PROJECT_DIR = Path(__file__).resolve().parent.parent

RAW_DIR = PROJECT_DIR / "data" / "raw" / "SKAB"
PROCESSED_DIR = PROJECT_DIR / "data" / "processed"
FIGURES_DIR = PROJECT_DIR / "figures"
REPORTS_DIR = PROJECT_DIR / "reports"

CLEAN_FILE = PROCESSED_DIR / "skab_clean.csv"
CLEANING_LOG_FILE = PROCESSED_DIR / "cleaning_log.csv"
SPLIT_FILE = PROCESSED_DIR / "split.csv"

# The 8 sensor columns, with a readable label and unit for plots.
# Units come from the official SKAB README (see README.md, Data Sources).
SENSOR_LABELS = {
    "Accelerometer1RMS": "Vibration 1, RMS (g)",
    "Accelerometer2RMS": "Vibration 2, RMS (g)",
    "Current": "Motor current (A)",
    "Pressure": "Loop pressure (bar)",
    "Temperature": "Motor temperature (°C)",
    "Thermocouple": "Fluid temperature (°C)",
    "Voltage": "Motor voltage (V)",
    "Volume Flow RateRMS": "Flow rate (L/min)",
}
SENSORS = list(SENSOR_LABELS)

# Plot colours, used the same way in every figure:
# blue = normal behaviour, orange = labelled anomaly.
NORMAL_COLOUR = "#2a78d6"
ANOMALY_COLOUR = "#eb6834"


def load_clean_data():
    """Load the cleaned data made by clean_data.py."""
    return pd.read_csv(CLEAN_FILE, parse_dates=["datetime"])
