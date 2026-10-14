# Sensor Fault Detection & Maintenance Prioritisation

Analyses multi-sensor time-series data from a water-pump testbed (vibration, current, pressure, temperature and more). The project detects abnormal behaviour, measures how well the detectors work against labelled data, and produces a maintenance summary.

> This project **detects anomalies**. It does **not** predict equipment failure.

## Project structure

```
data/raw/SKAB/     Original SKAB data, unchanged (35 CSV files + licence)
data/processed/    Cleaned data, cleaning log and train/test split (made by the scripts)
src/               Python scripts
notebooks/         Jupyter notebooks
figures/           Saved plots
reports/           Findings, summary tables and (later) the maintenance summary
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## How to run

Run these from the project folder, in this order. Each step uses the output of the one before.

```bash
.venv/bin/python src/inspect_data.py   # Phase 1: print a summary of the raw data (changes nothing)
.venv/bin/python src/clean_data.py     # Phase 2: check the data, save data/processed/skab_clean.csv + cleaning_log.csv
.venv/bin/python src/make_split.py     # Phase 2: decide tuning/test files, save data/processed/split.csv
.venv/bin/python src/explore_data.py   # Phase 2: summary tables in reports/, plots in figures/
```

`skab_clean.csv` (about 7 MB) is not stored in git, because `clean_data.py` rebuilds it from the raw data in a few seconds. The cleaning log and the split are stored in git.

| Script | What it does |
|---|---|
| `src/common.py` | Shared settings: file paths, sensor names, units and plot colours |
| `src/clean_data.py` | Runs checks on every file and flags problems in extra columns. No reading is deleted or changed. |
| `src/make_split.py` | Splits whole experiment files into tuning and test sets, with a fixed random seed |
| `src/explore_data.py` | Summary statistics and plots, using only the anomaly-free and tuning files |

Phase 2 results are written up in [reports/phase2_findings.md](reports/phase2_findings.md).

Built with Python 3.14, pandas 3.0.6, NumPy 2.5.4, Matplotlib 3.11.2.

## Data Sources

**Dataset:** SKAB, the Skoltech Anomaly Benchmark, v0.9
- **Official repository:** https://github.com/waico/SKAB (maintained by the dataset authors)
- **Dataset DOI (Kaggle):** https://doi.org/10.34740/KAGGLE/DSV/1693952
- **Authors:** Iurii D. Katser and Vyacheslav O. Kozitsin, Skolkovo Institute of Science and Technology (Skoltech), 2020
- **Licence:** GNU General Public License v3.0 (GPL-3.0). A copy is kept at `data/raw/SKAB/LICENSE`.
- **Downloaded:** 2026-10-14, from the `master` branch at commit `b2c0d46c2971dcbfe71e26087b6d231998bb91c2` (last updated 2024-08-11)

**What the data represents:** Readings from sensors on a laboratory testbed, which is a water circulation loop driven by an electric motor and pump. In each experiment the machine ran normally, then the researchers deliberately caused a fault and later removed it. The faults were:
- `valve1/` (16 files): partly closing the valve at the pump **inlet**
- `valve2/` (4 files): partly closing the valve at the pump **outlet**
- `other/` (14 files): fluid leaks and additions, rotor imbalance with different patterns (sharp, linear, step, impulse, exponential), changes in water volume, cavitation, and hotter water supply
- `anomaly-free/` (1 file): normal operation only, with no labels

**Columns** (units from the official README):

| Column | Meaning | Unit |
|---|---|---|
| `datetime` | Time the reading was written to the database | YYYY-MM-DD hh:mm:ss |
| `Accelerometer1RMS` | Vibration acceleration (RMS), sensor 1 | g |
| `Accelerometer2RMS` | Vibration acceleration (RMS), sensor 2 | g |
| `Current` | Electric motor current | A |
| `Pressure` | Pressure in the loop after the pump | bar |
| `Temperature` | Temperature of the motor body | °C |
| `Thermocouple` | Temperature of the fluid in the loop | °C |
| `Voltage` | Electric motor voltage | V |
| `Volume Flow RateRMS` | Fluid flow rate in the loop | L/min |
| `anomaly` | 1 = row is inside the anomaly period, 0 = normal | – |
| `changepoint` | 1 = row marks a change in machine state | – |

**Size:** 35 CSV files with 46,806 rows in total. Each labelled file has 745–1,327 rows (about 12–23 minutes), and the anomaly-free file has 9,405 rows (about 2.8 hours). Readings are taken about once per second.

**Derived files** (no other data sources are used): everything in `data/processed/`, `figures/` and `reports/` is made by the scripts in `src/` from the raw SKAB files above. `data/raw/` is never modified.

## Assumptions

- **The `anomaly` column is our ground truth.** We measure detector performance against it.
- **The sampling interval is 1 second.** This is the median gap between rows in every file. Occasional longer gaps exist (see Limitations).
- **The timezone is unknown.** Timestamps are treated as local time in the order recorded.
- **Our reading of the changepoints is not documented.** In most files there are 4 changepoints: at the first anomaly row, partway through the anomaly, near its end, and at the first normal row afterwards. We think they mark transition phases, but the official README does not explain this, so we will use the `anomaly` column for evaluation.
- **The documentation has small errors, and the data files are correct.** The data README numbers files `1–16` and `1–4`, but the real files are `0–15` (valve1) and `0–3` (valve2). The main README names the flow column `RateRMS`, but in the files it is `Volume Flow RateRMS`. The main README says "34 datasets" in one place and "35" in another. We count 35 files: 34 labelled and 1 anomaly-free.
- **Fault descriptions for `other/` files come from the SKAB data README.** Unlike the valve folders, the `other/` file numbers there (1–14) match the real file names.

**Cleaning (Phase 2)**
- **Nothing is deleted or changed. Problems are flagged.** `clean_data.py` adds True/False columns (`flag_...`) and writes every check to `data/processed/cleaning_log.csv`, including checks that found nothing.
- **Physical lower limits.** Vibration and flow are RMS values, so they can't be negative. We assume current and voltage are reported as magnitudes, so they can't be negative either (the docs don't say). Temperatures can't be below −273.15 °C. Pressure can't be below a perfect vacuum, −1.01325 bar in gauge terms.
- **Negative pressure is kept.** The docs don't say whether pressure is gauge (relative to the air) or absolute. Gauge pressure can be negative, so we keep these values and flag them with `flag_negative_pressure`.
- **A gap longer than 2 seconds counts as missing readings.** The row after the gap is flagged. No readings are filled in.
- **The anomaly-free file's labels are left empty**, not set to 0. The authors describe it as normal only, but don't give labels.
- **Each file is a separate experiment.** Rows carry `experiment_id`, `experiment_group` and `file_name`. Files are stacked in one table but never merged into one timeline.

**Train/test split (Phase 2, decided before any detector)**
- **Split by whole files, not rows.** Neighbouring rows are almost identical, so a random-row split would put near-copies of test rows into the tuning set.
- **The anomaly-free file is the normal reference.** In each fault group (valve1, valve2, other), about 30% of files go to test and the rest to tuning, chosen at random with a fixed seed (42). Result: 24 tuning and 10 test files (valve1 11/5, valve2 3/1, other 10/4).
- **Files that share readings stay together.** `other/2`–`4`, `other/10`–`11` and `other/12`–`13` are each kept in one set. `other/5` shares readings with the anomaly-free file, so it is always in tuning.
- **Phase 2 exploration uses only the anomaly-free and tuning files.** The test files are not looked at until Phase 4.

**Exploration (Phase 2)**
- **Rolling window: the past 60 seconds.** This is long enough to smooth second-to-second noise and short compared with an anomaly period (about 400 s). The window is measured in time, so gaps don't stretch it, and it only looks backwards, as a live detector would.
- **"Clear change" means a mean shift of 2 or more normal standard deviations** within the same experiment. This is a simple cut-off we chose for describing the data, not a detector setting.
- **Rows with conflicting labels are left out of the normal-vs-anomaly comparison**, and a reading stored in two files is counted once.

## Limitations

- **Laboratory testbed, induced faults.** The faults were caused on purpose under controlled conditions, so results may not carry over to machines in real service, where faults develop naturally and over longer periods.
- **Small dataset.** There are 34 short experiments, each with exactly one continuous anomaly period, and only one anomaly-free recording.
- **Anomalies are far more common than in real life.** 34.9% of labelled rows are anomalous. In real operation faults are much rarer, so precision and false-alarm numbers from this data will look better than they would in practice.
- **Some timestamp gaps.** Most consecutive rows are 1–2 s apart. A few files have larger gaps, up to 247 s in `other/2.csv`, and 33–76 s in several others. There are no missing values.
- **Overlapping time ranges.** Some files overlap in time. For example, `anomaly-free.csv` runs until 16:16:47 on 2020-02-08, but `other/5.csv` starts at 16:06:48 that same day. `other/2`–`3`, `other/3`–`4`, `other/10`–`11` and `other/12`–`13` also overlap. The documentation does not explain this. Phase 2 found that **in every overlap the readings are identical**: the same 1,290 readings are stored in two files.
- **The same reading sometimes has different labels in two files.** `other/12` labels 178 shared readings as anomalies, but `other/13` labels them normal. `other/3` labels 57 shared readings as anomalies, but `other/4` labels them normal. We can't tell which is right, so labels are not changed. These rows are flagged with `flag_label_conflict`. `other/12`–`13` are in the test set, so Phase 4 must handle them.
- **Three different normal operating points.** Normal flow is about 127 L/min on 2020-02-08 (anomaly-free run, `other/5`–`11`), about 76 L/min on 2020-03-01 (`other/2`–`4`), and about 32 L/min on 2020-03-09 (all valve files). Current and vibration differ in the same way. So the anomaly-free run only describes "normal" for the 2020-02-08 experiments. The docs don't explain the difference.
- **Pressure readings are very coarse.** They take only about 10 distinct values, about 0.328 bar apart, so small pressure changes can't be seen. 7 readings (−1.257 bar) are below a perfect vacuum, which is physically impossible. They are kept and flagged with `flag_impossible_value`.
- **Some fault types appear only in tuning or only in test.** The `other/` folder holds many fault types with one or a few files each. Rotor imbalance and water-volume changes are only in tuning. Cavitation and hot water supply are only in test. Test results for those faults will show whether a detector generalises to a fault it wasn't tuned on, but each rests on one or two files.
- **Small test set.** 10 experiment files, so Phase 4 results will have wide uncertainty.
- **GPL-3.0 licence.** The data is redistributed here unchanged, with its licence and credit to the authors. GPL is normally a software licence, so check its terms before reusing this data elsewhere.
- **No failure prediction.** The labels mark anomaly periods. They do not record failures or time until failure, so this project cannot and does not predict failures.
