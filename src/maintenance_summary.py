"""
maintenance_summary.py - Phase 5: alarm log and investigation priority.

Uses the ROLLING + RATE detector (the final Phase 3b setting, chosen
because it did best on the tuning set) on every experiment.

Steps:
  1. Alarm log: one row per alarm, with the sensors that caused it, how far
     they went beyond normal, and a plain-English reason.
  2. Priority score per experiment, built ONLY from the alarms (duration,
     severity, number of sensors). The anomaly labels are NOT used, because
     a real maintenance team would not have them.
  3. Afterwards, a separate check of the ranking against the labels.
  4. Three charts.

Every experiment is monitored from the end of its 5-minute baseline to the
end of the file, for at most 20 minutes (see MONITOR_SECONDS). Otherwise
the 2.8-hour anomaly-free run would collect far more alarm time just for
being longer.

Outputs:
  reports/alarm_log.csv          - every alarm in the monitoring window
  reports/priority_ranking.csv   - experiments ranked by priority score
  figures/k_, l_, m_ figures     - timeline, top-10 scores, alarms per sensor

Run it AFTER tune_detectors.py, from the project folder:
    .venv/bin/python src/maintenance_summary.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import (ANOMALY_COLOUR, BASELINE_COLOUR, FIGURE_WIDTH, NORMAL_COLOUR, REPORTS_DIR,
                    ROLLING_COLOUR, SPLIT_FILE, TEXT_COLOUR, apply_style, load_clean_data,
                    save_figure)
from detectors import (BASELINE_SECONDS, DETECTOR_SENSORS, TEMPERATURE_SENSORS,
                       baseline_mask, baseline_stats, seconds_since_start)
from evaluate_test import FINAL_SETTINGS, build_cache, fault_type
from tune_detectors import run_detector

apply_style()

DETECTOR = "rolling"
SETTING = FINAL_SETTINGS[DETECTOR]

# Monitoring window: from the end of the baseline to the end of the file,
# but at most 20 minutes after the baseline. The longest fault experiment is
# 1398 s (23.3 min) long, so every fault experiment is watched to its end,
# while the 2.8-hour anomaly-free run is cut to the same maximum length.
# (An earlier 15-minute window cut off the end of other/4 and other/10.)
# The window does not use the labels.
MONITOR_SECONDS = 20 * 60
WINDOW_END = BASELINE_SECONDS + MONITOR_SECONDS

# Weightings tried in the sensitivity check: (duration, severity, sensors).
WEIGHTINGS = {
    "equal (used)": (1, 1, 1),
    "duration-heavy": (2, 1, 1),
    "severity-heavy": (1, 2, 1),
    "sensors-heavy": (1, 1, 2),
}

# Signals the detector watches: 5 sensors directly + 2 temperature rates.
WATCHED = [s for s in DETECTOR_SENSORS if s not in TEMPERATURE_SENSORS] + TEMPERATURE_SENSORS

SHORT_NAMES = {
    "Accelerometer1RMS": "Vibration 1",
    "Accelerometer2RMS": "Vibration 2",
    "Current": "Motor current",
    "Voltage": "Motor voltage",
    "Volume Flow RateRMS": "Flow rate",
    "Temperature": "Motor temperature",
    "Thermocouple": "Fluid temperature",
}


# ---------------------------------------------------------------------------
# 1. Alarm log
# ---------------------------------------------------------------------------

def sensor_deviation(sensor, idx, rows, cache, baseline):
    """How far one sensor went beyond normal during one alarm.

    Returns (peak in baseline std, the limit it is compared with, reason text).
    For normal sensors there are two tests (level moved, or got noisier),
    and we report whichever went furthest beyond ITS limit.
    """
    experiment_id = rows["experiment_id"].iloc[0]
    name = SHORT_NAMES[sensor]
    if sensor in TEMPERATURE_SENSORS:
        rates = cache[("rate", experiment_id, SETTING["temp_window"])]
        rate_std = rates.loc[baseline, sensor].std()
        size = rates.loc[idx, sensor] / rate_std
        at_peak = size.abs().idxmax()
        peak = abs(size[at_peak])
        direction = "rising" if size[at_peak] > 0 else "falling"
        reason = (f"{name} was {direction} {peak:.0f}x faster than normal "
                  f"({rates.loc[at_peak, sensor]:+.1f} °C/min)")
        return peak, SETTING["temp_k"], reason

    mean, std = baseline_stats(rows)
    roll_mean, roll_std = cache[("rolling", experiment_id, SETTING["window"])]
    level = (roll_mean.loc[idx, sensor] - mean[sensor]) / std[sensor]
    noise = roll_std.loc[idx, sensor] / std[sensor]
    level_peak, noise_peak = level.abs().max(), noise.max()
    if level_peak / SETTING["k"] >= noise_peak / SETTING["m"]:
        direction = "rose" if level[level.abs().idxmax()] > 0 else "fell"
        reason = f"{name} {direction} by {level_peak:.0f}x its normal spread (30-s average)"
        return level_peak, SETTING["k"], reason
    reason = f"{name} became {noise_peak:.1f}x as jumpy as normal (30-s spread)"
    return noise_peak, SETTING["m"], reason


def alarm_log_for(rows, sensor_alarms, cache, set_name):
    """One row per alarm inside the monitoring window of one experiment."""
    seconds = seconds_since_start(rows)
    window = (seconds >= BASELINE_SECONDS) & (seconds < WINDOW_END)
    baseline = baseline_mask(rows) & ~rows["flag_label_conflict"]
    in_alarm = sensor_alarms.any(axis=1) & window
    # Number each continuous stretch of alarm (same idea as detectors.alarm_events).
    event_number = (in_alarm & ~in_alarm.shift(1, fill_value=False)).cumsum()

    log = []
    for _, idx in in_alarm[in_alarm].groupby(event_number[in_alarm]).groups.items():
        sensors = [s for s in WATCHED if sensor_alarms.loc[idx, s].any()]
        details = [sensor_deviation(s, idx, rows, cache, baseline) for s in sensors]
        worst = max(details, key=lambda d: d[0] / d[1])  # furthest beyond its limit
        # Labels are only stored for the later check; they are NOT used in the score.
        labels = rows.loc[idx, "anomaly"].where(~rows.loc[idx, "flag_label_conflict"])
        log.append({
            "experiment_id": rows["experiment_id"].iloc[0],
            "set": set_name,
            "start": rows.loc[idx, "datetime"].iloc[0],
            "end": rows.loc[idx, "datetime"].iloc[-1],
            "start_s": seconds[idx].iloc[0],
            "duration_s": seconds[idx].iloc[-1] - seconds[idx].iloc[0] + 1,
            "sensors": ", ".join(SHORT_NAMES[s] for s in sensors),
            "n_sensors": len(sensors),
            "peak_deviation_std": round(worst[0], 1),
            "limit_std": worst[1],
            "times_over_limit": round(worst[0] / worst[1], 1),
            "reason": "; ".join(d[2] for d in details),
            "label_check_overlaps_fault": bool((labels == 1).any()) if labels.notna().any() else pd.NA,
        })
    return log


# ---------------------------------------------------------------------------
# 2. Priority score (labels NOT used)
# ---------------------------------------------------------------------------

def priority_score(rows, sensor_alarms, events):
    """score = 100 x (D + S + N) / 3, each part between 0 and 1:
      D = share of the monitored time spent in alarm           (how long)
      S = log10(largest deviation, in baseline std) / 2, max 1 (how severe)
          10x normal spread -> 0.5, 100x -> 1
      N = signals that raised an alarm / 7 watched signals     (how widespread)
    """
    seconds = seconds_since_start(rows)
    window = (seconds >= BASELINE_SECONDS) & (seconds < WINDOW_END)
    duration = sensor_alarms.any(axis=1)[window].mean()
    peak = max((e["peak_deviation_std"] for e in events), default=0)
    severity = min(np.log10(peak) / 2, 1) if peak > 1 else 0.0
    signals = {s for e in events for s in e["sensors"].split(", ")}
    spread = len(signals) / len(WATCHED)
    return {
        "alarms": len(events),
        "alarm_minutes": round(duration * window.sum() / 60, 1),
        "D_duration": round(duration, 3),
        "peak_deviation_std": peak,
        "S_severity": round(severity, 3),
        "signals_alarmed": ", ".join(sorted(signals)),
        "N_sensors": round(spread, 3),
        "priority_score": round(100 * (duration + severity + spread) / 3, 1),
    }


def sensitivity(ranking):
    """Re-rank with different weights for (duration, severity, sensors).
    Shows whether the order depends a lot on our choice of equal weights."""
    table = ranking[["experiment_id"]].copy()
    for name, (w_d, w_s, w_n) in WEIGHTINGS.items():
        score = 100 * (w_d * ranking["D_duration"] + w_s * ranking["S_severity"]
                       + w_n * ranking["N_sensors"]) / (w_d + w_s + w_n)
        # method="min": tied scores share the best rank (e.g. several zeros).
        table[f"rank: {name}"] = score.rank(ascending=False, method="min").astype(int)
    return table.sort_values("rank: equal (used)")


# ---------------------------------------------------------------------------
# 3. Check against the labels (done AFTER ranking)
# ---------------------------------------------------------------------------

def label_check(rows, sensor_alarms):
    """Share of this experiment's alarm time that falls inside the labelled fault."""
    seconds = seconds_since_start(rows)
    window = (seconds >= BASELINE_SECONDS) & (seconds < WINDOW_END) & ~rows["flag_label_conflict"]
    alarm = sensor_alarms.any(axis=1) & window
    fault = window & (rows["anomaly"] == 1)
    return {
        "has_labelled_fault": bool(fault.any()),
        "share_of_alarm_time_inside_fault": (alarm & fault).sum() / alarm.sum() if alarm.any() else np.nan,
        "share_of_fault_time_in_alarm": (alarm & fault).sum() / fault.sum() if fault.any() else np.nan,
    }


# ---------------------------------------------------------------------------
# 4. Charts
# ---------------------------------------------------------------------------

def chart_timeline(ranking, alarm_log, all_rows, filename):
    """(a) One row per experiment (ordered by priority), alarms as bars."""
    order = ranking["experiment_id"].tolist()
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 11))
    for y, experiment_id in enumerate(order):
        rows = all_rows[experiment_id]
        seconds = seconds_since_start(rows)
        # Labelled fault period (shaded), from the labels: for reading only.
        fault = seconds[(rows["anomaly"] == 1)]
        if len(fault):
            ax.barh(y, fault.max() - fault.min(), left=fault.min(), height=0.9,
                    color=ANOMALY_COLOUR, alpha=0.2, lw=0)
        mine = alarm_log[alarm_log["experiment_id"] == experiment_id]
        ax.barh([y] * len(mine), mine["duration_s"], left=mine["start_s"], height=0.5,
                color=ROLLING_COLOUR, lw=0)
    ax.axvspan(0, BASELINE_SECONDS, color=BASELINE_COLOUR, alpha=0.3, lw=0)
    labels = [f"{e}  ({fault_type(e) if not e.startswith('anomaly') else 'no fault'})"
              for e in order]
    ax.set_yticks(range(len(order)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, WINDOW_END)
    ax.set_xlabel("Seconds since the experiment started")
    ax.grid(axis="y", visible=False)
    handles = [plt.Rectangle((0, 0), 1, 1, color=BASELINE_COLOUR, alpha=0.5),
               plt.Rectangle((0, 0), 1, 1, color=ANOMALY_COLOUR, alpha=0.3),
               plt.Rectangle((0, 0), 1, 1, color=ROLLING_COLOUR)]
    ax.legend(handles, ["baseline (first 5 min)", "labelled fault (for checking only)", "alarm"],
              loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3)
    ax.set_title("Alarm timeline, rolling + rate detector (rows ordered by priority score, highest first)",
                 loc="left", fontsize=11, pad=24)
    fig.tight_layout()
    save_figure(fig, filename)


def chart_top10(ranking, filename):
    """(b) Top 10 experiments by priority score, split into its three parts."""
    top = ranking.head(10).iloc[::-1]  # reversed so the highest is at the top
    # Three shades of one blue: the parts of one score (orange and aqua are
    # kept for "labelled fault" and "rolling detector" in other figures).
    parts = [("D_duration", "duration (D)", "#174a85"),
             ("S_severity", "severity (S)", NORMAL_COLOUR),
             ("N_sensors", "sensors involved (N)", "#8db8ec")]
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 5))
    left = np.zeros(len(top))
    for column, label, colour in parts:
        width = 100 * top[column].to_numpy() / 3  # each part's share of the score
        ax.barh(range(len(top)), width, left=left, color=colour, label=label,
                edgecolor="white", linewidth=1.5)
        left += width
    for y, score in enumerate(top["priority_score"]):
        ax.text(score + 1, y, f"{score:.0f}", va="center", fontsize=8, color=TEXT_COLOUR)
    ax.set_yticks(range(len(top)),
                  [f"{e} ({s})  {fault_type(e) if not e.startswith('anomaly') else 'no fault'}"
                   for e, s in zip(top["experiment_id"], top["set"])], fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Priority score (0-100); made from alarms only, no labels")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right")
    ax.set_title("Top 10 experiments to investigate")
    fig.text(0.01, 0.01, "Fault names are shown for reference only. They are not used "
             "in the score, which is built from the alarms alone.",
             fontsize=8, color=TEXT_COLOUR, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04, 1, 1))  # leave room for the note
    save_figure(fig, filename)


def chart_sensors(alarm_log, filename):
    """(c) How many alarms each signal took part in."""
    counts = pd.Series({SHORT_NAMES[s]: alarm_log["sensors"].str.contains(SHORT_NAMES[s]).sum()
                        for s in WATCHED}).sort_values()
    fig, ax = plt.subplots(figsize=(FIGURE_WIDTH, 4.5))
    bars = ax.barh(counts.index, counts.to_numpy(), color=NORMAL_COLOUR)
    ax.bar_label(bars, padding=3, fontsize=8, color=TEXT_COLOUR)
    ax.set_xlabel("Number of alarms the signal took part in (an alarm can involve several)")
    ax.grid(axis="y", visible=False)
    ax.set_title("Alarms per signal, all 35 experiments (temperatures: rate of change)")
    fig.tight_layout()
    save_figure(fig, filename)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pd.set_option("display.width", 250)
    data = load_clean_data()
    split = pd.read_csv(SPLIT_FILE)
    data = data.merge(split[["experiment_id", "role"]], on="experiment_id")
    all_rows = {e: rows for e, rows in data.groupby("experiment_id")}
    role = dict(zip(split["experiment_id"], split["role"]))
    cache = build_cache(all_rows)

    log, ranking = [], []
    for experiment_id, rows in all_rows.items():
        sensor_alarms = run_detector(rows, cache, DETECTOR, SETTING)
        events = alarm_log_for(rows, sensor_alarms, cache, role[experiment_id])
        log += events
        ranking.append({"experiment_id": experiment_id, "set": role[experiment_id],
                        **priority_score(rows, sensor_alarms, events),
                        **label_check(rows, sensor_alarms)})

    alarm_log = pd.DataFrame(log)
    alarm_log.to_csv(REPORTS_DIR / "alarm_log.csv", index=False)
    print(f"Saved {len(alarm_log)} alarms to reports/alarm_log.csv")

    ranking = pd.DataFrame(ranking).sort_values("priority_score", ascending=False)
    ranking.insert(0, "rank", range(1, len(ranking) + 1))
    ranking.insert(3, "fault_type", [fault_type(e) if not e.startswith("anomaly") else "no fault"
                                     for e in ranking["experiment_id"]])
    ranking.round(3).to_csv(REPORTS_DIR / "priority_ranking.csv", index=False)
    print(ranking.drop(columns=["signals_alarmed"]).round(2).to_string(index=False))

    # Sensitivity check: does the top 5 change with other weights?
    ranks = sensitivity(ranking)
    ranks.to_csv(REPORTS_DIR / "priority_sensitivity.csv", index=False)
    equal_top5 = set(ranks.head(5)["experiment_id"])
    print("\nTop 5 under each weighting:")
    for column in ranks.columns[1:]:
        top5 = ranks.sort_values(column).head(5)["experiment_id"].tolist()
        print(f"  {column:24s} {top5}  (shared with equal weights: "
              f"{len(equal_top5 & set(top5))} of 5)")

    chart_timeline(ranking, alarm_log, all_rows, "k_alarm_timeline.png")
    chart_top10(ranking, "l_top10_priority.png")
    chart_sensors(alarm_log, "m_alarms_per_signal.png")


if __name__ == "__main__":
    main()
