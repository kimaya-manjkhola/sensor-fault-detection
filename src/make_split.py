"""
make_split.py - Phase 2: decide which experiments are used for tuning and
which are kept back for the final test. Decided ONCE, before any detector
exists, so the test set can't influence how we build the detectors.

Rules:
  - Split by whole files (experiments), never by random rows. Rows next to
    each other in time are almost identical, so a random-row split would
    put near-copies of test rows into the tuning set.
  - The anomaly-free file is the "normal reference" (what normal looks like).
  - About 70% of fault files -> tuning, 30% -> test, done separately for
    each fault group (valve1, valve2, other) so every group is in both sets.
  - Files that share readings (found by clean_data.py) always go into the
    same set, and a file that shares readings with the normal reference
    always goes into tuning. Otherwise the same reading could be used for
    tuning AND testing.
  - A fixed random seed makes the split the same every time it is run.

Output: data/processed/split.csv (one row per file).

Run it AFTER clean_data.py, from the project folder:
    .venv/bin/python src/make_split.py
"""

import numpy as np
import pandas as pd

from common import SPLIT_FILE, load_clean_data

TEST_FRACTION = 0.3
RANDOM_SEED = 42
NORMAL_REFERENCE = "anomaly-free/anomaly-free"

# What each experiment simulated, copied from the SKAB data README
# (data/raw/SKAB/README.md). Valve files share one description per folder.
FAULT_DESCRIPTIONS = {
    "anomaly-free": "Normal operation only",
    "valve1": "Valve at the pump inlet partly closed",
    "valve2": "Valve at the pump outlet partly closed",
    "other/1": "Fluid leaks and fluid additions",
    "other/2": "Fluid leaks and fluid additions",
    "other/3": "Fluid leaks and fluid additions",
    "other/4": "Fluid leaks and fluid additions",
    "other/5": "Rotor imbalance, sharp",
    "other/6": "Rotor imbalance, linear",
    "other/7": "Rotor imbalance, step",
    "other/8": "Rotor imbalance, impulse (Dirac delta)",
    "other/9": "Rotor imbalance, exponential",
    "other/10": "Slow increase in the amount of water in the circuit",
    "other/11": "Sudden increase in the amount of water in the circuit",
    "other/12": "Draining water from the tank until cavitation",
    "other/13": "Two-phase flow at the pump inlet (cavitation)",
    "other/14": "Water supply at increased temperature",
}


def find_linked_files(data):
    """Return groups of files that share at least one reading.

    Example: other/2 shares readings with other/3, and other/3 with
    other/4, so all three end up in one group {other/2, other/3, other/4}.
    """
    shared = data[data["flag_shared_with_other_file"]]
    # For each shared timestamp, the set of files that contain it.
    pairs = shared.groupby("datetime")["experiment_id"].agg(frozenset).unique()

    groups = []
    for pair in pairs:
        merged = set(pair)
        # Join any existing group that has a file in common with this pair.
        for group in [g for g in groups if g & merged]:
            merged |= group
            groups.remove(group)
        groups.append(merged)
    return groups


def number_of(experiment_id):
    """'valve1/12' -> 12, so files sort as 0, 1, 2 ... 10 (not 0, 1, 10, 2)."""
    stem = experiment_id.split("/")[1]
    return int(stem) if stem.isdigit() else -1


def main():
    data = load_clean_data()

    # One row per experiment, with its size and number of anomaly rows.
    files = data.groupby("experiment_id").agg(
        experiment_group=("experiment_group", "first"),
        file_name=("file_name", "first"),
        rows=("datetime", "size"),
        anomaly_rows=("anomaly", "sum"),
    ).reset_index()
    files["anomaly_rows"] = files["anomaly_rows"].astype(int)  # 401.0 -> 401
    files["sort_number"] = files["experiment_id"].map(number_of)
    files = files.sort_values(["experiment_group", "sort_number"])

    linked_groups = find_linked_files(data)
    linked_with = {}
    for group in linked_groups:
        for experiment_id in group:
            others = sorted(group - {experiment_id}, key=number_of)
            linked_with[experiment_id] = ", ".join(others)
    files["linked_with"] = files["experiment_id"].map(linked_with).fillna("")

    # Files linked to the normal reference must be in tuning (see top).
    must_tune = set()
    for group in linked_groups:
        if NORMAL_REFERENCE in group:
            must_tune |= group - {NORMAL_REFERENCE}

    role = {NORMAL_REFERENCE: "normal_reference"}
    rng = np.random.default_rng(RANDOM_SEED)

    for fault_group in ["valve1", "valve2", "other"]:
        ids = files.loc[files["experiment_group"] == fault_group, "experiment_id"].tolist()
        target_test = round(TEST_FRACTION * len(ids))

        # "Units" are what we pick from: a linked group counts as one unit,
        # every other file is a unit on its own.
        units = []
        for experiment_id in ids:
            if any(experiment_id in unit for unit in units):
                continue  # already added as part of a linked group
            group = next((g for g in linked_groups if experiment_id in g), {experiment_id})
            units.append(sorted(group - {NORMAL_REFERENCE}, key=number_of))

        # Go through the units in a random (but fixed-seed) order and put
        # each into test if it still fits under the target number of files.
        n_test = 0
        for i in rng.permutation(len(units)):
            unit = units[i]
            fits = n_test + len(unit) <= target_test
            if fits and not (set(unit) & must_tune):
                n_test += len(unit)
                for experiment_id in unit:
                    role[experiment_id] = "test"
        for experiment_id in ids:
            role.setdefault(experiment_id, "tuning")

    files["role"] = files["experiment_id"].map(role)
    files["fault_description"] = [
        FAULT_DESCRIPTIONS.get(e, FAULT_DESCRIPTIONS.get(g))
        for e, g in zip(files["experiment_id"], files["experiment_group"])
    ]

    columns = ["experiment_id", "experiment_group", "file_name", "role", "rows",
               "anomaly_rows", "linked_with", "fault_description"]
    files[columns].to_csv(SPLIT_FILE, index=False)

    print(files[columns].to_string(index=False))
    print("\nFiles per role and group:")
    print(pd.crosstab(files["experiment_group"], files["role"], margins=True))
    print(f"\nSaved split to {SPLIT_FILE}")


if __name__ == "__main__":
    main()
