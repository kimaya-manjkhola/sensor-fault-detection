# Phase 2 findings: which sensors change during faults?

**Data used:** the anomaly-free run (normal reference) and the 24 **tuning** experiments only. The 10 test experiments were not loaded. See `data/processed/split.csv`.

**Numbers come from:** `reports/phase2_summary_stats.csv`, `reports/phase2_shift_per_experiment.csv` and `reports/phase2_shift_summary.csv`, all made by `src/explore_data.py`.

## How "change" was measured

For each tuning experiment and each sensor, we compared the rows labelled anomaly with the rows labelled normal **in the same experiment**:

- **Mean shift** = (anomaly mean − normal mean) ÷ normal standard deviation. It says how many "normal wobbles" the average moved. A value of 0 means no change.
- **Std ratio** = anomaly standard deviation ÷ normal standard deviation. A value above 1 means the signal got noisier during the anomaly.

A mean shift of **2 or more** (up or down) is counted below as a "clear" change. This cut-off is our own simple choice to describe the data. It is not a detector setting.

Comparing within each experiment matters because of the next finding.

## Finding 1: the machine ran at three different "normal" operating points

The normal rows of the tuning experiments are not alike. They group by the day they were recorded:

| Recorded | Experiments | Normal flow (L/min) | Normal current (A) | Normal vibration 1 (g) |
|---|---|---|---|---|
| 2020-02-08 | anomaly-free, other/5–11 | 125–128 | 2.4–2.5 | 0.21–0.24 |
| 2020-03-01 | other/2–4 (leaks) | 76–77 | 1.6 | 0.08 |
| 2020-03-09 | valve1 and valve2 | 32 | 1.0 | 0.03 |

The **anomaly-free run only matches the 2020-02-08 experiments**. For example, its mean flow is 125.2 L/min, while the normal rows of every valve experiment average about 32 L/min. The SKAB documentation does not explain why the operating point differs, so we don't guess.

**What this means for later phases:** a detector with fixed limits learned from the anomaly-free run would flag every valve experiment as abnormal from its first second. Phase 3 will need to compare each experiment with its own normal behaviour, for example using the readings at its start.

It also means the pooled histograms in figure (c) mostly show the three operating points, not the faults. The many peaks in each panel are those operating points. Because normal and anomaly rows come from the same experiments, the two curves overlap heavily for most sensors.

## Finding 2: which sensors change, and in which experiments

| Sensor | Clear change in tuning experiments | Evidence |
|---|---|---|
| **Vibration 1 and 2** | **Yes, strongly in the rotor-imbalance experiments** | Mean shift +24 to +115 in other/5, 6, 7 and 9. In other/8 (impulse imbalance) the mean didn't move (−0.8 and +0.1), but the std ratio was 4.1 and 6.3, so the signal became spikier. Outside imbalance, the only clear change is vibration 2 in other/11 (sudden increase of water, +2.9). No clear change in any valve or leak experiment (all between −1.2 and +1.2). |
| **Flow rate** | **Yes, in most valve and leak experiments** | Clear fall in 8 of 11 valve1, 2 of 3 valve2 and all 3 leak experiments (other/2–4: −2.6, −3.4, −4.5). Largest: valve1/13 at −13.5. A clear rise in other/10 (slow increase of water, +3.5). Also a fall in other/9 (−2.8). |
| **Motor current** | **No** | Mean shift between −0.2 and +0.2 in all 24 tuning experiments; std ratio 0.9–1.1. |
| **Motor voltage** | **No** | Mean shift between −0.1 and +0.1 in all 24; std ratio 0.9–1.1. |
| **Loop pressure** | **No change visible, but the sensor may be too coarse to show one** | Mean shift between −0.2 and +0.1 in all 24. The readings only take about 10 distinct values, about 0.328 bar apart. So a small real change in pressure would not show up. |
| **Motor temperature** | **No clear mean change** | Mean shift between −1.5 and +1.1. These temperatures drift slowly through each experiment (figure a). |
| **Fluid temperature** | **No clear mean change** | Mean shift between −1.4 and +1.8. Also drifts slowly, e.g. from 26.9 °C to 29.4 °C during the 2.8-hour anomaly-free run (figure a). |

## Finding 3: what the example experiment (valve1/0) shows

valve1/0 was picked as the first valve1 file in the tuning set, not because it looks good. It is actually one of the **weaker** valve examples:

- **Flow** drops only from about 32 to 31–32 L/min during the anomaly (mean shift −0.8, below our cut-off). In this file the flow readings are whole numbers (31, 32 or 33), so the change is close to the sensor's resolution. The 60-second rolling mean (blue line in figure b) shows the drop more clearly than the raw readings.
- **Motor temperature** falls by about 4 °C soon after the anomaly starts (from about 79 °C to 74.5 °C), and its rolling standard deviation peaks at about 1 °C (figure d). But across all 11 valve1 tuning files the median temperature shift is only −0.08, so **this is not typical** and we should not generalise from it.
- Fluid temperature has a short bump of about 0.1 °C during the anomaly.
- Vibration, current, voltage and pressure show no visible change (figures b and d).

## What we can and can't say

- We **can** say: in the tuning data, vibration responds strongly to the rotor-imbalance faults, and flow responds to most valve and leak faults.
- We **can't** yet say how well any of this works as a detector. That is Phase 3 (build) and Phase 4 (measure on the test set).
- Some fault types appear in only one tuning experiment (e.g. the impulse imbalance other/8), so findings about them rest on a single example.
- Current, voltage and pressure showed no clear change in these experiments. This doesn't prove they never respond to faults, and for pressure the coarse readings may hide small changes.

## Figures

| File | What it shows |
|---|---|
| `figures/a_anomaly_free_all_sensors.png` | All 8 sensors over the 2.8-hour anomaly-free run (60-s rolling mean over raw readings) |
| `figures/b_valve1_0_all_sensors.png` | All 8 sensors for valve1/0 (60-s rolling mean over raw readings), labelled anomaly shaded |
| `figures/c_normal_vs_anomaly_distributions.png` | Histograms of labelled-normal vs labelled-anomaly rows in tuning experiments |
| `figures/d_valve1_0_rolling_std.png` | 60-second rolling standard deviation for valve1/0 |

*Phase 6 note: the separate rolling-mean figure (e) was merged into figure b, which now draws the 60-s rolling mean over the raw readings. No numbers changed.*
