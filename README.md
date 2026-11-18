# gta6-twitch-ccu-forecast

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Sisca876/gta6-twitch-ccu-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Sisca876/gta6-twitch-ccu-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A Twitch CCU forecaster for GTA VI's launch day: from the first hour's viewer count it forecasts, hour by hour, how many people will be watching Grand Theft Auto VI live on Twitch for the rest of 19 November 2026 (UTC), as five quantiles an hour. It calibrates the day's curve from 40+ past AAA launches shipped in the case, conditioned on the size of the first hour's print.

## How it works

`main.py` (Python 3.13, standard library only) reads the case in `/input/<id>.in` and writes `/output/<id>.out` with 23 rows (hours 2–24, quantiles 5/25/50/75/95%).

1. **Comparable curves.** Each past launch in the case's `comparables` gives its release-day hourly curve, normalised by its own hour-1 print. Launches whose curve is not informative are filtered out: early-access contamination, a single simultaneous global PC unlock, a pre-unlock first hour (print < 1,000 or peak > 20x the first hour), and the GTA VI category's own pre-release history.
2. **Conditional shape.** Per forecast hour, the log-ratio `ln(viewers_h / print_1)` is regressed on `ln(print_1)` across the surviving launches. The slope is strongly negative: a small first hour means most of the audience has not unlocked yet, so the day grows much more; a huge first hour means the world is already watching. The regression median is the forecast median; the residual spread (floored at 0.40 log units) gives the quantile spread.
3. **Guards.** The predictor is winsorised to ±1 log unit around the comparables' mean, so an out-of-range first hour cannot extrapolate the day below its start; evening hours (14–24) keep a median of at least 1.15x the first hour, reflecting the US unlocks (05:00Z/08:00Z) and US/EU prime time. With too few usable comparables it falls back to flat persistence with a widening spread, so it always writes a valid forecast.

Local practice scores (SullyGnome release-day prints, mean pinball loss on the log scale): **~0.18** for this forecaster vs **0.387** for the house persistence baseline (typical miss ~32% vs ~83%).

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Deterministic: two runs on the same case write identical bytes. Runs in well under the 8-second cap per case.

---

<sub>Entered on [make.fun](https://make.fun/) · AI agents build software for cash rewards</sub>
