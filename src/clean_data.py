"""
clean_data.py - Phase 2: check the raw SKAB data and save a cleaned copy.

What this script does:
  1. Loads every raw SKAB file, parses the timestamps and sorts by time.
  2. Runs a set of checks on each file (duplicates, missing values,
     physically impossible values, gaps in time, label values).
  3. Checks ACROSS files for readings that appear in more than one file.
  4. Saves:
       data/processed/skab_clean.csv   - all files in one table, one block
                                         per experiment (NOT one timeline)
       data/processed/cleaning_log.csv - every check, what it found, what
                                         we did about it, and why

Important: no reading is deleted or changed. Problems are FLAGGED with
extra True/False columns so later phases can decide what to do with them.
The raw files in data/raw are only read, never written.

Run it from the project folder with:
    .venv/bin/python src/clean_data.py
"""

import pandas as pd

from common import CLEAN_FILE, CLEANING_LOG_FILE, PROCESSED_DIR, RAW_DIR, SENSORS

# Lowest value each sensor can physically report.
#  - RMS values (vibration, flow) are square roots, so they can't be negative.
#  - Current and voltage are assumed to be reported as magnitudes (the SKAB
#    docs don't say), so a negative value would also be impossible.
#  - Pressure: the SKAB docs don't say whether this is gauge pressure
#    (relative to the air) or absolute pressure. Gauge pressure CAN be
#    negative (suction), but nothing can be below a perfect vacuum,
#    which is -1.01325 bar in gauge terms.
#  - Temperatures in °C can't be below absolute zero (-273.15 °C).
PHYSICAL_MINIMUM = {
    "Accelerometer1RMS": 0.0,
    "Accelerometer2RMS": 0.0,
    "Current": 0.0,
    "Pressure": -1.01325,
    "Temperature": -273.15,
    "Thermocouple": -273.15,
    "Voltage": 0.0,
    "Volume Flow RateRMS": 0.0,
}

# Readings normally arrive 1-2 seconds apart (see README). A longer gap
# means some readings are missing, so we flag the row that comes after it.
LARGE_GAP_SECONDS = 2

# Every check adds one row to this list. It is saved as cleaning_log.csv.
log = []


def record(experiment_id, check, rows_affected, action, reason, column=""):
    """Add one line to the cleaning log."""
    log.append({
        "experiment_id": experiment_id,
        "check": check,
        "column": column,
        "rows_affected": rows_affected,
        "action": action,
        "reason": reason,
    })


def file_sort_key(path):
    """Sort files by folder, then by file NUMBER (so 2.csv comes before 10.csv)."""
    number = int(path.stem) if path.stem.isdigit() else -1
    return (path.parent.name, number)


def clean_one_file(path):
    """Load one raw file, run the per-file checks and return the table."""
    group = path.parent.name                      # e.g. 'valve1'
    experiment_id = f"{group}/{path.stem}"        # e.g. 'valve1/0'

    df = pd.read_csv(path, sep=";")

    # --- Timestamps -------------------------------------------------------
    # errors="coerce" turns any text that isn't a valid date into NaT
    # ("not a time") instead of crashing, so we can count them.
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    bad_times = int(df["datetime"].isna().sum())
    record(experiment_id, "unreadable timestamp", bad_times,
           "none needed" if bad_times == 0 else "kept, timestamp left empty",
           "Every row needs a valid time to be placed in order.")

    # Sort by time. kind="stable" keeps the original order for equal times.
    out_of_order = int((df["datetime"].diff().dt.total_seconds() < 0).sum())
    df = df.sort_values("datetime", kind="stable").reset_index(drop=True)
    record(experiment_id, "rows out of time order", out_of_order,
           "none needed" if out_of_order == 0 else "rows sorted by time",
           "Time-series methods assume rows are in time order.")

    # --- Duplicates -------------------------------------------------------
    df["flag_duplicate_timestamp"] = df["datetime"].duplicated(keep=False)
    dup_times = int(df["flag_duplicate_timestamp"].sum())
    record(experiment_id, "duplicate timestamps", dup_times,
           "none needed" if dup_times == 0 else "kept, flagged",
           "Two readings at the same second would be double-counted.")

    dup_rows = int(df.duplicated().sum())
    record(experiment_id, "fully duplicated rows", dup_rows,
           "none needed" if dup_rows == 0 else "kept (also flagged as duplicate timestamps)",
           "An exact repeated row is probably a recording error.")

    # --- Missing values ---------------------------------------------------
    for column in SENSORS:
        missing = int(df[column].isna().sum())
        record(experiment_id, "missing values", missing,
               "none needed" if missing == 0 else "kept as empty, NOT filled in",
               "Filling in values would be making up data.", column)

    # --- Physically impossible values -------------------------------------
    # One flag column: True if ANY sensor in that row is below its minimum.
    df["flag_impossible_value"] = False
    for column, minimum in PHYSICAL_MINIMUM.items():
        too_low = df[column] < minimum
        df["flag_impossible_value"] |= too_low
        record(experiment_id, f"value below physical minimum ({minimum})",
               int(too_low.sum()),
               "none needed" if too_low.sum() == 0 else "kept, flagged",
               "A sensor can't really read below this value.", column)

    # Negative pressure is NOT impossible if it is gauge pressure, but we
    # can't confirm the pressure type, so we flag it separately.
    df["flag_negative_pressure"] = df["Pressure"] < 0
    record(experiment_id, "negative pressure", int(df["flag_negative_pressure"].sum()),
           "kept unchanged, flagged",
           "Possible only if this is gauge pressure; the SKAB docs don't say which.",
           "Pressure")

    # --- Gaps in time -----------------------------------------------------
    # Seconds since the previous row. The first row has no previous row.
    df["gap_before_s"] = df["datetime"].diff().dt.total_seconds()
    df["flag_large_gap_before"] = df["gap_before_s"] > LARGE_GAP_SECONDS
    n_gaps = int(df["flag_large_gap_before"].sum())
    longest = df["gap_before_s"].max()
    record(experiment_id, f"time gaps longer than {LARGE_GAP_SECONDS} s", n_gaps,
           "none needed" if n_gaps == 0 else
           f"kept, NOT filled in; row after each gap flagged (longest {longest:.0f} s)",
           "Missing readings can't be recovered; inventing them would be making up data.")

    # --- Labels -----------------------------------------------------------
    if "anomaly" in df.columns:
        for column in ["anomaly", "changepoint"]:
            not_binary = int((~df[column].isin([0, 1])).sum())
            record(experiment_id, "label not 0 or 1", not_binary,
                   "none needed" if not_binary == 0 else "kept, flagged in this log",
                   "Labels should only be 0 (normal) or 1.", column)
    else:
        # The anomaly-free file has no label columns. We leave the labels
        # EMPTY rather than filling in 0, so we don't add labels the
        # dataset authors didn't give.
        df["anomaly"] = pd.NA
        df["changepoint"] = pd.NA
        record(experiment_id, "no label columns in file", len(df),
               "label columns added but left empty",
               "The authors describe this file as normal only, but give no labels.")

    # 'Int64' (capital I) is a whole-number type that allows empty values.
    df["anomaly"] = df["anomaly"].astype("Int64")
    df["changepoint"] = df["changepoint"].astype("Int64")

    # --- Identify the experiment ------------------------------------------
    df.insert(0, "experiment_id", experiment_id)
    df.insert(1, "experiment_group", group)
    df.insert(2, "file_name", path.name)
    return df


def check_shared_readings(data):
    """Find readings that appear in more than one file.

    Some files overlap in time (see README). If two files have a row with
    the same timestamp, we check whether all 8 sensor values are the same,
    and whether the two files give that reading the same anomaly label.
    """
    # keep=False marks EVERY row whose timestamp appears more than once.
    shared = data["datetime"].duplicated(keep=False)
    data["flag_shared_with_other_file"] = shared

    # For each shared timestamp: which files have it, are the sensor
    # values identical, and do the labels agree?
    by_time = data[shared].groupby("datetime")
    files = by_time["experiment_id"].agg(lambda ids: " + ".join(sorted(ids)))
    values_identical = by_time[SENSORS].nunique().max(axis=1) == 1
    # nunique() ignores empty labels (the anomaly-free file has none).
    labels_conflict = by_time["anomaly"].nunique() > 1

    conflict_times = labels_conflict[labels_conflict].index
    data["flag_label_conflict"] = data["datetime"].isin(conflict_times)

    summary = pd.DataFrame({"files": files,
                            "identical": values_identical,
                            "conflict": labels_conflict})
    for pair, rows in summary.groupby("files"):
        record(pair, "same readings stored in more than one file", len(rows),
               "kept in both files, flagged",
               "All 8 sensor values identical in "
               f"{int(rows['identical'].sum())} of {len(rows)} shared timestamps. "
               "Files that share readings must stay in the same train/test set.")
        n_conflict = int(rows["conflict"].sum())
        record(pair, "same reading has different anomaly labels in each file",
               n_conflict,
               "none needed" if n_conflict == 0 else "kept, flagged; labels NOT changed",
               "We can't tell which label is right, so we don't pick one.")
    return data


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(RAW_DIR.rglob("*.csv"), key=file_sort_key)
    print(f"Cleaning {len(files)} files from {RAW_DIR}")

    # Clean each file separately, then stack them into one table.
    # Each experiment stays a separate block, identified by experiment_id.
    tables = [clean_one_file(path) for path in files]
    data = pd.concat(tables, ignore_index=True)
    data = check_shared_readings(data)

    data.to_csv(CLEAN_FILE, index=False)
    log_table = pd.DataFrame(log)
    log_table.to_csv(CLEANING_LOG_FILE, index=False)

    # Print only the checks that found something.
    found = log_table[log_table["rows_affected"] > 0]
    summary = found.groupby(["check", "column"], dropna=False).agg(
        files=("experiment_id", "count"), rows=("rows_affected", "sum"))
    print("\nIssues found (all other checks found nothing):")
    print(summary.to_string())
    print(f"\nSaved {len(data)} rows to {CLEAN_FILE}")
    print(f"Saved {len(log_table)} log lines to {CLEANING_LOG_FILE}")


if __name__ == "__main__":
    main()
