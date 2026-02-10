#!/usr/bin/env python3
"""
Chrony series parser + plotting.

Inputs (per scenario directory, e.g. chrony_low/):
- chrony_tracking_series.txt
- chrony_sourcestats_series.txt

Outputs (under --outdir, default analysis/):
- parser_chrony/: CSV parsed tables
- plots_chrony/:  PNG time-series

Notes:
- tracking: extracts both "System time" (signed, seconds slow/fast) and "Last offset" (seconds).
  Default plot metric is "system_time" because it represents the effective clock error of the node.
- sourcestats: extracts Offset and Std Dev (per source).

Units:
- tracking offsets are in seconds; exported also as microseconds.
- sourcestats Offset supports ns/us/ms/s suffixes; exported as seconds and microseconds.
- sourcestats Std Dev supports ns/us/ms/s suffixes; exported as seconds and microseconds.

Plot scaling requirement:
- For the same plot type across scenarios (low/medium/high), y-axis limits must be shared
  to enable visual comparisons.
- This is applied per metric family:
  - tracking offset (chosen tracking metric)
  - sourcestats offset
  - sourcestats stddev
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt


RE_SAMPLE_HDR = re.compile(r"^=+\s*SAMPLE\s+\d+/\d+\s+@\s+(?P<ts>[^ ]+)\s*=+\s*$")

# tracking lines
RE_TRACKING_SYSTEM_TIME = re.compile(
    r"^System time\s*:\s*(?P<val>[+-]?\d+(?:\.\d+)?)\s+seconds\s+(?P<dir>slow|fast)\s+of\s+NTP\s+time\s*$"
)
RE_TRACKING_LAST_OFFSET = re.compile(r"^Last offset\s*:\s*(?P<val>[+-]?\d+(?:\.\d+)?)\s+seconds\s*$")

# sourcestats row (after header lines)
# Example: servergm  7  5  45  -5.006  9.671  -11us  73us
RE_SOURCESTATS_ROW = re.compile(
    r"^(?P<name>\S+)\s+"
    r"(?P<np>\d+)\s+(?P<nr>\d+)\s+(?P<span>\d+)\s+"
    r"(?P<freq>[+-]?\d+(?:\.\d+)?)\s+(?P<skew>[+-]?\d+(?:\.\d+)?)\s+"
    r"(?P<offset>[+-]?\d+(?:\.\d+)?(?:ns|us|ms|s)?)\s+"
    r"(?P<stddev>[+-]?\d+(?:\.\d+)?(?:ns|us|ms|s)?)\s*$"
)

RE_TABLE_SEPARATOR = re.compile(r"^=+\s*$")


def parse_iso_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_rel_seconds(times: List[datetime]) -> List[float]:
    if not times:
        return []
    t0 = times[0].timestamp()
    return [t.timestamp() - t0 for t in times]


def parse_quantity_with_unit(s: str) -> float:
    """
    Parses values like:
      -11us, -328ns, 0.000424827 (no unit -> seconds by default), 1.2ms, 0.5s
    Returns seconds.
    """
    s = s.strip()
    m = re.fullmatch(r"(?P<num>[+-]?\d+(?:\.\d+)?)(?P<unit>ns|us|ms|s)?", s)
    if not m:
        raise ValueError(f"Cannot parse quantity: {s}")

    num = float(m.group("num"))
    unit = m.group("unit") or "s"

    if unit == "s":
        return num
    if unit == "ms":
        return num * 1e-3
    if unit == "us":
        return num * 1e-6
    if unit == "ns":
        return num * 1e-9

    raise ValueError(f"Unknown unit: {unit}")


@dataclass
class TrackingSeries:
    t: List[datetime]
    system_time_s: List[float]   # signed seconds (slow -> negative local-ref, fast -> positive local-ref)
    last_offset_s: List[float]   # signed seconds


@dataclass
class SourceStatsSeries:
    t: List[datetime]
    source: List[str]
    offset_s: List[float]
    stddev_s: List[float]


def parse_tracking_series(path: Path) -> TrackingSeries:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    times: List[datetime] = []
    system_time_s: List[float] = []
    last_offset_s: List[float] = []

    cur_ts: Optional[datetime] = None
    cur_system: Optional[float] = None
    cur_last: Optional[float] = None

    def flush_sample() -> None:
        nonlocal cur_ts, cur_system, cur_last
        if cur_ts is None:
            return
        if cur_system is None and cur_last is None:
            cur_ts = None
            return
        times.append(cur_ts)
        system_time_s.append(cur_system if cur_system is not None else float("nan"))
        last_offset_s.append(cur_last if cur_last is not None else float("nan"))
        cur_ts = None
        cur_system = None
        cur_last = None

    for line in lines:
        m = RE_SAMPLE_HDR.match(line.strip())
        if m:
            flush_sample()
            cur_ts = parse_iso_ts(m.group("ts"))
            continue

        if cur_ts is None:
            continue

        m = RE_TRACKING_SYSTEM_TIME.match(line.strip())
        if m:
            v = float(m.group("val"))
            dir_ = m.group("dir")
            # Represent clock error as (local - ref):
            # slow => local behind => negative
            # fast => local ahead  => positive
            cur_system = -v if dir_ == "slow" else +v
            continue

        m = RE_TRACKING_LAST_OFFSET.match(line.strip())
        if m:
            cur_last = float(m.group("val"))
            continue

    flush_sample()
    return TrackingSeries(times, system_time_s, last_offset_s)


def parse_sourcestats_series(path: Path) -> SourceStatsSeries:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    times: List[datetime] = []
    sources: List[str] = []
    offsets: List[float] = []
    stddevs: List[float] = []

    cur_ts: Optional[datetime] = None
    in_table = False

    for line in lines:
        ls = line.strip()

        m = RE_SAMPLE_HDR.match(ls)
        if m:
            cur_ts = parse_iso_ts(m.group("ts"))
            in_table = False
            continue

        if cur_ts is None:
            continue

        if RE_TABLE_SEPARATOR.match(ls):
            in_table = True
            continue

        if not in_table:
            continue

        m = RE_SOURCESTATS_ROW.match(ls)
        if m:
            name = m.group("name")
            off_s = parse_quantity_with_unit(m.group("offset"))
            sd_s = parse_quantity_with_unit(m.group("stddev"))

            times.append(cur_ts)
            sources.append(name)
            offsets.append(off_s)
            stddevs.append(sd_s)
            continue

    return SourceStatsSeries(times, sources, offsets, stddevs)


def ensure_dirs(base_outdir: Path) -> Tuple[Path, Path]:
    parser_dir = base_outdir / "parser_chrony"
    plots_dir = base_outdir / "plots_chrony"
    parser_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    return parser_dir, plots_dir


def write_csv(path: Path, header: List[str], rows: List[List[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


YLim = Tuple[float, float]


def _compute_ylim_symmetric(y_all: List[float], pad: float = 0.05) -> Optional[YLim]:
    vals = [v for v in y_all if v == v]  # filters NaN
    if not vals:
        return None
    m = max(abs(v) for v in vals)
    m *= (1.0 + pad)
    return (-m, +m)


def _compute_ylim_positive(y_all: List[float], pad: float = 0.05) -> Optional[YLim]:
    vals = [v for v in y_all if v == v]
    if not vals:
        return None
    vmax = max(vals)
    vmax *= (1.0 + pad)
    return (0.0, vmax)


def plot_series(
    x: List[float],
    y: List[float],
    title: str,
    ylabel: str,
    outpath: Path,
    ylim: Optional[YLim] = None,
) -> None:
    if not x or not y:
        return
    plt.figure()
    plt.plot(x, y)
    plt.title(title)
    plt.xlabel("time (s, relative)")
    plt.ylabel(ylabel)
    if ylim is not None:
        plt.ylim(ylim[0], ylim[1])
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def infer_scenario_from_path(p: Path) -> Optional[str]:
    for part in [p.parent.name.lower(), p.name.lower()]:
        if "low" in part:
            return "low"
        if "medium" in part:
            return "medium"
        if "high" in part:
            return "high"
    return None


def resolve_pairs(
    inputs: List[Path],
    forced_scenario: Optional[str],
) -> List[Tuple[Path, Path, str]]:
    pairs: List[Tuple[Path, Path, str]] = []

    for inp in inputs:
        if inp.is_dir():
            tfile = inp / "chrony_tracking_series.txt"
            sfile = inp / "chrony_sourcestats_series.txt"
            if not tfile.exists() or not sfile.exists():
                raise FileNotFoundError(f"Missing tracking/sourcestats series in directory: {inp}")
            scenario = forced_scenario or infer_scenario_from_path(inp)
            if scenario is None:
                raise ValueError(f"Cannot infer scenario from directory name: {inp.name}")
            pairs.append((tfile, sfile, scenario))
        else:
            scenario = forced_scenario or infer_scenario_from_path(inp)
            if scenario is None:
                raise ValueError(f"Cannot infer scenario from filename/path: {inp}")

            name = inp.name
            if "tracking_series" in name:
                tfile = inp
                sfile = inp.parent / name.replace("tracking_series", "sourcestats_series")
            elif "sourcestats_series" in name:
                sfile = inp
                tfile = inp.parent / name.replace("sourcestats_series", "tracking_series")
            else:
                raise ValueError(
                    f"Unrecognized input file (expected *tracking_series* or *sourcestats_series*): {inp}"
                )

            if not tfile.exists() or not sfile.exists():
                raise FileNotFoundError(f"Missing companion file for: {inp}")

            pairs.append((tfile, sfile, scenario))

    return pairs


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse Chrony tracking+sourcestats series and generate CSV/plots.")
    ap.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Either chrony_* directories or explicit *_tracking_series.txt / *_sourcestats_series.txt files.",
    )
    ap.add_argument(
        "--outdir",
        type=Path,
        default=Path("/home/gabrielemenestrina/tesi_sync_lab/analysis"),
        help="Base analysis directory",
    )
    ap.add_argument(
        "--scenario",
        choices=["low", "medium", "high"],
        default=None,
        help="Forces scenario label (otherwise inferred from folder/filename).",
    )
    ap.add_argument(
        "--tracking-metric",
        choices=["system_time", "last_offset"],
        default="system_time",
        help="Which tracking metric is plotted as 'offset'.",
    )
    args = ap.parse_args()

    base_outdir: Path = args.outdir
    parser_dir, plots_dir = ensure_dirs(base_outdir)

    pairs = resolve_pairs(args.inputs, args.scenario)

    # First pass: parse everything and keep in memory to compute common y-lims across scenarios.
    parsed: Dict[str, Tuple[TrackingSeries, SourceStatsSeries]] = {}
    tracking_rel: Dict[str, List[float]] = {}
    sourcestats_rel: Dict[str, List[float]] = {}

    for tracking_path, sourcestats_path, scenario in pairs:
        tr = parse_tracking_series(tracking_path)
        ss = parse_sourcestats_series(sourcestats_path)

        parsed[scenario] = (tr, ss)
        tracking_rel[scenario] = to_rel_seconds(tr.t)
        sourcestats_rel[scenario] = to_rel_seconds(ss.t)

        # Export CSVs immediately (independent from plotting/scaling).
        tr_rows: List[List[object]] = []
        for i in range(len(tr.t)):
            tr_rows.append([
                tr.t[i].isoformat(),
                tracking_rel[scenario][i],
                tr.system_time_s[i],
                tr.system_time_s[i] * 1e6,
                tr.last_offset_s[i],
                tr.last_offset_s[i] * 1e6,
            ])
        write_csv(
            parser_dir / f"chrony_{scenario}_tracking.csv",
            ["iso_ts", "t_rel_s", "system_time_s", "system_time_us", "last_offset_s", "last_offset_us"],
            tr_rows,
        )

        ss_rows: List[List[object]] = []
        for i in range(len(ss.t)):
            ss_rows.append([
                ss.t[i].isoformat(),
                sourcestats_rel[scenario][i],
                ss.source[i],
                ss.offset_s[i],
                ss.offset_s[i] * 1e6,
                ss.stddev_s[i],
                ss.stddev_s[i] * 1e6,
            ])
        write_csv(
            parser_dir / f"chrony_{scenario}_sourcestats.csv",
            ["iso_ts", "t_rel_s", "source", "offset_s", "offset_us", "stddev_s", "stddev_us"],
            ss_rows,
        )

    # Compute common y-lims across scenarios (per plot family).
    tracking_y_all_us: List[float] = []
    sourcestats_offset_all_us: List[float] = []
    sourcestats_stddev_all_us: List[float] = []

    for scenario, (tr, ss) in parsed.items():
        if args.tracking_metric == "system_time":
            tracking_y_all_us.extend([v * 1e6 for v in tr.system_time_s])
        else:
            tracking_y_all_us.extend([v * 1e6 for v in tr.last_offset_s])

        sourcestats_offset_all_us.extend([v * 1e6 for v in ss.offset_s])
        sourcestats_stddev_all_us.extend([v * 1e6 for v in ss.stddev_s])

    tracking_ylim = _compute_ylim_symmetric(tracking_y_all_us)     # can be negative
    ss_offset_ylim = _compute_ylim_symmetric(sourcestats_offset_all_us)  # can be negative
    ss_stddev_ylim = _compute_ylim_positive(sourcestats_stddev_all_us)   # non-negative

    # Second pass: plot with common y-lims.
    for scenario, (tr, ss) in parsed.items():
        tr_t_rel = tracking_rel[scenario]
        ss_t_rel = sourcestats_rel[scenario]

        if args.tracking_metric == "system_time":
            y = [v * 1e6 for v in tr.system_time_s]
            ylab = "system time offset (us)"
            fname = f"chrony_{scenario}_tracking_system_time_offset_us.png"
            title = f"Chrony tracking offset (system time) - {scenario}"
        else:
            y = [v * 1e6 for v in tr.last_offset_s]
            ylab = "last offset (us)"
            fname = f"chrony_{scenario}_tracking_last_offset_us.png"
            title = f"Chrony tracking offset (last offset) - {scenario}"

        plot_series(
            tr_t_rel,
            y,
            title,
            ylab,
            plots_dir / fname,
            ylim=tracking_ylim,
        )

        plot_series(
            ss_t_rel,
            [v * 1e6 for v in ss.stddev_s],
            f"Chrony sourcestats std dev - {scenario}",
            "std dev (us)",
            plots_dir / f"chrony_{scenario}_sourcestats_stddev_us.png",
            ylim=ss_stddev_ylim,
        )

        plot_series(
            ss_t_rel,
            [v * 1e6 for v in ss.offset_s],
            f"Chrony sourcestats offset - {scenario}",
            "source offset (us)",
            plots_dir / f"chrony_{scenario}_sourcestats_offset_us.png",
            ylim=ss_offset_ylim,
        )


if __name__ == "__main__":
    main()
