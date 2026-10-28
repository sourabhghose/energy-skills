"""Shared helpers for EnergyBench planted-truth generators (stdlib only).

Every generator writes agent-visible files into `out` and returns the answer key, computed from the
values exactly as written (after rounding), so an independent re-computation from the files matches.
"""

from __future__ import annotations

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
LB_PER_TONNE = 2204.62262
MMBTU_TO_GJ = 1.055056
M3_TO_SCF = 35.3147


def rng_for(task_id: str, seed: int) -> random.Random:
    """String seeds are hashed with SHA-512 by `random`, so this is stable across processes and platforms."""
    return random.Random(f"energybench:{task_id}:{seed}")


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def lognormal(rng: random.Random, mu: float, sigma: float) -> float:
    return math.exp(rng.gauss(mu, sigma))


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method; fine for the small rates used here."""
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def hours_between(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    out, t = [], start
    while t < end:
        out.append(t)
        t += step
    return out


def fmt_local(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def fmt_utc(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    """n-th weekday (Mon=0) of a month; n=-1 is the last one."""
    if n > 0:
        first = datetime(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    nxt = datetime(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def us_holidays(year: int) -> set[str]:
    days = [
        datetime(year, 1, 1), nth_weekday(year, 5, 0, -1), datetime(year, 7, 4),
        nth_weekday(year, 9, 0, 1), nth_weekday(year, 11, 3, 4), datetime(year, 12, 25),
    ]
    return {d.strftime("%Y-%m-%d") for d in days}


def readme(out: Path, title: str, lines: list[str]) -> None:
    """A short data dictionary the agent can read, as a real data owner would provide."""
    write_text(out / "README.md", f"# {title}\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
