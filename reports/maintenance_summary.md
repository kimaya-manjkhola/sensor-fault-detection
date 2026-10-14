# Maintenance summary: water-pump testbed (SKAB)

**What this is:** a list of pump test runs ranked by how strongly the sensors moved away from that run's own normal behaviour. It is an **anomaly detector**: it flags unusual readings. **It does not predict failures** or say how long equipment will last.

**How it works, in one line:** each run learns "normal" from its first 5 minutes. After that, an alarm is raised when a sensor's 30-second average moves more than 5× its normal spread, when the sensor gets more than 2× as jumpy as normal, or when a temperature changes more than 6× faster than normal, for at least 10 seconds. Pressure and temperature *levels* are not used. Every run is watched for the same 15 minutes after its baseline.

**Full alarm list:** `reports/alarm_log.csv`, 80 alarms. Each row has its sensors, its peak deviation and a plain-English reason.

## What to investigate first

| Priority | Run | Score | What the alarms show | Main signals |
|---|---|---|---|---|
| 1 | other/5 | 67 | Vibration jumps sharply (30-s spread up to 109× normal) and stays high; about 8 minutes in alarm | Vibration 1 & 2 |
| 2 | other/13 | 66 | In alarm about 9 of its 15 minutes, starting *before* its fault; then flow collapses and becomes 78× as jumpy as normal. **Check the baseline first** (see caveats). | Flow, Vibration 1 |
| 3 | other/7 | 65 | Vibration level jumps 171–176× above normal for over 6 minutes | Vibration 1 & 2 |
| 4 | other/9 | 64 | Vibration level 127–160× above normal; flow 7× below normal | Vibration 1 & 2, flow |
| 5 | other/14 | 61 | Fluid temperature rising very fast (+8 °C/min, 191× normal rate); flow 6× above normal | Fluid temp., flow, vibration 1 |

Next in line: other/6, other/12, other/10, other/8 and valve1/12 (scores 45–59). The full ranking is in `reports/priority_ranking.csv`, and the top 10 are in `figures/l_top10_priority.png`.

**Why these first:** the score adds up three things, each worth up to a third:
- **How long** the run was in alarm (share of the 15 minutes),
- **How severe** the largest deviation was (log scale: 10× normal spread = half marks, 100× = full marks),
- **How many** of the 7 watched signals alarmed.

Score = 100 × (duration + severity + sensors) ÷ 3. The anomaly labels are **not** used.

**What triggers alarms most** (`figures/m_alarms_per_signal.png`): flow (49 alarms), vibration 1 (19), vibration 2 (13), motor-temperature rate (11) and fluid-temperature rate (8). Motor current and voltage never triggered an alarm.

## How good is this ranking? (checked against the labels afterwards)

- **Every run except one contains a real fault.** So the ranking mostly shows *how visible* each fault was in the sensors, not *whether* a run is faulty. With only one fault-free run, we can't measure how well it separates healthy runs from faulty ones.
- **Most alarm time is real.** 86% of all alarm time falls inside labelled faults. Of the 73 alarms with clear labels, 47 touch a fault and 26 don't (26 false alarms).
- **The top of the list is dominated by rotor imbalance** (4 of the top 6, with vibration 100–256× normal spread), plus cavitation and hot water. Valve and leak faults rank lower because their flow changes are smaller (about 2–18× normal spread).
  - **The score measures how big the sensor change is, not how serious the fault is mechanically.**
- **3 of the top 10 are high partly for the wrong reasons:**
  - **other/13:** only 38% of its alarm time is inside the fault. A weak baseline caused alarms before the fault.
  - **other/12:** only 5% inside. Most of its fault period has conflicting labels and can't be checked, and most of its checkable alarm time is before or after the fault.
  - **other/8:** 21% inside.
- **Lower down:** valve1/2 ranks 19th entirely because of an alarm *before* its fault.
- **At the bottom:** three real faults raised **no alarm** at all (valve1/3, valve1/4, valve1/6). They score 0, tied with the fault-free run.

## Main caveats

1. **Laboratory testbed, faults caused on purpose,** in short runs (about 20 minutes). Real machines, with faults that develop slowly, may behave differently.
2. **Small faults in flow are missed.** In the missed valve faults, flow moved by only about 2–5× its normal spread (below the alarm limit), or crossed the limit only in short bursts.
3. **The baseline must be normal.** Alarms only mean "different from this run's first 5 minutes". If the start of a run is unusual (as in other/13), everything after it looks abnormal. If a run lasts hours, normal slow drift also triggers alarms: over the whole 2.8-hour fault-free run (after its baseline), the detector is in alarm about 88% of the time, compared with 0% in its first 15 minutes. The baseline would need re-learning regularly.
4. **False alarms:** on the 10 held-out test runs, 13% of normal time was in alarm, about 10 false alarms per hour of normal running. That is far too many for a real plant without further tuning.
5. **Only 10 test runs,** so all performance figures are uncertain (see `reports/phase4_evaluation.md`).
6. **Not a failure predictor.** An alarm is a reason to look, not a diagnosis.
