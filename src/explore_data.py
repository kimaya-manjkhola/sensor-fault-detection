"""
explore_data.py - Phase 2: summary statistics and plots.

Uses ONLY the normal reference (anomaly-free) file and the TUNING files.
The test files are never loaded here, so nothing we see now can influence
the detectors we will test on them later.

What this script does:
  1. Summary statistics per sensor (mean, std, min, max) for three sets of
     rows: the anomaly-free run, normal rows in tuning files, and anomalous
     rows in tuning files.
  2. For each tuning experiment, how far each sensor moves during the
     anomaly compared with that same experiment's normal rows.
  3. Rolling mean and rolling standard deviation for one example experiment.
  4. Saves the plots in figures/ and the tables in reports/.

Run it AFTER clean_data.py and make_split.py, from the project folder:
    .venv/bin/python src/explore_data.py
"""

import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (ANOMALY_COLOUR, FIGURE_WIDTH, FIGURES_DIR, NORMAL_COLOUR,
                    RAW_COLOUR, REPORTS_DIR, SENSOR_LABELS, SENSORS, SPLIT_FILE,
                    apply_style, load_clean_data, save_figure)

# Rolling window: 60 seconds (about 60 readings at 1 reading per second).
#  - Long enough to smooth out second-to-second sensor noise.
#  - Short compared with an anomaly period (about 400 s in most files),
#    so a change shows up within about a minute.
# The window is measured in TIME, not rows, so a gap in the data doesn't
# stretch it. It only looks BACKWARDS (past 60 s), which is what a
# detector running live on the machine could also do.
ROLLING_WINDOW = "60s"
# Don't report a rolling value until the window holds at least 30 readings;
# with fewer, the standard deviation is too unreliable.
ROLLING_MIN_READINGS = 30

# A mean shift of 2 or more normal standard deviations is used below as a
# simple, stated cut-off for "a clear change". It is a description of the
# data, not a detector setting.
CLEAR_SHIFT = 2.0

# Same look as every other figure in the project (see common.py).
apply_style()


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_explore_data():
    """Load the cleaned data and keep only the normal reference + tuning files."""
    data = load_clean_data()
    split = pd.read_csv(SPLIT_FILE)
    data = data.merge(split[["experiment_id", "role"]], on="experiment_id")
    data = data[data["role"].isin(["normal_reference", "tuning"])]
    # Safety check: stop if a test file somehow got through.
    assert "test" not in set(data["role"]), "Test data must not be explored!"
    return data, split


def comparison_sets(data):
    """Return the three sets of rows we compare.

    - Rows with conflicting labels in two files are left out, because we
      don't know whether they are normal or anomalous.
    - A reading stored in two files is counted once within each set.
    """
    usable = data[~data["flag_label_conflict"]]
    tuning = usable[usable["role"] == "tuning"]
    sets = {
        "anomaly-free run": usable[usable["role"] == "normal_reference"],
        "tuning, labelled normal": tuning[tuning["anomaly"] == 0],
        "tuning, labelled anomaly": tuning[tuning["anomaly"] == 1],
    }
    return {name: rows.drop_duplicates("datetime") for name, rows in sets.items()}


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def summary_statistics(sets):
    """Mean, std, min and max of every sensor for each set of rows."""
    tables = []
    for name, rows in sets.items():
        stats = rows[SENSORS].agg(["mean", "std", "min", "max"]).T
        stats.insert(0, "row_set", name)
        stats.insert(1, "rows", len(rows))
        tables.append(stats)
    table = pd.concat(tables).rename_axis("sensor").reset_index()
    return table.sort_values(["sensor", "row_set"], key=lambda s: s.map(
        {name: i for i, name in enumerate(SENSORS + list(sets))}))


def shift_per_experiment(data):
    """For each tuning experiment and sensor, compare anomaly vs normal rows.

    mean_shift = (anomaly mean - normal mean) / normal standard deviation
        How many "normal wobbles" the average moved. 0 = no change.
    std_ratio = anomaly std / normal std
        Above 1 means the signal got noisier during the anomaly.
    Both compare rows from the SAME experiment, so differences between
    experiments (e.g. a warmer day) don't get mixed in.
    """
    usable = data[(data["role"] == "tuning") & ~data["flag_label_conflict"]]
    results = []
    for experiment_id, rows in usable.groupby("experiment_id"):
        normal = rows[rows["anomaly"] == 0]
        anomaly = rows[rows["anomaly"] == 1]
        for sensor in SENSORS:
            normal_std = normal[sensor].std()
            if normal_std == 0:
                normal_std = np.nan  # avoid dividing by zero
            results.append({
                "experiment_id": experiment_id,
                "experiment_group": rows["experiment_group"].iloc[0],
                "sensor": sensor,
                "mean_shift": (anomaly[sensor].mean() - normal[sensor].mean()) / normal_std,
                "std_ratio": anomaly[sensor].std() / normal_std,
            })
    return pd.DataFrame(results)


def summarise_shifts(shifts):
    """Per fault group and sensor: typical shift and how many experiments
    show a clear rise or fall."""
    summary = shifts.groupby(["experiment_group", "sensor"], sort=False).agg(
        experiments=("mean_shift", "size"),
        median_mean_shift=("mean_shift", "median"),
        clear_rise=("mean_shift", lambda s: int((s >= CLEAR_SHIFT).sum())),
        clear_fall=("mean_shift", lambda s: int((s <= -CLEAR_SHIFT).sum())),
        median_std_ratio=("std_ratio", "median"),
    ).reset_index()
    return summary.round(2)


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

def rolling_mean_std(rows):
    """Rolling mean and std of every sensor over the past ROLLING_WINDOW."""
    rolling = rows.set_index("datetime")[SENSORS].rolling(
        ROLLING_WINDOW, min_periods=ROLLING_MIN_READINGS)
    return rolling.mean().reset_index(drop=True), rolling.std().reset_index(drop=True)


def shade_anomalies(ax, rows, label=None):
    """Shade every labelled anomaly period (consecutive rows with anomaly == 1)."""
    is_anomaly = (rows["anomaly"] == 1).fillna(False).to_numpy()
    times = rows["datetime"].to_numpy()
    # A new period starts wherever the label changes from 0 to 1.
    start = None
    for i, flag in enumerate(is_anomaly):
        if flag and start is None:
            start = times[i]
        last = i == len(is_anomaly) - 1
        if start is not None and (not flag or last):
            end = times[i] if flag else times[i - 1]
            ax.axvspan(start, end, color=ANOMALY_COLOUR, alpha=0.15, lw=0, label=label)
            label = None  # only label the first period, for the legend
            start = None


def sensors_over_time(rows, values, title, filename, colour=NORMAL_COLOUR,
                      shade=False, background=None):
    """One small plot per sensor, stacked, sharing the time axis.

    values      - table with one column per sensor (raw or rolling values)
    background  - optional raw values drawn faintly behind the main line
    """
    fig, axes = plt.subplots(len(SENSORS), 1, figsize=(FIGURE_WIDTH, 13), sharex=True)
    for ax, sensor in zip(axes, SENSORS):
        if background is not None:
            ax.plot(rows["datetime"], background[sensor], color=RAW_COLOUR, lw=0.8,
                    label="raw reading")
        ax.plot(rows["datetime"], values[sensor], color=colour, lw=1.2,
                label=f"{ROLLING_WINDOW} rolling mean" if background is not None else None)
        if shade:
            shade_anomalies(ax, rows, label="labelled anomaly")
        ax.set_ylabel(SENSOR_LABELS[sensor], rotation=0, ha="right", va="center")
    axes[-1].set_xlabel(f"Time on {rows['datetime'].iloc[0]:%Y-%m-%d} (HH:MM)")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    if shade or background is not None:
        axes[0].legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=3, frameon=False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    save_figure(fig, filename)


def distributions(sets, filename):
    """Histogram of each sensor: labelled-normal vs labelled-anomaly rows."""
    normal = sets["tuning, labelled normal"]
    anomaly = sets["tuning, labelled anomaly"]
    fig, axes = plt.subplots(2, 4, figsize=(FIGURE_WIDTH, 5.5))
    for ax, sensor in zip(axes.flat, SENSORS):
        # Same bins for both sets so the shapes can be compared fairly.
        bins = np.histogram_bin_edges(pd.concat([normal[sensor], anomaly[sensor]]), bins=60)
        # density=True scales each histogram to area 1, so the two sets can
        # be compared even though there are more normal rows.
        ax.hist(normal[sensor], bins=bins, density=True, histtype="step", lw=1.5,
                color=NORMAL_COLOUR, label=f"labelled normal ({len(normal):,} rows)")
        ax.hist(anomaly[sensor], bins=bins, density=True, histtype="step", lw=1.5,
                color=ANOMALY_COLOUR, label=f"labelled anomaly ({len(anomaly):,} rows)")
        ax.set_xlabel(SENSOR_LABELS[sensor])
        ax.set_yticks([])
        ax.grid(False)
    axes[0, 0].set_ylabel("Share of rows (density)")
    axes[1, 0].set_ylabel("Share of rows (density)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.01, 0.95), ncol=2)
    fig.suptitle("Sensor values in tuning experiments: labelled normal vs labelled anomaly",
                 x=0.01, ha="left", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.9))
    save_figure(fig, filename)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    FIGURES_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)
    pd.set_option("display.width", 200)

    data, split = load_explore_data()
    sets = comparison_sets(data)

    # 1. Summary statistics
    stats = summary_statistics(sets)
    stats.round(4).to_csv(REPORTS_DIR / "phase2_summary_stats.csv", index=False)
    print(stats.round(3).to_string(index=False), "\n")

    # 2. Per-experiment shifts
    shifts = shift_per_experiment(data)
    shifts.round(3).to_csv(REPORTS_DIR / "phase2_shift_per_experiment.csv", index=False)
    shift_summary = summarise_shifts(shifts)
    shift_summary.to_csv(REPORTS_DIR / "phase2_shift_summary.csv", index=False)
    print(shift_summary.to_string(index=False), "\n")

    # 3. Example experiment: the first valve1 file in the tuning set.
    # (valve1 is the largest fault group; we take the first one rather
    # than picking one that "looks good".)
    tuning_valve1 = split[(split["role"] == "tuning") & (split["experiment_group"] == "valve1")]
    example_id = tuning_valve1["experiment_id"].iloc[0]
    example = data[data["experiment_id"] == example_id].reset_index(drop=True)
    print(f"Example experiment: {example_id}")

    # Rolling values over the past 60 seconds of time.
    rolling_mean, rolling_std = rolling_mean_std(example)

    # 4. Plots. Noisy signals are easier to read with the 60-s rolling mean
    # (blue) drawn over the raw readings (grey).
    normal_run = data[data["role"] == "normal_reference"].reset_index(drop=True)
    normal_mean, _ = rolling_mean_std(normal_run)
    sensors_over_time(normal_run, normal_mean,
                      f"Anomaly-free run: all sensors over time ({ROLLING_WINDOW} rolling mean over raw readings)",
                      "a_anomaly_free_all_sensors.png", background=normal_run)

    safe_id = example_id.replace("/", "_")
    sensors_over_time(example, rolling_mean,
                      f"Fault experiment {example_id}: all sensors ({ROLLING_WINDOW} rolling mean "
                      "over raw readings), labelled anomaly shaded",
                      f"b_{safe_id}_all_sensors.png", shade=True, background=example)

    distributions(sets, "c_normal_vs_anomaly_distributions.png")

    sensors_over_time(example, rolling_std,
                      f"Fault experiment {example_id}: rolling standard deviation "
                      f"(past {ROLLING_WINDOW}), labelled anomaly shaded",
                      f"d_{safe_id}_rolling_std.png", shade=True)


if __name__ == "__main__":
    main()
