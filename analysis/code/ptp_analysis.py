#!/usr/bin/env python3
"""
PTP (linuxptp/ptp4l) log parser + analysis.

- Supports two roles:
  1) boundary: parses "master offset ... path delay ..." + state/fault events
  2) client:   parses "rms ... max ... delay ..." + state events

- Builds:
  - time-series plots (offset/rms/delay) where meaningful
  - per-scenario summary tables (CSV)
  - event tables (CSV) for state transitions and faults

Notes:
- Each input file is a single run for one role+scenario.
- The timestamp inside square brackets (e.g., ptp4l[1538.162]) is used as time (s).
- Units:
  - offset, rms, max, delay, path delay: nanoseconds (ns)
  - time: seconds (s), relative (t - t0)
  - freq: kept as raw "servo units" (not converted)
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import matplotlib.pyplot as plt


# ----------------------------
# Regex patterns (linuxptp ptp4l)
# ----------------------------

# Common prefix: ptp4l[1538.162]:
RE_TS = r"ptp4l\[(?P<t>\d+\.\d+)\]:\s+"

# Boundary: master offset lines
RE_BOUNDARY_SAMPLE = re.compile(
    RE_TS
    + r"master offset\s+(?P<offset>-?\d+)\s+s(?P<sstate>\d)\s+freq\s+(?P<freq>[+-]?\d+)\s+path delay\s+(?P<delay>\d+)"
)

# Client: rms summary lines.
# The logger is not guaranteed to print delay on every line; therefore, the pattern must match:
# - freq +/- <freq_pm> always (it is observed in logs)
# - optional: "delay <delay> +/- <delay_pm>"
RE_CLIENT_SAMPLE = re.compile(
    RE_TS
    + r"rms\s+(?P<rms>\d+)\s+max\s+(?P<max>\d+)\s+freq\s+(?P<freq>[+-]?\d+)\s+\+/-\s+(?P<freq_pm>\d+)"
    + r"(?:\s+delay\s+(?P<delay>\d+)(?:\s+\+/-\s+(?P<delay_pm>\d+))?)?"
)

# State transitions (both roles)
RE_STATE = re.compile(
    RE_TS
    + r"port\s+(?P<port>\d+):\s+(?P<from>[A-Z_]+)\s+to\s+(?P<to>[A-Z_]+)\s+on\s+(?P<reason>[A-Z0-9_]+)"
)

# Fault lines (boundary often)
RE_FAULT = re.compile(RE_TS + r".*\bFAULTY\b.*")
RE_FAULT_DETECTED = re.compile(RE_TS + r".*FAULT_DETECTED.*")

# Best master selection (useful diagnostic)
RE_BEST_MASTER = re.compile(RE_TS + r"selected best master clock\s+(?P<gm>[0-9a-f]+\.[0-9a-f]+\.[0-9a-f]+)")
RE_FOREIGN_NOT_PTP_TIMESCALE = re.compile(RE_TS + r"foreign master not using PTP timescale")

# New foreign master
RE_NEW_FOREIGN = re.compile(RE_TS + r"port\s+(?P<port>\d+):\s+new foreign master\s+(?P<fm>[0-9a-f]+\.[0-9a-f]+\.[0-9a-f]+-\d+)")


# ----------------------------
# Data containers
# ----------------------------

@dataclass
class ParsedRun:
    role: str                 # "boundary" or "client"
    scenario: str             # "low" / "medium" / "high" or free label
    source_file: Path

    samples: pd.DataFrame     # time-series numeric samples
    events: pd.DataFrame      # state / other events


# ----------------------------
# Parsing
# ----------------------------

def _read_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _normalize_time(df: pd.DataFrame, t_col: str = "t") -> pd.DataFrame:
    if df.empty:
        return df
    t0 = df[t_col].min()
    df = df.copy()
    df["t_rel_s"] = df[t_col] - t0
    return df


def parse_ptp4l_log(path: Path, role: str, scenario: str) -> ParsedRun:
    """
    Parses a single ptp4l log file for the given role+scenario.

    The caller chooses the role because boundary/client formats differ and
    auto-detection is error-prone in mixed logs.
    """
    lines = _read_lines(path)

    sample_rows: List[Dict] = []
    event_rows: List[Dict] = []

    for line in lines:
        # State transitions
        m = RE_STATE.search(line)
        if m:
            event_rows.append({
                "t": float(m.group("t")),
                "type": "state",
                "port": int(m.group("port")),
                "from": m.group("from"),
                "to": m.group("to"),
                "reason": m.group("reason"),
                "raw": line.strip(),
            })
            continue

        # Fault detection
        if RE_FAULT.search(line) or RE_FAULT_DETECTED.search(line):
            mt = re.search(RE_TS, line)
            if mt:
                event_rows.append({
                    "t": float(mt.group("t")),
                    "type": "fault",
                    "port": None,
                    "from": None,
                    "to": None,
                    "reason": None,
                    "raw": line.strip(),
                })
            continue

        # Best master clock
        m = RE_BEST_MASTER.search(line)
        if m:
            event_rows.append({
                "t": float(re.search(RE_TS, line).group("t")),
                "type": "best_master",
                "port": None,
                "from": None,
                "to": None,
                "reason": m.group("gm"),
                "raw": line.strip(),
            })
            continue

        # Foreign master not using PTP timescale
        if RE_FOREIGN_NOT_PTP_TIMESCALE.search(line):
            mt = re.search(RE_TS, line)
            if mt:
                event_rows.append({
                    "t": float(mt.group("t")),
                    "type": "ptp_timescale_mismatch",
                    "port": None,
                    "from": None,
                    "to": None,
                    "reason": None,
                    "raw": line.strip(),
                })
            continue

        # New foreign master
        m = RE_NEW_FOREIGN.search(line)
        if m:
            event_rows.append({
                "t": float(re.search(RE_TS, line).group("t")),
                "type": "new_foreign_master",
                "port": int(m.group("port")),
                "from": None,
                "to": None,
                "reason": m.group("fm"),
                "raw": line.strip(),
            })
            continue

        # Numeric samples
        if role == "boundary":
            m = RE_BOUNDARY_SAMPLE.search(line)
            if m:
                sample_rows.append({
                    "t": float(m.group("t")),
                    "offset_ns": int(m.group("offset")),
                    "servo_state": int(m.group("sstate")),       # s0/s1/s2 -> 0/1/2
                    "freq_raw": int(m.group("freq")),            # kept raw (servo units)
                    "path_delay_ns": int(m.group("delay")),
                    "raw": line.strip(),
                })
                continue

        elif role == "client":
            m = RE_CLIENT_SAMPLE.search(line)
            if m:
                row = {
                    "t": float(m.group("t")),
                    "rms_ns": int(m.group("rms")),
                    "max_ns": int(m.group("max")),
                    "freq_raw": int(m.group("freq")),
                    "freq_pm_raw": int(m.group("freq_pm")) if m.group("freq_pm") else None,
                    "path_delay_ns": int(m.group("delay")) if m.group("delay") else None,
                    "path_delay_pm_ns": int(m.group("delay_pm")) if m.group("delay_pm") else None,
                    "raw": line.strip(),
                }
                sample_rows.append(row)
                continue

        else:
            raise ValueError(f"Unknown role: {role}")

    samples = pd.DataFrame(sample_rows)
    events = pd.DataFrame(event_rows)

    if not samples.empty:
        samples = _normalize_time(samples, "t")
    if not events.empty:
        events = _normalize_time(events, "t")

    return ParsedRun(role=role, scenario=scenario, source_file=path, samples=samples, events=events)


# ----------------------------
# Metrics / summaries
# ----------------------------

def _find_first_time(events: pd.DataFrame, predicate) -> Optional[float]:
    if events.empty:
        return None
    sub = events[predicate(events)]
    if sub.empty:
        return None
    return float(sub["t_rel_s"].min())


def compute_convergence_time_boundary(events: pd.DataFrame) -> Optional[float]:
    """
    Boundary convergence: first transition to SLAVE (UNCALIBRATED -> SLAVE) on any port.

    This implementation takes the earliest SLAVE transition as "convergence".
    """
    def pred(df: pd.DataFrame) -> pd.Series:
        return (df["type"] == "state") & (df["to"] == "SLAVE")
    return _find_first_time(events, pred)


def compute_convergence_time_client(events: pd.DataFrame) -> Optional[float]:
    """
    Client convergence: first transition to SLAVE (UNCALIBRATED -> SLAVE).
    """
    def pred(df: pd.DataFrame) -> pd.Series:
        return (df["type"] == "state") & (df["to"] == "SLAVE")
    return _find_first_time(events, pred)


def summarize_boundary(run: ParsedRun) -> pd.DataFrame:
    """
    Produces per-run summary for boundary.

    Post-lock statistics are computed on servo_state == 2 (s2) if available.
    """
    assert run.role == "boundary"
    s = run.samples
    e = run.events

    conv_s = compute_convergence_time_boundary(e)

    # Fault stats
    fault_count = int((e["type"] == "fault").sum()) if not e.empty else 0

    # Post-lock filter
    post = s[s["servo_state"] == 2].copy() if not s.empty and "servo_state" in s.columns else pd.DataFrame()
    # Fallback if no s2 exists: leave post-lock stats empty
    def safe_stat(series: pd.Series, fn):
        return fn(series) if series is not None and not series.empty else None

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "source_file": str(run.source_file),
        "convergence_time_s": conv_s,
        "fault_count": fault_count,

        # Offset stats post-lock (ns)
        "offset_mean_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.mean())),
        "offset_std_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.std(ddof=1))),
        "offset_p50_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.50))),
        "offset_p95_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.95))),
        "offset_p99_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.99))),
        "offset_maxabs_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.abs().max())),

        # Path delay stats post-lock (ns)
        "path_delay_mean_ns_s2": safe_stat(post.get("path_delay_ns"), lambda x: float(x.mean())),
        "path_delay_std_ns_s2": safe_stat(post.get("path_delay_ns"), lambda x: float(x.std(ddof=1))),
    }
    return pd.DataFrame([out])


def summarize_client(run: ParsedRun) -> pd.DataFrame:
    """
    Produces per-run summary for client.

    Post-lock statistics are computed on samples after the SLAVE transition time (if present).
    If the run never reaches SLAVE, summary highlights "locked=False" and avoids meaningless stats.
    """
    assert run.role == "client"
    s = run.samples
    e = run.events

    conv_s = compute_convergence_time_client(e)
    locked = conv_s is not None

    # Post-lock samples: t_rel >= convergence
    post = s[s["t_rel_s"] >= conv_s].copy() if locked and not s.empty else pd.DataFrame()

    def safe_stat(series: pd.Series, fn):
        return fn(series) if series is not None and not series.empty else None

    reselection_count = int((e["type"] == "best_master").sum()) if not e.empty else 0

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "source_file": str(run.source_file),
        "locked": locked,
        "convergence_time_s": conv_s,
        "best_master_reselection_count": reselection_count,

        # RMS stats post-lock (ns)
        "rms_mean_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.mean())),
        "rms_std_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.std(ddof=1))),
        "rms_p95_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.quantile(0.95))),
        "rms_max_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.max())),

        # Max-offset (ns) post-lock (if present)
        "max_mean_ns_post": safe_stat(post.get("max_ns"), lambda x: float(x.mean())),
        "max_max_ns_post": safe_stat(post.get("max_ns"), lambda x: float(x.max())),

        # Delay stats post-lock (ns) when available
        "path_delay_mean_ns_post": safe_stat(post.get("path_delay_ns").dropna() if "path_delay_ns" in post else None,
                                             lambda x: float(x.mean())),
        "path_delay_std_ns_post": safe_stat(post.get("path_delay_ns").dropna() if "path_delay_ns" in post else None,
                                            lambda x: float(x.std(ddof=1))),
    }
    return pd.DataFrame([out])


# ----------------------------
# Plotting
# ----------------------------

def _plot_series(df: pd.DataFrame, x: str, y: str, title: str, ylabel: str, outpath: Path) -> None:
    """
    Plots a single time series.
    """
    if df.empty or y not in df.columns:
        return
    plt.figure()
    plt.plot(df[x], df[y])
    plt.title(title)
    plt.xlabel("time (s, relative)")
    plt.ylabel(ylabel)
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def plot_boundary(run: ParsedRun, outdir: Path) -> None:
    """
    Boundary plots:
    - offset vs time
    - path delay vs time
    - offset vs time (post-lock only) if s2 exists
    """
    s = run.samples
    if s.empty:
        return

    _plot_series(
        s, "t_rel_s", "offset_ns",
        f"PTP boundary offset (ns) - {run.scenario}",
        "offset (ns)",
        outdir / f"boundary_{run.scenario}_offset_ns.png"
    )

    _plot_series(
        s, "t_rel_s", "path_delay_ns",
        f"PTP boundary path delay (ns) - {run.scenario}",
        "path delay (ns)",
        outdir / f"boundary_{run.scenario}_path_delay_ns.png"
    )

    if "servo_state" in s.columns:
        post = s[s["servo_state"] == 2].copy()
        if not post.empty:
            _plot_series(
                post, "t_rel_s", "offset_ns",
                f"PTP boundary offset post-lock (s2) - {run.scenario}",
                "offset (ns)",
                outdir / f"boundary_{run.scenario}_offset_ns_postlock_s2.png"
            )


def plot_client(run: ParsedRun, outdir: Path) -> None:
    """
    Client plots:
    - RMS vs time (only if samples exist)
    - path delay vs time (only if present)
    """
    s = run.samples
    if s.empty:
        return

    _plot_series(
        s, "t_rel_s", "rms_ns",
        f"PTP client RMS offset (ns) - {run.scenario}",
        "RMS offset (ns)",
        outdir / f"client_{run.scenario}_rms_ns.png"
    )

    if "path_delay_ns" in s.columns and s["path_delay_ns"].notna().any():
        _plot_series(
            s.dropna(subset=["path_delay_ns"]), "t_rel_s", "path_delay_ns",
            f"PTP client path delay (ns) - {run.scenario}",
            "path delay (ns)",
            outdir / f"client_{run.scenario}_path_delay_ns.png"
        )


# ----------------------------
# IO helpers
# ----------------------------

def infer_role_and_scenario_from_filename(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Tries to infer role and scenario from filename patterns like:
      boundary_low.log, client_medium.txt, ptp_client_high.log
    """
    name = path.stem.lower()
    role = None
    scenario = None

    if "boundary" in name:
        role = "boundary"
    elif "client" in name:
        role = "client"

    for sc in ("low", "medium", "high"):
        if sc in name:
            scenario = sc
            break

    return role, scenario


def ensure_outdir(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Parse ptp4l logs and generate summaries/plots.")
    ap.add_argument("inputs", nargs="+", type=Path, help="Log files (one per run).")
    ap.add_argument(
        "--outdir",
        type=Path,
        default=Path("/home/gabrielemenestrina/tesi_sync_lab/analysis"),
        help="Base analysis directory",
    )
    ap.add_argument(
        "--role",
        choices=["boundary", "client"],
        default=None,
        help="Forces role for all inputs (otherwise inferred from filename).",
    )
    ap.add_argument(
        "--scenario",
        choices=["low", "medium", "high"],
        default=None,
        help="Forces scenario for all inputs (otherwise inferred from filename).",
    )
    args = ap.parse_args()

    outdir: Path = args.outdir

    # Ensures base output directories exist.
    ensure_outdir(outdir)

    # PTP-specific output directories.
    parser_dir = outdir / "parser_ptp"
    plots_dir = outdir / "plots_ptp"
    parser_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    runs: List[ParsedRun] = []

    for p in args.inputs:
        role = args.role
        scenario = args.scenario

        # Infers missing metadata from filename, if not forced.
        if role is None or scenario is None:
            r_i, s_i = infer_role_and_scenario_from_filename(p)
            role = role or r_i
            scenario = scenario or s_i

        if role is None or scenario is None:
            raise ValueError(
                f"Cannot infer role/scenario from filename: {p.name}. "
                f"Use --role and/or --scenario."
            )

        run = parse_ptp4l_log(p, role=role, scenario=scenario)
        runs.append(run)

        # Exports parsed tables for transparency.
        if not run.samples.empty:
            run.samples.to_csv(parser_dir / f"{role}_{scenario}_samples.csv", index=False)
        if not run.events.empty:
            run.events.to_csv(parser_dir / f"{role}_{scenario}_events.csv", index=False)

        # Produces role-specific plots.
        if role == "boundary":
            plot_boundary(run, plots_dir)
        else:
            plot_client(run, plots_dir)

    # Aggregates summaries across runs.
    boundary_summaries: List[pd.DataFrame] = []
    client_summaries: List[pd.DataFrame] = []

    for run in runs:
        if run.role == "boundary":
            boundary_summaries.append(summarize_boundary(run))
        elif run.role == "client":
            client_summaries.append(summarize_client(run))

    if boundary_summaries:
        pd.concat(boundary_summaries, ignore_index=True).to_csv(
            parser_dir / "boundary_summary.csv", index=False
        )
    if client_summaries:
        pd.concat(client_summaries, ignore_index=True).to_csv(
            parser_dir / "client_summary.csv", index=False
        )


if __name__ == "__main__":
    main()
