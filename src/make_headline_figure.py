"""
make_headline_figure.py - one clean figure for the README.

It shows a single TEST experiment (valve1/9, inlet valve partly closed),
only the sensor that matters for this fault (flow rate), the labelled
fault, and the alarms of the final rolling + rate detector.

valve1/9 was chosen because it is a test file (never used for tuning),
it is the most common fault type, and it shows one clear signal. Its one
false alarm is shown too, not hidden.

Run it AFTER tune_detectors.py, from the project folder:
    .venv/bin/python src/make_headline_figure.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from common import (ANOMALY_COLOUR, BASELINE_COLOUR, FIGURE_WIDTH, NORMAL_COLOUR, RAW_COLOUR,
                    ROLLING_COLOUR, TEXT_COLOUR, apply_style, load_clean_data, save_figure)
from detectors import BASELINE_SECONDS, rolling_values, seconds_since_start
from evaluate_test import FINAL_SETTINGS, build_cache
from tune_detectors import run_detector

EXPERIMENT = "valve1/9"
SENSOR = "Volume Flow RateRMS"
apply_style()


def runs(mask):
    """(start, end) positions of each continuous stretch where mask is True."""
    starts = mask & ~mask.shift(1, fill_value=False)
    ends = mask & ~mask.shift(-1, fill_value=False)
    return list(zip(mask.index[starts], mask.index[ends]))


def main():
    data = load_clean_data()
    rows = data[data["experiment_id"] == EXPERIMENT]
    seconds = seconds_since_start(rows)
    minutes = seconds / 60
    smooth, _ = rolling_values(rows, FINAL_SETTINGS["rolling"]["window"])

    cache = build_cache({EXPERIMENT: rows})
    alarms = run_detector(rows, cache, "rolling", FINAL_SETTINGS["rolling"]).any(axis=1)
    alarms &= seconds >= BASELINE_SECONDS  # nothing is scored inside the baseline
    fault = rows["anomaly"] == 1
    fault_start = minutes[fault].iloc[0]
    first_alarm = minutes[alarms & fault].iloc[0]

    fig, (ax, ax_alarm) = plt.subplots(2, 1, figsize=(FIGURE_WIDTH, 4.8), sharex=True,
                                       gridspec_kw={"height_ratios": [5, 1]})
    for axis in (ax, ax_alarm):
        axis.axvspan(0, BASELINE_SECONDS / 60, color=BASELINE_COLOUR, alpha=0.3, lw=0)
        axis.axvspan(fault_start, minutes[fault].iloc[-1], color=ANOMALY_COLOUR, alpha=0.15, lw=0)

    ax.plot(minutes, rows[SENSOR], color=RAW_COLOUR, lw=0.8, label="raw reading")
    ax.plot(minutes, smooth[SENSOR], color=NORMAL_COLOUR, lw=1.8, label="30-s rolling mean")
    ax.set_ylabel("Flow rate (L/min)")
    ax.text(0.2, ax.get_ylim()[1], "baseline:\nlearns 'normal'", va="top", fontsize=8,
            color=TEXT_COLOUR)
    ax.text(fault_start + 0.2, ax.get_ylim()[1], "labelled fault:\ninlet valve partly closed",
            va="top", fontsize=8, color=TEXT_COLOUR)
    ax.legend(loc="lower left")

    # Alarm row: one bar per alarm.
    for start, end in runs(alarms):
        ax_alarm.axvspan(minutes[start], minutes[end] + 1 / 60, ymin=0.2, ymax=0.8,
                         color=ROLLING_COLOUR, lw=0)
        if fault.loc[start:end].any():
            # Label inside the bar.
            ax_alarm.text((minutes[start] + minutes[end]) / 2, 0.5,
                          f"alarm starts {60 * (first_alarm - fault_start):.0f} s after the fault",
                          ha="center", va="center", fontsize=8, color="white")
        else:
            # Label to the left of a short alarm.
            ax_alarm.text(minutes[start] - 0.15, 0.5, "short false alarm", ha="right",
                          va="center", fontsize=8, color=TEXT_COLOUR)
    ax_alarm.set_yticks([0.5], ["alarm"])
    ax_alarm.set_ylim(0, 1)
    ax_alarm.grid(False)
    ax_alarm.set_xlabel("Minutes since the experiment started")
    ax_alarm.set_xlim(0, minutes.iloc[-1])

    fig.suptitle(f"Test experiment {EXPERIMENT}: flow drops when the inlet valve is partly "
                 "closed, and the rolling detector raises an alarm",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save_figure(fig, "headline_valve1_9.png")


if __name__ == "__main__":
    main()
