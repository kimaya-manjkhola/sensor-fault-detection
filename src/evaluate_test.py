"""
evaluate_test.py - Phase 4: evaluate the FINAL detectors on the held-out
test files.

Rules:
  - The settings below are copied from Phase 3b and are NOT changed after
    seeing test results (a check below makes sure they match Phase 3b).
  - Each test file learns "normal" from its own first 5 minutes, exactly
    as in tuning.
  - Readings with conflicting labels are never scored.

The same code also re-scores the tuning files, so tuning and test numbers
are calculated in exactly the same way and can be compared side by side.

Outputs (reports/ and figures/):
  phase4_baseline_check.csv        - is each test baseline fully normal?
  phase4_summary.csv               - scores per detector, tuning vs test
  phase4_per_fault.csv             - every fault: caught? delay? false alarms?
  phase4_by_fault_type.csv         - faults caught per fault type
  phase4_alarms_test.csv           - every test alarm and its sensors
  phase4_missed_fault_analysis.csv - how much each sensor changed in missed faults
  h_, i_, j_ figures               - bar charts

Run it AFTER clean_data.py, make_split.py and tune_detectors.py:
    .venv/bin/python src/evaluate_test.py
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from common import FIGURES_DIR, REPORTS_DIR, SPLIT_FILE, load_clean_data
from detectors import (DETECTOR_SENSORS, TEMPERATURE_SENSORS, alarm_events,
                       baseline_mask, baseline_stats, rolling_values, score,
                       temperature_rates, threshold_flags)
from tune_detectors import (ROLLING_COLOUR, THRESHOLD_COLOUR, check_baselines,
                            describe, run_detector)

# Final settings from Phase 3b (reports/phase3_detectors.md, section 8).
FINAL_SETTINGS = {
    "threshold": {"sensors": "no temperatures", "k": 3, "n": 10,
                  "temp_window": 30, "temp_k": 5},
    "rolling": {"sensors": "no temperatures", "window": 30, "k": 5, "m": 2, "n": 10,
                "temp_window": 30, "temp_k": 6},
}


def without_rate(setting):
    """The same setting without the temperature rate-of-change rule."""
    return {key: value for key, value in setting.items() if not key.startswith("temp_")}


# The four versions we evaluate. The first two are the final detectors;
# the other two show whether the Phase 3b temperature rule helped on new data.
VARIANTS = {
    "threshold + rate": ("threshold", FINAL_SETTINGS["threshold"]),
    "rolling + rate": ("rolling", FINAL_SETTINGS["rolling"]),
    "threshold (no rate)": ("threshold", without_rate(FINAL_SETTINGS["threshold"])),
    "rolling (no rate)": ("rolling", without_rate(FINAL_SETTINGS["rolling"])),
}
FINAL_VARIANTS = ["threshold + rate", "rolling + rate"]
VARIANT_COLOURS = {"threshold + rate": THRESHOLD_COLOUR, "rolling + rate": ROLLING_COLOUR}
FLAG_EVERYTHING_COLOUR = "#8a8984"  # grey: a reference, not a detector

# Rules for counting an alarm that was already running when a fault started
# as a genuine early catch (see strict_detection below).
EARLY_CATCH_WINDOW_S = 30
EARLY_CATCH_MIN_INTO_FAULT_S = 10


def fault_type(experiment_id):
    """Short fault-type name, grouped from the SKAB descriptions (split.csv)."""
    group, number = experiment_id.split("/")
    if group == "valve1":
        return "Inlet valve closed"
    if group == "valve2":
        return "Outlet valve closed"
    number = int(number)
    if number <= 4:
        return "Leak / fluid addition"
    if number <= 9:
        return "Rotor imbalance"
    if number <= 11:
        return "More water in circuit"
    if number <= 13:
        return "Cavitation"
    return "Hot water supply"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_sets():
    """Return {"tuning": {id: rows}, "test": {id: rows}}."""
    data = load_clean_data()
    split = pd.read_csv(SPLIT_FILE)
    data = data.merge(split[["experiment_id", "role"]], on="experiment_id")
    return {role: {e: rows for e, rows in data[data["role"] == role].groupby("experiment_id")}
            for role in ["tuning", "test"]}


def check_settings_match_phase3b():
    """Stop if the settings above are not the ones chosen in Phase 3b."""
    chosen = set(pd.read_csv(REPORTS_DIR / "phase3_alarms_tuning.csv")["setting"])
    for detector, setting in FINAL_SETTINGS.items():
        assert describe(detector, setting) in chosen, f"{detector} settings differ from Phase 3b!"


def build_cache(experiments):
    """Rolling values and temperature rates for every file (30 s windows)."""
    cache = {}
    for e, rows in experiments.items():
        cache[("rolling", e, FINAL_SETTINGS["rolling"]["window"])] = rolling_values(
            rows, FINAL_SETTINGS["rolling"]["window"])
        for setting in FINAL_SETTINGS.values():
            window = setting["temp_window"]
            cache[("rate", e, window)] = temperature_rates(rows, window)
    return cache


# ---------------------------------------------------------------------------
# Scoring one file and one set of files
# ---------------------------------------------------------------------------

def evaluate_file(rows, sensor_alarms):
    """Scores for one experiment file.

    Returns (per-second table, per-fault facts, list of alarm events).
    Conflicting-label readings are blanked out of the labels, so they count
    neither as anomaly nor as normal - also when deciding whether an alarm
    is a "fault alarm" or a "false alarm".
    """
    after = ~baseline_mask(rows)
    conflict = rows["flag_label_conflict"]
    scored = after & ~conflict
    in_alarm = sensor_alarms.any(axis=1)

    labels = rows.copy()
    labels.loc[conflict, "anomaly"] = pd.NA
    events = alarm_events(labels[after], sensor_alarms[after])

    fault = scored & (rows["anomaly"] == 1)
    caught = in_alarm & fault
    detected = bool(caught.any())
    delay = ((rows.loc[caught, "datetime"].iloc[0] - rows.loc[fault, "datetime"].iloc[0])
             .total_seconds() if detected else np.nan)

    fault_events = [e for e in events if e["overlaps_labelled_anomaly"] is True]
    false_events = [e for e in events if e["overlaps_labelled_anomaly"] is False]
    sensors = sorted({s for e in fault_events for s in e["sensors"].split(", ")})
    facts = {
        "detected": detected,
        "delay_s": delay,
        **strict_detection(rows, fault, events),
        "fault_alarms": len(fault_events),
        "false_alarms": len(false_events),
        "normal_seconds": int((scored & (rows["anomaly"] == 0)).sum()),
        "sensors_in_fault_alarms": ", ".join(sensors),
    }
    per_second = pd.DataFrame({"alarm": in_alarm[scored], "anomaly": rows.loc[scored, "anomaly"]})
    return per_second, facts, events


def strict_detection(rows, fault, events):
    """A stricter way to count detections.

    A "0 s" delay means an alarm was already running when the fault started.
    That alarm only counts as a real (early) catch if ALL of these hold:
      1. it started at most EARLY_CATCH_WINDOW_S seconds before the fault,
      2. it kept going for at least EARLY_CATCH_MIN_INTO_FAULT_S seconds
         into the fault (so the change carried on into the fault), and
      3. none of its sensors had raised an earlier alarm in this file
         (otherwise it looks like the normal noise of that sensor).
    Otherwise, only alarms that START at or after the fault start count.
    """
    if not fault.any():
        return {"detected_strict": False, "delay_strict_s": np.nan}
    fault_start = rows.loc[fault, "datetime"].iloc[0]
    fault_end = rows.loc[fault, "datetime"].iloc[-1]
    result = {"alarm_on_at_fault_start": False, "early_alarm_started_s_before": np.nan,
              "early_alarm_sensors": "", "early_catch_justified": False}

    for event in events:
        if event["start"] < fault_start <= event["end"]:
            sensors = set(event["sensors"].split(", "))
            earlier_same_sensor = any(
                other["end"] < event["start"] and sensors & set(other["sensors"].split(", "))
                for other in events)
            seconds_before = (fault_start - event["start"]).total_seconds()
            seconds_into = (event["end"] - fault_start).total_seconds()
            result.update({
                "alarm_on_at_fault_start": True,
                "early_alarm_started_s_before": seconds_before,
                "early_alarm_sensors": event["sensors"],
                "early_catch_justified": (seconds_before <= EARLY_CATCH_WINDOW_S
                                          and seconds_into >= EARLY_CATCH_MIN_INTO_FAULT_S
                                          and not earlier_same_sensor),
            })

    # Alarms that start inside the fault period.
    later = [e for e in events if fault_start <= e["start"] <= fault_end
             and e["overlaps_labelled_anomaly"] is True]
    if result["early_catch_justified"]:
        delay = 0.0
    elif later:
        delay = (min(e["start"] for e in later) - fault_start).total_seconds()
    else:
        delay = np.nan
    result.update({"detected_strict": not np.isnan(delay), "delay_strict_s": delay})
    return result


def evaluate_set(experiments, cache, detector, setting):
    """Run one detector on every file in a set; return (summary, per-fault rows, events)."""
    per_second, per_fault, all_events = [], [], []
    for experiment_id, rows in experiments.items():
        sensor_alarms = run_detector(rows, cache, detector, setting)
        seconds, facts, events = evaluate_file(rows, sensor_alarms)
        per_second.append(seconds)
        per_fault.append({"experiment_id": experiment_id,
                          "fault_type": fault_type(experiment_id), **facts})
        all_events += events
    per_fault = pd.DataFrame(per_fault)
    normal_hours = per_fault["normal_seconds"].sum() / 3600  # 1 reading ~ 1 second
    summary = score(pd.concat(per_second))
    summary.update({
        "faults_detected": int(per_fault["detected"].sum()),
        "faults_detected_strict": int(per_fault["detected_strict"].sum()),
        "faults": len(per_fault),
        "median_delay_s": per_fault["delay_s"].median(),
        "median_delay_strict_s": per_fault["delay_strict_s"].median(),
        "false_alarm_events": int(per_fault["false_alarms"].sum()),
        "normal_hours": normal_hours,
        "false_alarms_per_hour": per_fault["false_alarms"].sum() / normal_hours,
    })
    return summary, per_fault, all_events


def flag_everything(experiments):
    """The "flag everything" baseline: always in alarm.
    Precision = share of anomaly readings; recall = 1; false-alarm rate = 1."""
    anomaly_share = []
    for rows in experiments.values():
        scored = ~baseline_mask(rows) & ~rows["flag_label_conflict"]
        anomaly_share.append(rows.loc[scored, "anomaly"])
    labels = pd.concat(anomaly_share)
    return {"precision": (labels == 1).mean(), "recall": 1.0, "false_alarm_rate": 1.0}


# ---------------------------------------------------------------------------
# Missed faults: how much did each sensor change, compared with baseline noise?
# ---------------------------------------------------------------------------

def longest_run_seconds(mask, times):
    """Longest unbroken stretch where mask is True, in seconds."""
    if not mask.any():
        return 0.0
    run_id = (mask != mask.shift()).cumsum()
    runs = times[mask].groupby(run_id[mask]).agg(["first", "last"])
    return ((runs["last"] - runs["first"]).dt.total_seconds() + 1).max()


def analyse_missed_fault(rows, cache):
    """For each signal the detectors watch, compare the fault period with the
    baseline. All numbers are in "baseline standard deviations"."""
    scored = ~baseline_mask(rows) & ~rows["flag_label_conflict"]
    fault = scored & (rows["anomaly"] == 1)
    times = rows["datetime"]
    mean, std = baseline_stats(rows)
    window = FINAL_SETTINGS["rolling"]["window"]
    roll_mean, roll_std = cache[("rolling", rows["experiment_id"].iloc[0], window)]
    k_threshold = FINAL_SETTINGS["threshold"]["k"]

    results = []
    for sensor in DETECTOR_SENSORS:
        if sensor in TEMPERATURE_SENSORS:
            continue  # temperatures are only used through their rate (below)
        beyond = threshold_flags(rows, k_threshold)[sensor] & fault
        results.append({
            "signal": sensor,
            "mean_shift_std": (rows.loc[fault, sensor].mean() - mean[sensor]) / std[sensor],
            "max_30s_mean_shift_std": ((roll_mean.loc[fault, sensor] - mean[sensor]).abs()
                                       / std[sensor]).max(),
            "max_30s_std_ratio": (roll_std.loc[fault, sensor] / std[sensor]).max(),
            "share_beyond_k_threshold": beyond.sum() / fault.sum(),
            "longest_run_beyond_k_threshold_s": longest_run_seconds(beyond, times),
        })
    rates = cache[("rate", rows["experiment_id"].iloc[0], FINAL_SETTINGS["threshold"]["temp_window"])]
    in_base = baseline_mask(rows) & ~rows["flag_label_conflict"]
    for sensor in TEMPERATURE_SENSORS:
        rate_std = rates.loc[in_base, sensor].std()
        size = rates[sensor].abs() / rate_std
        results.append({
            "signal": f"{sensor} rate",
            "max_rate_std": size[fault].max(),
            "longest_run_beyond_rate_k5_s": longest_run_seconds((size > 5) & fault, times),
        })
    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def style_axes(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e5e3")
    ax.set_axisbelow(True)


def chart_scores(test_summary, everything, filename):
    """(a) precision, recall, false-alarm rate per detector vs flag-everything."""
    metrics = ["precision", "recall", "false_alarm_rate"]
    names = ["Precision", "Recall", "False-alarm rate\n(lower is better)"]
    series = [(v, [test_summary[v][m] for m in metrics], VARIANT_COLOURS[v]) for v in FINAL_VARIANTS]
    series.append(("flag everything", [everything[m] for m in metrics], FLAG_EVERYTHING_COLOUR))
    x = np.arange(len(metrics))
    width = 0.26
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, (label, values, colour) in enumerate(series):
        bars = ax.bar(x + (i - 1) * width, values, width - 0.03, color=colour, label=label)
        ax.bar_label(bars, labels=[f"{v:.2f}" for v in values], padding=2, fontsize=8,
                     color="#52514e")
    ax.set_xticks(x, names)
    ax.set_ylim(0, 1.25)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_ylabel("Score (0 to 1)")
    style_axes(ax)
    ax.legend(frameon=False, ncol=3, loc="upper left")
    ax.set_title("Test set: scores per reading, compared with flagging everything",
                 loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"Saved figures/{filename}")


def chart_delays(per_fault_test, filename):
    """(b) detection delay per test fault; missed faults are labelled."""
    faults = per_fault_test[per_fault_test["variant"] == FINAL_VARIANTS[0]]["experiment_id"].tolist()
    y = np.arange(len(faults))
    height = 0.38
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for i, variant in enumerate(FINAL_VARIANTS):
        mine = per_fault_test[per_fault_test["variant"] == variant].set_index("experiment_id")
        delays = mine.loc[faults, "delay_s"]
        positions = y + (i - 0.5) * height
        ax.barh(positions, delays.fillna(0), height - 0.04,
                color=VARIANT_COLOURS[variant], label=variant)
        for pos, delay in zip(positions, delays):
            if np.isnan(delay):
                text = "missed"
            elif delay == 0:
                # The alarm was already running when the fault started.
                text = "0 s (alarm already on at fault start)"
            else:
                text = f"{delay:.0f} s"
            ax.text((0 if np.isnan(delay) else delay) + 3, pos, text, va="center",
                    fontsize=8, color="#52514e")
    labels = [f"{e}  ({fault_type(e)})" for e in faults]
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Seconds from fault start to first alarm")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#e5e5e3")
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
    ax.set_title("Test set: detection delay per fault", loc="left", fontsize=11, pad=22)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"Saved figures/{filename}")


def chart_by_type(by_type_test, filename):
    """(c) faults detected per fault type, out of how many there were."""
    types = by_type_test[by_type_test["variant"] == FINAL_VARIANTS[0]]["fault_type"].tolist()
    x = np.arange(len(types))
    width = 0.36
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for i, variant in enumerate(FINAL_VARIANTS):
        mine = by_type_test[by_type_test["variant"] == variant].set_index("fault_type").loc[types]
        bars = ax.bar(x + (i - 0.5) * width, mine["detected"], width - 0.04,
                      color=VARIANT_COLOURS[variant], label=variant)
        ax.bar_label(bars, labels=[f"{d} of {n}" for d, n in zip(mine["detected"], mine["faults"])],
                     padding=2, fontsize=8, color="#52514e")
    ax.set_xticks(x, types)
    ax.set_ylabel("Faults detected")
    ax.set_ylim(0, by_type_test["faults"].max() + 1)
    ax.yaxis.get_major_locator().set_params(integer=True)
    style_axes(ax)
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("Test set: faults detected per fault type", loc="left", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / filename, dpi=150)
    plt.close(fig)
    print(f"Saved figures/{filename}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    pd.set_option("display.width", 250)
    check_settings_match_phase3b()
    sets = load_sets()
    print(f"Tuning files: {len(sets['tuning'])}, test files: {len(sets['test'])}\n")

    # 1. Test baselines
    checks = check_baselines(sets["test"])
    checks.to_csv(REPORTS_DIR / "phase4_baseline_check.csv", index=False)
    print(checks.to_string(index=False), "\n")

    caches = {name: build_cache(experiments) for name, experiments in sets.items()}

    # 2-3. Score every variant on tuning and test files, the same way.
    summaries, per_fault_tables, test_alarms = [], [], []
    for variant, (detector, setting) in VARIANTS.items():
        for set_name, experiments in sets.items():
            summary, per_fault, events = evaluate_set(experiments, caches[set_name],
                                                      detector, setting)
            summaries.append({"variant": variant, "set": set_name, **summary})
            per_fault.insert(0, "variant", variant)
            per_fault.insert(1, "set", set_name)
            per_fault_tables.append(per_fault)
            if set_name == "test" and variant in FINAL_VARIANTS:
                table = pd.DataFrame(events)
                table.insert(0, "variant", variant)
                test_alarms.append(table)
    for set_name, experiments in sets.items():
        everything = flag_everything(experiments)
        summaries.append({"variant": "flag everything", "set": set_name, **everything,
                          "faults_detected": len(experiments), "faults": len(experiments)})
    summary = pd.DataFrame(summaries)
    summary.round(4).to_csv(REPORTS_DIR / "phase4_summary.csv", index=False)
    print(summary.round(3).to_string(index=False), "\n")

    per_fault = pd.concat(per_fault_tables, ignore_index=True)
    per_fault.to_csv(REPORTS_DIR / "phase4_per_fault.csv", index=False)
    print(per_fault[(per_fault["set"] == "test")].drop(columns=["set", "normal_seconds"])
          .to_string(index=False), "\n")
    pd.concat(test_alarms).to_csv(REPORTS_DIR / "phase4_alarms_test.csv", index=False)

    # 4. Per fault type
    by_type = per_fault.groupby(["variant", "set", "fault_type"], sort=False).agg(
        faults=("detected", "size"), detected=("detected", "sum"),
        median_delay_s=("delay_s", "median"), false_alarms=("false_alarms", "sum"),
    ).reset_index()
    by_type.to_csv(REPORTS_DIR / "phase4_by_fault_type.csv", index=False)
    print(by_type[by_type["variant"].isin(FINAL_VARIANTS)].to_string(index=False), "\n")

    # 6. Missed faults (by either final detector, tuning or test)
    final_faults = per_fault[per_fault["variant"].isin(FINAL_VARIANTS)]
    missed = final_faults[~final_faults["detected"]]
    analyses = []
    for (set_name, experiment_id), group in missed.groupby(["set", "experiment_id"]):
        rows = sets[set_name][experiment_id]
        table = analyse_missed_fault(rows, caches[set_name])
        table.insert(0, "experiment_id", experiment_id)
        table.insert(1, "set", set_name)
        table.insert(2, "missed_by", " & ".join(group["variant"]))
        analyses.append(table)
    if analyses:
        analysis = pd.concat(analyses, ignore_index=True)
        analysis.round(3).to_csv(REPORTS_DIR / "phase4_missed_fault_analysis.csv", index=False)
        print(analysis.round(2).to_string(index=False), "\n")

    # 7. Charts (test set, final detectors)
    FIGURES_DIR.mkdir(exist_ok=True)
    test_summary = {row["variant"]: row for _, row in summary[summary["set"] == "test"].iterrows()}
    chart_scores(test_summary, test_summary["flag everything"], "h_test_scores_vs_flag_everything.png")
    test_faults = per_fault[(per_fault["set"] == "test") & per_fault["variant"].isin(FINAL_VARIANTS)]
    chart_delays(test_faults, "i_test_detection_delay_per_fault.png")
    test_types = by_type[(by_type["set"] == "test") & by_type["variant"].isin(FINAL_VARIANTS)]
    chart_by_type(test_types, "j_test_faults_detected_per_type.png")


if __name__ == "__main__":
    main()
