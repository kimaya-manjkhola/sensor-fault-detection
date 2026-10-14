"""
run_all.py - run the whole project from start to finish with one command.

Each step is a separate script; they run in this order because each one
uses the files made by the one before. If a step fails, the run stops.

Run it from the project folder:
    .venv/bin/python src/run_all.py
"""

import subprocess
import sys
import time

from common import PROJECT_DIR

STEPS = [
    ("inspect_data.py", "Phase 1: summary of the raw data (changes nothing)"),
    ("clean_data.py", "Phase 2: checks and cleaned data"),
    ("make_split.py", "Phase 2: tuning / test split"),
    ("explore_data.py", "Phase 2: statistics and plots"),
    ("tune_detectors.py", "Phase 3 + 3b: tune the detectors on tuning files"),
    ("evaluate_test.py", "Phase 4: evaluate on the test files"),
    ("maintenance_summary.py", "Phase 5: alarm log and priority ranking"),
    ("make_headline_figure.py", "README headline figure"),
]


def main():
    started = time.time()
    for script, description in STEPS:
        print(f"\n=== {script}: {description} ===", flush=True)
        # sys.executable = the Python running this file (the project's .venv).
        # cwd=PROJECT_DIR because inspect_data.py uses paths relative to it.
        subprocess.run([sys.executable, str(PROJECT_DIR / "src" / script)],
                       cwd=PROJECT_DIR, check=True)
    print(f"\nAll {len(STEPS)} steps finished in {time.time() - started:.0f} s.")


if __name__ == "__main__":
    main()
