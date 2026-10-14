"""
detectors.py - Phase 3: the two anomaly detectors and how we score them.

This file only contains functions. tune_detectors.py calls them.

The idea in one paragraph:
  Every experiment starts with a few minutes of normal running. We measure
  each sensor's mean and standard deviation in that "baseline" window.
  After the baseline, a sensor is FLAGGED when it looks too different from
  its own baseline. A flag only becomes an ALARM if it stays on for at
  least N seconds in a row (the persistence rule).

  Detector 1 (fixed threshold) looks at each raw reading.
  Detector 2 (rolling statistics) looks at the mean and the standard
  deviation of the last W seconds of readings.
"""

import pandas as pd

from common import SENSORS

# Pressure is left out: its readings only take about 10 distinct values,
# about 0.328 bar apart (see README), so one reading jumping to the next
# level is a big step compared with its spread, and small real changes
# can't be seen at all.
DETECTOR_SENSORS = [s for s in SENSORS if s != "Pressure"]

# Length of the baseline window at the start of every experiment.
# Fixed BEFORE checking the labels; tune_detectors.py then checks that the
# window really is labelled normal in every tuning file.
BASELINE_SECONDS = 300


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------

def seconds_since_start(rows):
    """Seconds from the first reading of the experiment."""
    return (rows["datetime"] - rows["datetime"].iloc[0]).dt.total_seconds()


def baseline_mask(rows):
    """True for readings in the first BASELINE_SECONDS of the experiment."""
    return seconds_since_start(rows) < BASELINE_SECONDS


def baseline_stats(rows):
    """Mean and standard deviation of each sensor in the baseline window.

    Readings with conflicting labels are left out, because we can't be
    sure they are normal.
    """
    usable = rows[baseline_mask(rows) & ~rows["flag_label_conflict"]]
    return usable[DETECTOR_SENSORS].mean(), usable[DETECTOR_SENSORS].std()


# ---------------------------------------------------------------------------
# The two detectors: they return one True/False column per sensor
# ---------------------------------------------------------------------------

def threshold_flags(rows, k):
    """Detector 1: flag a reading outside baseline mean +/- k * baseline std."""
    mean, std = baseline_stats(rows)
    distance = (rows[DETECTOR_SENSORS] - mean).abs()
    return distance > k * std


def rolling_values(rows, window_seconds):
    """Rolling mean and rolling std over the PAST window_seconds of time.

    Only past readings are used, so this could run live on the machine.
    At least half the window must be filled before a value is given.
    """
    rolling = rows.set_index("datetime")[DETECTOR_SENSORS].rolling(
        f"{window_seconds}s", min_periods=window_seconds // 2)
    return (rolling.mean().reset_index(drop=True).set_axis(rows.index),
            rolling.std().reset_index(drop=True).set_axis(rows.index))


def rolling_flags(rows, rolling_mean, rolling_std, k, m):
    """Detector 2: flag when, for the last W seconds,
      - the rolling mean is more than k * baseline std from the baseline mean
        (the sensor's level has moved), OR
      - the rolling std is more than m * baseline std
        (the sensor has become noisier / shakier).
    Rolling values are passed in, so they are only computed once per window.
    """
    mean, std = baseline_stats(rows)
    level_moved = (rolling_mean - mean).abs() > k * std
    got_noisier = rolling_std > m * std
    return level_moved | got_noisier


# ---------------------------------------------------------------------------
# Persistence rule: a flag must last N seconds before it becomes an alarm
# ---------------------------------------------------------------------------

def apply_persistence(flags, rows, n_seconds):
    """Turn per-sensor flags into per-sensor alarms.

    In plain words: a single odd reading is often just noise. So a sensor
    only goes into alarm once its flag has stayed on, without a break, for
    at least n_seconds. As soon as the flag goes off, the alarm stops.
    This only uses past readings, so it could also run live.

    A large time gap (missing readings) also breaks the run, because we
    don't know what happened during the gap.
    """
    times = rows["datetime"]
    gap = rows["flag_large_gap_before"]
    alarms = pd.DataFrame(False, index=flags.index, columns=flags.columns)
    for sensor in flags.columns:
        flag = flags[sensor]
        # A run starts where the flag is on but the previous reading was not
        # flagged (or there was a gap just before it).
        previous_flag = flag.shift(1, fill_value=False)
        run_starts = flag & (~previous_flag | gap)
        # For every reading, the time its current run started.
        start_time = times.where(run_starts).ffill()
        seconds_on = (times - start_time).dt.total_seconds()
        alarms[sensor] = flag & (seconds_on >= n_seconds)
    return alarms


# ---------------------------------------------------------------------------
# Alarm events and scoring
# ---------------------------------------------------------------------------

def alarm_events(rows, sensor_alarms):
    """List each alarm as one event: start, end, and which sensors caused it.

    The machine is "in alarm" when ANY sensor is in alarm. One event is a
    continuous stretch of readings in alarm.
    """
    in_alarm = sensor_alarms.any(axis=1)
    # Number each stretch: the count goes up every time the alarm switches on.
    event_number = (in_alarm & ~in_alarm.shift(1, fill_value=False)).cumsum()
    events = []
    for _, idx in in_alarm[in_alarm].groupby(event_number[in_alarm]).groups.items():
        event_rows = rows.loc[idx]
        sensors = [s for s in sensor_alarms.columns if sensor_alarms.loc[idx, s].any()]
        labelled = event_rows["anomaly"]
        events.append({
            "experiment_id": event_rows["experiment_id"].iloc[0],
            "start": event_rows["datetime"].iloc[0],
            "end": event_rows["datetime"].iloc[-1],
            "duration_s": (event_rows["datetime"].iloc[-1]
                           - event_rows["datetime"].iloc[0]).total_seconds() + 1,
            "sensors": ", ".join(sensors),
            # Does the event overlap a labelled anomaly at all?
            # (Empty for the anomaly-free file, which has no labels.)
            "overlaps_labelled_anomaly": bool((labelled == 1).any())
                                         if labelled.notna().any() else pd.NA,
        })
    return events


def score(results):
    """Precision, recall and false-alarm rate, counted per reading (second).

    results must have columns: alarm (True/False) and anomaly (0/1).
      precision        = of the seconds in alarm, the share labelled anomaly
      recall           = of the seconds labelled anomaly, the share in alarm
      false-alarm rate = of the seconds labelled normal, the share in alarm
    """
    alarm = results["alarm"]
    anomaly = results["anomaly"] == 1
    true_pos = int((alarm & anomaly).sum())
    false_pos = int((alarm & ~anomaly).sum())
    false_neg = int((~alarm & anomaly).sum())
    true_neg = int((~alarm & ~anomaly).sum())
    precision = true_pos / (true_pos + false_pos) if true_pos + false_pos else float("nan")
    recall = true_pos / (true_pos + false_neg)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "false_alarm_rate": false_pos / (false_pos + true_neg),
    }
