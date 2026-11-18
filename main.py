"""GTA VI launch-day Twitch CCU forecaster (gta6-twitch-ccu-forecast-01).

Reads one case (/input/<id>.in) and writes /output/<id>.out: for each of hours
2..24 of the release day (UTC), five quantiles (5/25/50/75/95%) of the Twitch
concurrent viewers in the Grand Theft Auto VI category.

Method (stdlib only, deterministic, no network, no randomness):
  The case ships `comparables`: past big game launches' hourly Twitch curves
  from 14 days before to 3 days after their release day. For each comparable
  we take its release-day curve normalised by its own hour-1 print, then, per
  forecast hour, regress the log-ratio ln(viewers_h / print_1) on ln(print_1)
  across the comparable launches. The slope is strongly negative (a small
  first-hour print means most of the audience has not unlocked yet, so the day
  grows much more; a huge first hour means the world is already watching, so
  the day stays flatter) -- on the kit's 38 comparables the correlation of
  ln(print_1) with ln(peak/print_1) is about -0.8. The regression median is
  the forecast median; the residual spread, widened to a floor, gives the
  quantile spread. The predictor is winsorised to +-1 log unit around the
  comparables' mean so an out-of-range first hour cannot extrapolate the day
  below its start, and evening hours (14..24) keep a median of at least 1.15x
  the first hour: the US unlocks (05:00Z/08:00Z) and US/EU prime time sit in
  those hours for a rolling-midnight console launch.

  Comparables are filtered to launches whose release-day curve is actually
  informative: no early-access contamination, no single simultaneous global
  PC unlock, a meaningful hour-1 print (>= 1000 viewers), a peak no more than
  20x the first hour (a tiny first hour is a pre-unlock hour, not a launch
  hour), and the GTA VI category's own pre-release history is left out. With
  too few usable comparables the program falls back to a flat persistence
  forecast with a widening spread, so it always writes a valid forecast.

Local practice scores (SullyGnome release-day prints, pinball loss log-scale):
  this forecaster ~0.18, house persistence baseline 0.387.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so a module
# shipped beside this file imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Regression / spread constants, calibrated on the kit's comparables.
MIN_COMPARABLES = 5        # fewer usable launches -> persistence fallback
MIN_HOURS = 20             # a comparable needs this many release-day hours
MIN_P1 = 1000.0            # a first-hour print below this is pre-unlock noise
MAX_PEAK_RATIO = 20.0      # peak / first-hour above this: first hour pre-unlock
SD_MULT = 0.8              # residual sd is shrunk a little (small sample)
SD_FLOOR = 0.40            # log units; honest uncertainty floor
PREDICTOR_CLAMP = 1.0      # winsorise ln(p1) - mean ln(p1) to +- this
EVENING_FLOOR = 1.15       # median ratio floor for hours 14..24 (US unlock)
BASELINE_SIGMA = 0.15      # fallback persistence spread, as the house baseline


def parse_time(value):
    """ISO-8601 UTC timestamp -> aware datetime (handles a trailing Z)."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def round2(x):
    """x rounded to 2 decimals, half up, as JavaScript Math.round(x*100)/100."""
    scaled = x * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100.0
    return int(value) if value == int(value) else value


def smooth(values):
    """3-point moving average (edges use the points that exist)."""
    out = []
    for i in range(len(values)):
        window = values[max(0, i - 1):min(len(values), i + 2)]
        out.append(sum(window) / len(window))
    return out


def usable_comparable(comp):
    """A comparable's release-day curve, or None when it is not usable.

    Returns (p1, {hour: viewers}) with hours 1..24 of the comparable's own
    release day (its day_start), or None.
    """
    unlock = str(comp.get("unlock") or "").lower()
    name = str(comp.get("name") or "").lower()
    if "not a launch" in unlock or "before release" in name:
        return None  # the target game's own pre-release history, not a launch
    if "early-access-contaminated" in unlock:
        return None  # early-access players already playing: curve distorted
    if "pc single global" in unlock or "simultaneous midnight gmt" in unlock:
        return None  # one worldwide PC unlock: a different day shape
    try:
        day_start = parse_time(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    hours = {}
    for row in comp.get("hourly") or []:
        try:
            viewers = row["viewers"]
            at = parse_time(row["from"])
        except (KeyError, TypeError, ValueError):
            continue
        if viewers is None or viewers <= 0:
            continue
        offset = (at - day_start).total_seconds() / 3600.0
        if 0 <= offset < 24:
            hours[int(offset) + 1] = float(viewers)
    if 1 not in hours or len(hours) < MIN_HOURS:
        return None
    p1 = hours[1]
    if p1 < MIN_P1:
        return None
    if max(hours.values()) / p1 > MAX_PEAK_RATIO:
        return None
    return p1, hours


def fit_shape(curves):
    """Per-hour regression of log-ratio on log first-hour print.

    curves: list of (p1, {hour: viewers}). Returns {hour: (a, b, mx, sd)} for
    hours 2..24, with a/b/sd smoothed across neighbouring hours, or None when
    too few curves survive.
    """
    if len(curves) < MIN_COMPARABLES:
        return None
    raw = {}
    for hour in range(2, 25):
        points = [
            (math.log(p1), math.log(hours[hour] / p1))
            for p1, hours in curves if hour in hours
        ]
        if len(points) < MIN_COMPARABLES:
            continue  # too sparse an hour: filled from its neighbours below
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        n = len(points)
        mx = sum(xs) / n
        my = sum(ys) / n
        vx = sum((x - mx) ** 2 for x in xs) / n
        slope = (
            sum((x - mx) * (y - my) for x, y in points) / n / vx if vx > 0 else 0.0
        )
        resid = [y - (my + slope * (x - mx)) for x, y in points]
        var = sum(r * r for r in resid) / n
        raw[hour] = {
            "a": my,
            "b": slope,
            "mx": mx,
            "sd": math.sqrt(var) if var > 0 else 0.30,
        }
    if not raw:
        return None
    # Fill a sparse hour from the nearest fitted hours (linear interpolation
    # between bracketing hours, nearest hour's fit at the edges).
    shape = {}
    fitted = sorted(raw)
    for hour in range(2, 25):
        if hour in raw:
            shape[hour] = dict(raw[hour])
            continue
        below = [h for h in fitted if h < hour]
        above = [h for h in fitted if h > hour]
        if below and above:
            lo, hi = max(below), min(above)
            w = (hour - lo) / (hi - lo)
            shape[hour] = {
                key: raw[lo][key] * (1 - w) + raw[hi][key] * w
                for key in ("a", "b", "mx", "sd")
            }
        elif below:
            shape[hour] = dict(raw[max(below)])
        else:
            shape[hour] = dict(raw[min(above)])
    for key in ("a", "b", "sd"):
        smoothed = smooth([shape[h][key] for h in range(2, 25)])
        for i, hour in enumerate(range(2, 25)):
            shape[hour][key] = smoothed[i]
    return shape


def hour_quantiles(shape, p1, hour):
    """The five quantiles for one hour from the fitted shape."""
    fit = shape[hour]
    d = math.log(p1) - fit["mx"]
    d = max(-PREDICTOR_CLAMP, min(PREDICTOR_CLAMP, d))
    med = fit["a"] + fit["b"] * d
    if hour >= 14:
        med = max(med, math.log(EVENING_FLOOR))
    sd = max(SD_MULT * fit["sd"], SD_FLOOR)
    quantiles = []
    for z in Z:
        value = p1 * math.exp(med + z * sd)
        value = max(1.0, min(1e9, value))
        quantiles.append(round2(value))
    for i in range(1, 5):
        quantiles[i] = max(quantiles[i], quantiles[i - 1])
    return quantiles


def baseline_quantiles(p1, hour):
    """Persistence fallback: every hour stays at the first hour's print."""
    quantiles = [
        round2(p1 * math.exp(z * BASELINE_SIGMA * math.sqrt(hour - 1)))
        for z in Z
    ]
    return [max(1.0, min(1e9, q)) for q in quantiles]


def forecast_case(case, name):
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError(f"{name} has no hour-1 print")
    p1 = max(1.0, float(first["viewers"]))
    curves = []
    for comp in case.get("comparables") or []:
        parsed = usable_comparable(comp)
        if parsed is not None:
            curves.append(parsed)
    # Deterministic order regardless of the case file's listing.
    curves.sort(key=lambda c: (c[0], len(c[1])))
    shape = fit_shape(curves)
    rows = []
    for row in case["forecast"]:
        hour = row["hour"]
        if shape is not None:
            q = hour_quantiles(shape, p1, hour)
        else:
            q = baseline_quantiles(p1, hour)
        rows.append({"hour": hour, "q": q})
    rows.sort(key=lambda r: r["hour"])
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case, path.name)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
