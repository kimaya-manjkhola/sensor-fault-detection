# Sensor Fault Detection & Maintenance Prioritisation

Analyses multi-sensor time-series data from a water-pump testbed (vibration, current, pressure, temperature and more). The project detects abnormal behaviour, measures how well the detectors work against labelled data, and produces a maintenance summary.

> This project **detects anomalies**. It does **not** predict equipment failure.

## Project structure

```
data/raw/SKAB/     Original SKAB data, unchanged (35 CSV files + licence)
data/processed/    Cleaned / combined data (created in later phases)
src/               Python scripts
notebooks/         Jupyter notebooks
figures/           Saved plots
reports/           Maintenance summary and results
```

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/inspect_data.py   # prints a summary of the raw data
```

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

## Assumptions

- **The `anomaly` column is our ground truth.** We measure detector performance against it.
- **The sampling interval is 1 second.** This is the median gap between rows in every file. Occasional longer gaps exist (see Limitations).
- **The timezone is unknown.** Timestamps are treated as local time in the order recorded.
- **Our reading of the changepoints is not documented.** In most files there are 4 changepoints: at the first anomaly row, partway through the anomaly, near its end, and at the first normal row afterwards. We think they mark transition phases, but the official README does not explain this, so we will use the `anomaly` column for evaluation.
- **The documentation has small errors, and the data files are correct.** The data README numbers files `1–16` and `1–4`, but the real files are `0–15` (valve1) and `0–3` (valve2). The main README names the flow column `RateRMS`, but in the files it is `Volume Flow RateRMS`. The main README says "34 datasets" in one place and "35" in another. We count 35 files: 34 labelled and 1 anomaly-free.

## Limitations

- **Laboratory testbed, induced faults.** The faults were caused on purpose under controlled conditions, so results may not carry over to machines in real service, where faults develop naturally and over longer periods.
- **Small dataset.** There are 34 short experiments, each with exactly one continuous anomaly period, and only one anomaly-free recording.
- **Anomalies are far more common than in real life.** 34.9% of labelled rows are anomalous. In real operation faults are much rarer, so precision and false-alarm numbers from this data will look better than they would in practice.
- **Some timestamp gaps.** Most consecutive rows are 1–2 s apart. A few files have larger gaps, up to 247 s in `other/2.csv`, and 33–76 s in several others. There are no missing values.
- **Overlapping time ranges.** Some files overlap in time. For example, `anomaly-free.csv` runs until 16:16:47 on 2020-02-08, but `other/5.csv` starts at 16:06:48 that same day. `other/2`–`3`, `other/3`–`4`, `other/10`–`11` and `other/12`–`13` also overlap. The documentation does not explain this, so it is an open question.
- **GPL-3.0 licence.** The data is redistributed here unchanged, with its licence and credit to the authors. GPL is normally a software licence, so check its terms before reusing this data elsewhere.
- **No failure prediction.** The labels mark anomaly periods. They do not record failures or time until failure, so this project cannot and does not predict failures.
