"""
tune_detectors.py - Phase 3: check the baselines, try many detector
settings on the TUNING files, pick one setting per detector, and plot.

Uses ONLY the tuning files and the anomaly-free file. Test files are never
loaded (there is a safety check below).

How a setting is scored (see detectors.py for the details):
  - Only readings AFTER the 5-minute baseline are scored (the detector
    learned from the baseline, so scoring it there would be cheating).
  - The 235 readings with conflicting labels are never scored.
  - Precision, recall and false-alarm rate are counted per second.
  - We also count how many of the 24 tuning faults got at least one alarm,
    how many separate false alarms there were, and what share of the time
    the anomaly-free run spends in alarm.

Outputs:
  reports/phase3_baseline_check.csv        - is the baseline window normal?
  reports/phase3_tuning_results.csv        - every setting tried, with scores
  reports/phase3_alarms_tuning.csv         - every alarm of the chosen settings,
                                             with the sensor(s) that caused it
  reports/phase3_alarms_per_experiment.csv - fault caught? which sensors?
  figures/f_..., g_...                     - alarms drawn over the sensor data

Run it AFTER clean_data.py and make_split.py, from the project folder:
    .venv/bin/python src/tune_detectors.py
"""

import itertools

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.transforms as mtransforms
import pandas as pd

from common import (ANOMALY_COLOUR, FIGURES_DIR, NORMAL_COLOUR, REPORTS_DIR,
                    SENSOR_LABELS, SPLIT_FILE, load_clean_data)
from detectors import (BASELINE_SECONDS, DETECTOR_SENSORS, alarm_events,
                       apply_persistence, baseline_mask, baseline_stats,
                       rolling_flags, rolling_values, score, threshold_flags)

# Which sensors a detector listens to. The temperatures drift slowly in
# normal running (Phase 2), so we try the detectors with and without them.
SENSOR_SETS = {
    "all 7": DETECTOR_SENSORS,
    "no temperatures": [s for s in DETECTOR_SENSORS
                        if s not in ("Temperature", "Thermocouple")],
}

# Settings to try. k and m are in "baseline standard deviations",
# window and N are in seconds.
THRESHOLD_GRID = {"sensors": list(SENSOR_SETS), "k": [3, 4, 5, 6, 8],
                  "n": [0, 5, 10, 20, 30]}
ROLLING_GRID = {"sensors": list(SENSOR_SETS), "window": [30, 60, 120],
                "k": [3, 5, 8], "m": [2, 3, 5], "n": [0, 10, 30]}

NORMAL_REFERENCE = "anomaly-free/anomaly-free"

# The fault experiments run about 15 minutes after their baseline, so for a
# fair comparison we also measure the anomaly-free run over its first
# 15 minutes after the baseline (as well as over the whole run).
COMPARABLE_SECONDS = 15 * 60

# A baseline shorter than this (because of a gap) is reported.
SHORT_BASELINE_SECONDS = 240

# How we pick ONE setting per detector (see reports/phase3_detectors.md):
# false alarms waste maintenance time and make people ignore alarms, so we
# first cap them, then catch as much of the faults as possible.
MAX_FALSE_ALARM_RATE = 0.05     # at most 5% of normal seconds in alarm
MAX_FALSE_ALARM_EVENTS = 24     # at most 1 false alarm per tuning file on average

# Colours for the two detectors' alarms in the plots.
THRESHOLD_COLOUR = "#4a3aa7"   # violet
ROLLING_COLOUR = "#1baf7a"     # aqua


# ---------------------------------------------------------------------------
# Loading and baseline check
# ---------------------------------------------------------------------------

def load_experiments():
    """Return {experiment_id: rows} for the tuning files + anomaly-free file."""
    data = load_clean_data()
    split = pd.read_csv(SPLIT_FILE)
    data = data.merge(split[["experiment_id", "role"]], on="experiment_id")
    data = data[data["role"].isin(["tuning", "normal_reference"])]
    assert "test" not in set(data["role"]), "Test data must not be used in Phase 3!"
    return {e: rows for e, rows in data.groupby("experiment_id")}


def check_baselines(experiments):
    """For every file: is the baseline window fully labelled normal?"""
    checks = []
    for experiment_id, rows in experiments.items():
        base = rows[baseline_mask(rows)]
        _, std = baseline_stats(rows)
        anomaly_rows = int((base["anomaly"] == 1).sum())
        conflict_rows = int(base["flag_label_conflict"].sum())
        # Time actually covered by readings (a gap can cut this short).
        covered = (base["datetime"].iloc[-1] - base["datetime"].iloc[0]).total_seconds()
        if base["anomaly"].isna().all():
            verdict = "no labels (file described as normal only)"
        elif anomaly_rows == 0 and conflict_rows == 0:
            verdict = "fully labelled normal"
        else:
            verdict = "NOT fully normal"
        if covered < SHORT_BASELINE_SECONDS:
            verdict += f"; SHORT: readings cover only {covered:.0f} s (time gap)"
        checks.append({
            "experiment_id": experiment_id,
            "baseline_readings": len(base),
            "seconds_covered": covered,
            "labelled_anomaly": anomaly_rows,
            "conflicting_labels": conflict_rows,
            "large_gaps": int(base["flag_large_gap_before"].sum()),
            "sensors_with_zero_std": ", ".join(std[std == 0].index),
            "verdict": verdict,
        })
    return pd.DataFrame(checks)


# ---------------------------------------------------------------------------
# Running and scoring one setting
# ---------------------------------------------------------------------------

def run_setting(experiments, rolling_cache, detector, setting):
    """Run one detector setting on every file and return its scores + alarms."""
    scored_parts = []
    all_events = []
    faults_detected = 0
    delays = []

    for experiment_id, rows in experiments.items():
        sensor_alarms = run_detector(rows, rolling_cache, detector, setting)

        # Only score what comes after the baseline.
        after = ~baseline_mask(rows)
        events = alarm_events(rows[after], sensor_alarms[after])
        all_events += events

        if experiment_id == NORMAL_REFERENCE:
            # Share of time in alarm: first 15 minutes after baseline, and overall.
            in_alarm = sensor_alarms.any(axis=1)[after]
            seconds = (rows["datetime"] - rows["datetime"].iloc[0]).dt.total_seconds()[after]
            first_part = seconds < BASELINE_SECONDS + COMPARABLE_SECONDS
            normal_share_15min = in_alarm[first_part].mean()
            normal_share_all = in_alarm.mean()
            continue

        scored = after & ~rows["flag_label_conflict"]
        part = pd.DataFrame({"alarm": sensor_alarms.any(axis=1)[scored],
                             "anomaly": rows.loc[scored, "anomaly"]})
        scored_parts.append(part)

        # Was this fault caught? If so, how many seconds after it started?
        in_fault = part[part["anomaly"] == 1]
        if in_fault["alarm"].any():
            faults_detected += 1
            fault_start = rows.loc[in_fault.index[0], "datetime"]
            first_alarm = rows.loc[in_fault.index[in_fault["alarm"].to_numpy()][0], "datetime"]
            delays.append((first_alarm - fault_start).total_seconds())

    result = score(pd.concat(scored_parts))
    tuning_events = [e for e in all_events if e["experiment_id"] != NORMAL_REFERENCE]
    result.update({
        "faults_detected": faults_detected,
        "median_delay_s": pd.Series(delays).median(),
        "false_alarm_events": sum(not e["overlaps_labelled_anomaly"] for e in tuning_events),
        "anomaly_free_in_alarm_15min": normal_share_15min,
        "anomaly_free_in_alarm_all": normal_share_all,
    })
    return result, all_events


def run_detector(rows, rolling_cache, detector, setting):
    """Run one detector setting on one file; return per-sensor alarms."""
    if detector == "threshold":
        flags = threshold_flags(rows, setting["k"])
    else:
        mean, std = rolling_cache[(rows["experiment_id"].iloc[0], setting["window"])]
        flags = rolling_flags(rows, mean, std, setting["k"], setting["m"])
    flags = flags[SENSOR_SETS[setting["sensors"]]]  # keep only the chosen sensors
    return apply_persistence(flags, rows, setting["n"])


def try_all_settings(experiments, rolling_cache):
    """Run every setting in both grids and return one results table."""
    rows = []
    for detector, grid in [("threshold", THRESHOLD_GRID), ("rolling", ROLLING_GRID)]:
        names = list(grid)
        for values in itertools.product(*grid.values()):
            setting = dict(zip(names, values))
            result, _ = run_setting(experiments, rolling_cache, detector, setting)
            rows.append({"detector": detector, **setting, **result})
    return pd.DataFrame(rows)


def choose_setting(results, detector):
    """Among settings within both false-alarm limits, take the highest recall
    (ties: more faults detected)."""
    allowed = results[(results["detector"] == detector)
                      & (results["false_alarm_rate"] <= MAX_FALSE_ALARM_RATE)
                      & (results["false_alarm_events"] <= MAX_FALSE_ALARM_EVENTS)]
    best = allowed.sort_values(["recall", "faults_detected"], ascending=False).iloc[0]
    grid = THRESHOLD_GRID if detector == "threshold" else ROLLING_GRID
    return {name: best[name] if name == "sensors" else int(best[name]) for name in grid}


def describe(detector, setting):
    """Short text for a setting, e.g. for plot titles."""
    if detector == "threshold":
        return (f"threshold: k={setting['k']}, N={setting['n']} s, "
                f"sensors: {setting['sensors']}")
    return (f"rolling: window={setting['window']} s, k={setting['k']}, m={setting['m']}, "
            f"N={setting['n']} s, sensors: {setting['sensors']}")


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def shade_runs(ax, times, mask, **style):
    """Shade every continuous stretch where mask is True."""
    starts = mask & ~mask.shift(1, fill_value=False)
    ends = mask & ~mask.shift(-1, fill_value=False)
    for start, end in zip(times[starts], times[ends]):
        ax.axvspan(start, end, **style)


def plot_alarms(rows, alarms_by_detector, settings_text, filename):
    """Each sensor over time, with two strips under the line showing when
    each detector had THAT sensor in alarm."""
    fig, axes = plt.subplots(len(DETECTOR_SENSORS), 1, figsize=(10, 12), sharex=True)
    times = rows["datetime"]
    in_baseline = baseline_mask(rows)
    for ax, sensor in zip(axes, DETECTOR_SENSORS):
        shade_runs(ax, times, in_baseline, color="#c3c2b7", alpha=0.25, lw=0)
        shade_runs(ax, times, rows["anomaly"] == 1, color=ANOMALY_COLOUR, alpha=0.15, lw=0)
        ax.plot(times, rows[sensor], color=NORMAL_COLOUR, lw=0.8)
        used = any(sensor in alarms.columns for alarms in alarms_by_detector.values())
        label = SENSOR_LABELS[sensor] + ("" if used else "\n(not used by detectors)")
        ax.set_ylabel(label, rotation=0, ha="right", va="center")
        ax.margins(y=0.35)  # leave room at the bottom for the alarm strips
        # Strips use data x-coordinates but a fixed height inside the plot.
        strip = mtransforms.blended_transform_factory(ax.transData, ax.transAxes)
        for (name, alarms), y, colour in zip(alarms_by_detector.items(), [0.10, 0.02],
                                             [THRESHOLD_COLOUR, ROLLING_COLOUR]):
            if sensor not in alarms.columns:
                continue
            on = alarms[sensor]
            starts, ends = times[on & ~on.shift(1, fill_value=False)], times[on & ~on.shift(-1, fill_value=False)]
            for start, end in zip(starts, ends):
                ax.fill_between([start, end + pd.Timedelta(seconds=1)], y, y + 0.06,
                                color=colour, lw=0, transform=strip)

    # Legend built by hand, because the strips and shading have no labels.
    handles = [plt.Rectangle((0, 0), 1, 1, color="#c3c2b7", alpha=0.4),
               plt.Rectangle((0, 0), 1, 1, color=ANOMALY_COLOUR, alpha=0.25),
               plt.Rectangle((0, 0), 1, 1, color=THRESHOLD_COLOUR),
               plt.Rectangle((0, 0), 1, 1, color=ROLLING_COLOUR)]
    labels = ["baseline (first 5 min)", "labelled anomaly",
              "threshold detector alarm (upper strip)", "rolling detector alarm (lower strip)"]
    axes[0].legend(handles, labels, loc="lower left", bbox_to_anchor=(0, 1.02),
                   ncol=2, frameon=False)
    axes[-1].set_xlabel(f"Time on {times.iloc[0]:%Y-%m-%d} (HH:MM)")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.suptitle(f"Detector alarms for {rows['experiment_id'].iloc[0]} (pressure not used)\n"
                 f"{settings_text}", x=0.01, ha="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"Saved figures/{filename}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pd.set_option("display.width", 220)
    experiments = load_experiments()
    print(f"Loaded {len(experiments)} files (tuning + anomaly-free); no test files.\n")

    # 1. Baseline check
    checks = check_baselines(experiments)
    checks.to_csv(REPORTS_DIR / "phase3_baseline_check.csv", index=False)
    print(checks.to_string(index=False), "\n")

    # Rolling values only depend on the window, so compute them once.
    rolling_cache = {(e, w): rolling_values(rows, w)
                     for e, rows in experiments.items() for w in ROLLING_GRID["window"]}

    # 2. Try every setting
    results = try_all_settings(experiments, rolling_cache)
    results.round(4).to_csv(REPORTS_DIR / "phase3_tuning_results.csv", index=False)
    print(f"Tried {len(results)} settings; all saved to reports/phase3_tuning_results.csv\n")

    # 3. Pick one setting per detector and list all of its alarms
    chosen = {d: choose_setting(results, d) for d in ["threshold", "rolling"]}
    alarm_tables = []
    for detector, setting in chosen.items():
        result, events = run_setting(experiments, rolling_cache, detector, setting)
        print(f"Chosen {describe(detector, setting)}")
        print("   " + ", ".join(f"{name}={value:.3f}" if isinstance(value, float)
                                else f"{name}={value}" for name, value in result.items()))
        table = pd.DataFrame(events)
        table.insert(0, "detector", detector)
        table.insert(1, "setting", describe(detector, setting))
        alarm_tables.append(table)
    alarms = pd.concat(alarm_tables, ignore_index=True)
    alarms.to_csv(REPORTS_DIR / "phase3_alarms_tuning.csv", index=False)
    print(f"\nSaved {len(alarms)} alarms to reports/phase3_alarms_tuning.csv")

    # Per experiment: how many alarms matched a labelled fault, and which
    # sensors raised them (needed later for the maintenance summary).
    per_file = []
    for experiment_id in experiments:
        if experiment_id == NORMAL_REFERENCE:
            continue
        for detector in chosen:
            mine = alarms[(alarms["experiment_id"] == experiment_id)
                          & (alarms["detector"] == detector)]
            hits = mine[mine["overlaps_labelled_anomaly"] == True]  # noqa: E712
            sensors = sorted({s for text in hits["sensors"] for s in text.split(", ")})
            per_file.append({
                "experiment_id": experiment_id,
                "detector": detector,
                "fault_detected": len(hits) > 0,
                "fault_alarms": len(hits),
                "false_alarms": len(mine) - len(hits),
                "sensors_in_fault_alarms": ", ".join(sensors),
            })
    per_file = pd.DataFrame(per_file)
    per_file.to_csv(REPORTS_DIR / "phase3_alarms_per_experiment.csv", index=False)
    print(per_file.to_string(index=False))

    # 4. Plots: valve1/0 (Phase 2 example) and the first rotor-imbalance
    # file in the tuning set (other/5).
    FIGURES_DIR.mkdir(exist_ok=True)
    settings_text = describe("threshold", chosen["threshold"]) + "  |  " + \
        describe("rolling", chosen["rolling"])
    for experiment_id, prefix in [("valve1/0", "f"), ("other/5", "g")]:
        rows = experiments[experiment_id]
        alarms_by_detector = {d: run_detector(rows, rolling_cache, d, s)
                              for d, s in chosen.items()}
        plot_alarms(rows, alarms_by_detector, settings_text,
                    f"{prefix}_detector_alarms_{experiment_id.replace('/', '_')}.png")


if __name__ == "__main__":
    main()
