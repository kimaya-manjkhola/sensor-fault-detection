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

# ---------------------------------------------------------------------------
# Figure style, shared by every script so all figures look the same
# ---------------------------------------------------------------------------
# Colours always mean the same thing:
NORMAL_COLOUR = "#2a78d6"     # blue: a sensor's (smoothed) signal
RAW_COLOUR = "#c3c2b7"        # light grey: raw readings behind the smoothed line
ANOMALY_COLOUR = "#eb6834"    # orange: labelled anomaly / fault period
BASELINE_COLOUR = "#c3c2b7"   # grey shading: the 5-minute baseline
THRESHOLD_COLOUR = "#4a3aa7"  # violet: threshold detector
ROLLING_COLOUR = "#1baf7a"    # aqua: rolling detector
REFERENCE_COLOUR = "#8a8984"  # dark grey: reference values (e.g. flag everything)
TEXT_COLOUR = "#52514e"       # secondary text (labels, notes)
GRID_COLOUR = "#e5e5e3"

FIGURE_WIDTH = 10   # inches; every figure uses this width
DPI = 150


def apply_style():
    """Use the same fonts, sizes and axes style in every figure."""
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.size": 9,
        "axes.titlesize": 11,
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID_COLOUR,
        "axes.axisbelow": True,
        "axes.edgecolor": "#8a8984",
        "axes.labelcolor": TEXT_COLOUR,
        "xtick.color": TEXT_COLOUR,
        "ytick.color": TEXT_COLOUR,
        "legend.frameon": False,
        "savefig.dpi": DPI,
    })


def save_figure(fig, filename):
    """Save a figure into figures/ and close it."""
    FIGURES_DIR.mkdir(exist_ok=True)
    fig.savefig(FIGURES_DIR / filename)
    import matplotlib.pyplot as plt
    plt.close(fig)
    print(f"Saved figures/{filename}")


def load_clean_data():
    """Load the cleaned data made by clean_data.py."""
    return pd.read_csv(CLEAN_FILE, parse_dates=["datetime"])
