"""
inspect_data.py - Phase 1: look at the raw SKAB data WITHOUT changing it.

What this script does:
  1. Finds every CSV file in data/raw/SKAB.
  2. Loads each one with pandas (read-only - nothing is saved back).
  3. Prints, per file: number of rows, time range, sampling interval,
     missing values and how many rows are labelled as anomalies.
  4. Prints a total at the end.

Run it from the project folder with:
    .venv/bin/python src/inspect_data.py
"""

from pathlib import Path

import pandas as pd

# Folder where the raw SKAB files live (relative to the project folder).
RAW_DIR = Path("data/raw/SKAB")


def load_skab_file(path):
    """Load one SKAB CSV file into a pandas DataFrame (a table).

    SKAB files use ';' (semicolon) between values instead of ','.
    We also tell pandas to read the 'datetime' column as real dates.
    """
    return pd.read_csv(path, sep=";", parse_dates=["datetime"])


def describe_file(path):
    """Return a dictionary of simple facts about one file."""
    df = load_skab_file(path)

    # Time between consecutive rows, in seconds.
    # .diff() subtracts each timestamp from the one after it.
    gaps = df["datetime"].diff().dt.total_seconds().dropna()

    info = {
        "group": path.parent.name,             # e.g. 'valve1'
        "file": path.name,                     # e.g. '0.csv'
        "rows": len(df),
        "start": df["datetime"].min(),
        "end": df["datetime"].max(),
        "median_gap_s": gaps.median(),         # the typical sampling interval
        "min_gap_s": gaps.min(),
        "max_gap_s": gaps.max(),
        "missing_values": int(df.isna().sum().sum()),
    }

    # The anomaly-free file has no label columns, so we check first.
    if "anomaly" in df.columns:
        info["anomaly_rows"] = int(df["anomaly"].sum())
        info["changepoints"] = int(df["changepoint"].sum())
    else:
        info["anomaly_rows"] = None
        info["changepoints"] = None

    return info


def main():
    # Find all CSV files in all sub-folders, sorted so output is predictable.
    files = sorted(RAW_DIR.rglob("*.csv"))
    print(f"Found {len(files)} CSV files in {RAW_DIR}\n")

    # Show the column names once, using the first labelled file.
    example = load_skab_file(RAW_DIR / "valve1" / "0.csv")
    print("Columns:", list(example.columns))
    print("\nData types:")
    print(example.dtypes, "\n")

    # Build one summary row per file and show them as a table.
    summary = pd.DataFrame([describe_file(f) for f in files])
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 100)
    print(summary.to_string(index=False))

    # Totals by group (folder).
    print("\nFiles and rows per group:")
    print(summary.groupby("group").agg(files=("file", "count"),
                                       rows=("rows", "sum"),
                                       anomaly_rows=("anomaly_rows", "sum")))

    print("\nTotal rows:", summary["rows"].sum())
    labelled = summary.dropna(subset=["anomaly_rows"])
    share = labelled["anomaly_rows"].sum() / labelled["rows"].sum()
    print(f"Share of labelled rows marked anomalous: {share:.1%}")


if __name__ == "__main__":
    main()
