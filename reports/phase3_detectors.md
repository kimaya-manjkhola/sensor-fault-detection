# Phase 3: threshold and rolling-statistics detectors

**Data used:** the 24 **tuning** experiments and the anomaly-free run only. The 10 test experiments were not loaded (the script stops if one appears). These are **tuning** results. They show how the settings were chosen, not how well the detectors work on unseen data. That is Phase 4.

**Made by:** `src/detectors.py` (the detectors) and `src/tune_detectors.py` (tuning, alarm lists and plots). All numbers below come from the CSV files in `reports/` named in each section.

## 1. Baseline: the first 5 minutes of each experiment

Each experiment learns its own "normal" from its first **300 seconds**. That's because the machine ran at different operating points on different days (Phase 2). The length was fixed before the labels were checked. To be transparent: the anomaly start times had been printed once before the check was written, and 300 s was kept as originally proposed.

Check against the labels (`reports/phase3_baseline_check.csv`):

- **22 of 24 tuning files:** the baseline is fully labelled normal, with no gaps. Each has 280–289 readings.
- **`other/4`: not certainly normal.** Its first 57 readings are labelled normal in `other/4`, but the *same* readings are labelled anomaly in `other/3` (Phase 2's label conflict). These 57 readings are **left out of other/4's baseline**, which is then learned from the remaining 227 readings.
- **`other/2`: labelled normal, but short.** A 247-second gap in the data starts inside the window, so the baseline readings only cover 107 s (104 readings). The fault starts at 354 s, right after the gap. The baseline is used as it is, but it is less reliable.
- **Anomaly-free run:** no labels (the authors describe it as normal only), 281 readings.
- No sensor had a standard deviation of zero in any baseline. A zero would make every later reading look abnormal.

Readings inside the baseline are **never scored**, because the detector learned from them.

## 2. The two detectors

Both work on each sensor separately, against that experiment's own baseline mean and standard deviation (std).

- **Detector 1 (fixed threshold):** a reading is flagged if it is more than **k × baseline std** away from the baseline mean.
- **Detector 2 (rolling statistics):** a sensor is flagged if, over the **last W seconds**,
  - the average has moved more than **k × baseline std** from the baseline mean (the level changed), or
  - the std is more than **m × baseline std** (the signal got shakier).

**Pressure is not used** by either detector. Its readings only take about 10 values, about 0.328 bar apart, so a single step between levels is huge compared with its normal spread, and small real changes can't be seen at all.

### The persistence rule (N seconds), in plain words

A single odd reading is usually noise, not a fault. So a sensor's flag only becomes an **alarm** once it has stayed on, **without a break, for at least N seconds**. When the flag goes off, the alarm stops. A time gap in the data also restarts the count, because we don't know what happened during the gap. This rule only looks at the past, so it could run live on a real machine. The cost is that every alarm starts at least N seconds late.

### Which sensor caused the alarm

The persistence rule is applied **to each sensor separately**. The machine is "in alarm" while at least one sensor is in alarm. Every alarm is saved with its start, end and the list of sensors that were in alarm during it (`reports/phase3_alarms_tuning.csv`). The maintenance summary will need this.

## 3. How the detectors were scored

All scores are counted **per second** (per reading), only **after the baseline**, and **without the 235 conflicting-label readings**:

- **Precision:** of the seconds in alarm, the share labelled anomaly.
- **Recall:** of the seconds labelled anomaly, the share in alarm.
- **False-alarm rate:** of the seconds labelled normal, the share in alarm.

Some extra measures help with the choice:
- **Faults detected:** how many of the 24 tuning faults had at least one alarm during the labelled period.
- **False-alarm events:** separate alarms that never touch a labelled anomaly.
- **Median delay:** seconds from the start of a fault to its first alarm.
- **Anomaly-free share of time in alarm,** over the first 15 minutes after its baseline (about the same length as a fault experiment) and over the whole 2.8-hour run.

**Important for reading precision:** 46.9% of the scored seconds are labelled anomaly. So a "detector" that is *always* in alarm would already score 0.47 precision. In real operation faults are much rarer, so precision would be lower.

## 4. Settings tried

212 settings in total (all in `reports/phase3_tuning_results.csv`):

- **Threshold detector:** k ∈ {3, 4, 5, 6, 8}, N ∈ {0, 5, 10, 20, 30} s
- **Rolling detector:** window W ∈ {30, 60, 120} s, k ∈ {3, 5, 8}, m ∈ {2, 3, 5}, N ∈ {0, 10, 30} s
- **Sensor set,** both detectors: all 7 sensors, or without the two temperature sensors

A selection of them, showing the trade-offs (★ = chosen):

| Detector | Sensors | W | k | m | N | Precision | Recall | False-alarm rate | Faults detected | False-alarm events | Median delay (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| threshold | all 7 | – | 3 | – | 10 | 0.65 | 0.79 | 0.382 | 24/24 | 33 | 28 |
| threshold | no temps | – | 3 | – | 0 | 0.83 | 0.63 | 0.113 | 24/24 | 439 | 2.5 |
| threshold | no temps | – | 3 | – | 5 | 0.92 | 0.49 | 0.040 | 18/24 | 27 | 28.5 |
| **threshold ★** | **no temps** | – | **3** | – | **10** | **0.93** | **0.47** | **0.031** | **16/24** | **13** | **32.5** |
| threshold | no temps | – | 3 | – | 30 | 0.96 | 0.42 | 0.016 | 15/24 | 6 | 66 |
| threshold | no temps | – | 5 | – | 0 | 0.94 | 0.49 | 0.029 | 21/24 | 94 | 16 |
| threshold | no temps | – | 5 | – | 10 | 0.98 | 0.36 | 0.008 | 13/24 | 5 | 55 |
| rolling | all 7 | 30 | 5 | 2 | 10 | 0.69 | 0.63 | 0.248 | 22/24 | 13 | 25 |
| rolling | no temps | 30 | 3 | 2 | 10 | 0.86 | 0.66 | 0.097 | 21/24 | 13 | 25 |
| rolling | no temps | 30 | 5 | 2 | 0 | 0.89 | 0.47 | 0.053 | 19/24 | 11 | 15 |
| **rolling ★** | **no temps** | **30** | **5** | **2** | **10** | **0.90** | **0.44** | **0.042** | **19/24** | **11** | **25** |
| rolling | no temps | 60 | 5 | 2 | 10 | 0.85 | 0.47 | 0.071 | 17/24 | 9 | 41 |
| rolling | no temps | 120 | 5 | 2 | 10 | 0.78 | 0.50 | 0.126 | 18/24 | 9 | 65 |
| rolling | no temps | 30 | 5 | 5 | 10 | 0.92 | 0.42 | 0.032 | 14/24 | 5 | 54.5 |
| rolling | no temps | 30 | 8 | 2 | 10 | 0.90 | 0.29 | 0.028 | 18/24 | 14 | 23.5 |

What the table shows:

- **Temperatures cause most false alarms.** With all 7 sensors, no setting gets the false-alarm rate below 9.7% (threshold) or 11.7% (rolling). The temperatures drift slowly in normal running, so after a few minutes they leave the narrow band learned in the baseline. This matches Phase 2, where neither temperature showed a clear change during faults.
- **Persistence (N) removes noise but adds delay.** For the threshold detector at k = 3, going from N = 0 to N = 10 cuts false-alarm events from 439 to 13. The cost is that 8 faults go undetected and the median delay rises from 2.5 s to 32.5 s.
- **Bigger k or m means fewer false alarms but more missed faults.**
- **Longer rolling windows *raise* the false-alarm rate.** The rolling mean keeps "remembering" the fault for up to a window length after it ends, so the alarm runs on into seconds labelled normal. They also react more slowly (median delay 25 s → 65 s).

## 5. How one setting per detector was chosen, and why

**First attempt: highest F1 score.** This did not work.
- The highest F1 (0.76) is the rolling detector at k = 3 with no persistence, which is in alarm for 11% of normal seconds.
- Settings with all 7 sensors are in alarm for 45–46% of normal seconds, yet score almost the same F1 (0.75).

Because nearly half the scored seconds are anomalies, F1 barely penalises alarming most of the time.

**Rule used instead** (chosen after seeing the F1 problem, still only on tuning data):
1. At most **5% of normal seconds** in alarm, and
2. At most **24 false-alarm events** across the 24 tuning files (one per experiment on average), then
3. The **highest recall**, with ties broken by more faults detected.

The reason: for maintenance, false alarms cost technician time and teach people to ignore alarms. So we first cap them, then catch as much as we can.

**Chosen settings:**

- **Threshold:** k = 3, N = 10 s, without temperatures.
- **Rolling:** window = 30 s, k = 5, m = 2, N = 10 s, without temperatures.
  - **Why a 30-second window:** it had the highest recall within the limits. A rolling mean over 30 readings already smooths out most second-to-second noise. And as shown above, longer windows react more slowly and keep alarming after the fault has ended.

| | Threshold ★ | Rolling ★ |
|---|---|---|
| Precision | 0.93 | 0.90 |
| Recall | 0.47 | 0.44 |
| False-alarm rate | 3.1% | 4.2% |
| Faults detected | 16 / 24 | 19 / 24 |
| False-alarm events | 13 | 11 |
| Median delay | 32.5 s | 25 s |
| Anomaly-free, first 15 min after baseline | 5.0% of time in alarm | 0.0% |
| Anomaly-free, whole 2.8 h run | 89% of time in alarm | 88% |

## 6. Which faults were caught, and by which sensors

From `reports/phase3_alarms_per_experiment.csv`:

- **Rotor imbalance (other/5–9):** caught by both detectors through the **vibration** sensors, except the impulse-imbalance file `other/8`, which only the rolling detector caught (through the rolling-std test).
- **Leaks (other/2–4):** caught by both. `other/3` and `other/4` were caught through **flow**; `other/2` through vibration 1.
- **Water volume changes (other/10, 11):** caught by both, through **flow and vibration**. In other/10 both detectors used vibration 2. In other/11 the threshold detector used vibration 2 and the rolling detector vibration 1.
- **Valve experiments (14 files):** mostly through **flow**. The threshold detector caught 7 of 14 and the rolling detector 9 of 14. The rolling detector caught valve2/0 and valve2/2 through vibration 1. **Missed by both:** valve1/0, valve1/1, valve1/2 and valve1/4. valve1/0 is the Phase 2 example, where the flow drop was only about 1 L/min, close to the sensor's 1 L/min resolution.

Recall per second is below 0.5 for both detectors. So even in caught faults, the alarms cover only part of the labelled period. We haven't yet analysed file by file why this happens.

## 7. What these results do NOT show

- **Not test results.** The settings were chosen *on* these files, so these numbers are optimistic. Phase 4 measures performance on the 10 held-out test files.
- **The baseline only stays valid for minutes, not hours.** In the 2.8-hour anomaly-free run, both detectors are in alarm about 88–89% of the time. That's because vibration and flow slowly drift away from their first 5 minutes. A real machine would need the baseline re-learned regularly. The fault experiments are only about 20 minutes long, so this doesn't show up in them.
- **Leaving out the temperatures is a tuning decision**, based on the tuning data. It means these detectors can't respond to a fault that *only* shows in temperature. The test set includes one such candidate, "water supply at increased temperature" (other/14).
- **Precision is inflated** by the high share of anomaly seconds (47%) in this dataset.

## Figures

| File | What it shows |
|---|---|
| `figures/f_detector_alarms_valve1_0.png` | valve1/0: sensors with both detectors' alarms. **No alarms**: a missed fault. |
| `figures/g_detector_alarms_other_5.png` | other/5 (sharp rotor imbalance): both detectors alarm on vibration during the fault. Both also give a short false alarm at about 16:13, and the threshold detector gives another just after the fault ends. |
