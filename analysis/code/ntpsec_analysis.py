#!/usr/bin/env python3
"""
NTPsec (ntpq -p style) log parser + plotting.

Target input format (repeated snapshots):
--- HH:MM:SS ---
     remote           refid      st t when poll reach   delay   offset   jitter
===============================================================================
*peername        refid          10 u   39   64    1   6.7970  -2.7943   0.6513

Outputs (under --outdir, default analysis/):
- parser_ntpsec/: CSV with parsed samples + events + summaries
- plots_ntpsec/:  PNG time-series: offset_ms, jitter_ms, delay_ms

Assumptions:
- delay/offset/jitter are expressed in milliseconds (ms) as in typical ntpq output.
- Each input file contains a single run for one role+scenario.
- If multiple peers are present, the parser extracts:
  - the selected peer (line starting with '*') when present
  - otherwise the first non-header peer line in the snapshot
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
# Regex patterns
# ----------------------------

RE_SNAPSHOT_TS = re.compile(r"^---\s+(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\s+---\s*$")

# Peer line: may start with a selection character (*, +, -, x, o, etc.) or whitespace.
# The first token can be "*boundary1" or "boundary1".
RE_PEER_LINE = re.compile(
    r"^(?P<remote_tok>\S+)\s+"
    r"(?P<refid>\S+)\s+"
    r"(?P<st>\d+)\s+"
    r"(?P<t>\S+)\s+"
    r"(?P<when>\S+)\s+"
    r"(?P<poll>\d+)\s+"
    r"(?P<reach>\S+)\s+"
    r"(?P<delay>-?\d+(?:\.\d+)?)\s+"
    r"(?P<offset>-?\d+(?:\.\d+)?)\s+"
    r"(?P<jitter>-?\d+(?:\.\d+)?)\s*$"
)

HEADER_PREFIXES = (
    "remote", "refid", "====", "=============================================================================="
)


# ----------------------------
# Data containers
# ----------------------------

@dataclass
class ParsedRun:
    role: str            # "boundary" or "client"
    scenario: str        # "low" / "medium" / "high"
    source_file: Path

    samples: pd.DataFrame
    events: pd.DataFrame


# ----------------------------
# Helpers
# ----------------------------

def _read_lines(path: Path) -> List[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _hhmmss_to_seconds(h: int, m: int, s: int) -> int:
    return h * 3600 + m * 60 + s


def _normalize_time(df: pd.DataFrame, t_col: str = "t_s") -> pd.DataFrame:
    if df.empty:
        return df
    t0 = float(df[t_col].min())
    out = df.copy()
    out["t_rel_s"] = out[t_col] - t0
    return out


def infer_role_and_scenario_from_filename(path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Supports filenames like:
      ntp_boundaryHIGH_live.log
      ntp_boundaryLOW_live.log
      ntp_clientMEDIUM_live.log
    Case-insensitive for scenario tokens.
    """
    name = path.stem.lower()

    role = None
    if "boundary" in name:
        role = "boundary"
    elif "client" in name:
        role = "client"

    scenario = None
    # accept both "..._low..." and "...low..." and "...high..."
    for sc in ("low", "medium", "high"):
        if sc in name:
            scenario = sc
            break

    return role, scenario



def ensure_outdir(outdir: Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)


# ----------------------------
# Core parsing
# ----------------------------

def parse_ntpq_snapshots(path: Path, role: str, scenario: str) -> ParsedRun:
    """
    Parses ntpq-like snapshots into a time-series of (delay, offset, jitter, reach, poll, ...).

    Peer selection logic per snapshot:
    - if a '*' peer exists in the snapshot, it is chosen
    - else the first peer line in the snapshot is chosen
    """
    lines = _read_lines(path)

    sample_rows: List[Dict] = []
    event_rows: List[Dict] = []

    current_ts_s: Optional[int] = None
    snapshot_peers: List[Dict] = []

    def flush_snapshot() -> None:
        nonlocal snapshot_peers, current_ts_s, sample_rows, event_rows
        if current_ts_s is None or not snapshot_peers:
            snapshot_peers = []
            return

        # Chooses selected peer if present, else first.
        chosen = None
        for pr in snapshot_peers:
            if pr["selected"]:
                chosen = pr
                break
        if chosen is None:
            chosen = snapshot_peers[0]

        # Emits sample.
        sample_rows.append({
            "t_s": float(current_ts_s),
            "hhmmss": chosen["hhmmss"],
            "remote": chosen["remote"],
            "refid": chosen["refid"],
            "stratum": chosen["stratum"],
            "assoc_type": chosen["assoc_type"],
            "when_s": chosen["when_s"],
            "poll_s": chosen["poll_s"],
            "reach_raw": chosen["reach_raw"],
            "reach_oct": chosen["reach_oct"],
            "selected": chosen["selected"],
            "delay_ms": chosen["delay_ms"],
            "offset_ms": chosen["offset_ms"],
            "jitter_ms": chosen["jitter_ms"],
            "raw": chosen["raw"],
        })

        # Emits events (minimal, useful for later extensions).
        if chosen["refid"] == ".INIT.":
            event_rows.append({
                "t_s": float(current_ts_s),
                "hhmmss": chosen["hhmmss"],
                "type": "init",
                "detail": "refid=.INIT.",
                "raw": chosen["raw"],
            })
        if chosen["selected"]:
            event_rows.append({
                "t_s": float(current_ts_s),
                "hhmmss": chosen["hhmmss"],
                "type": "selected_peer",
                "detail": chosen["remote"],
                "raw": chosen["raw"],
            })

        snapshot_peers = []

    for line in lines:
        line_stripped = line.strip()

        m_ts = RE_SNAPSHOT_TS.match(line_stripped)
        if m_ts:
            # Flush previous snapshot before starting new one.
            flush_snapshot()
            h = int(m_ts.group("h"))
            m = int(m_ts.group("m"))
            s = int(m_ts.group("s"))
            current_ts_s = _hhmmss_to_seconds(h, m, s)
            continue

        if not line_stripped:
            continue

        # Skip header lines.
        if line_stripped.startswith(HEADER_PREFIXES) or line_stripped.startswith("="):
            continue

        # Parse a peer line if inside a snapshot.
        if current_ts_s is None:
            continue

        m_peer = RE_PEER_LINE.match(line_stripped)
        if not m_peer:
            continue

        remote_tok = m_peer.group("remote_tok")
        selected = remote_tok.startswith("*")
        remote = remote_tok[1:] if selected else remote_tok

        # Reach is usually printed as octal-like digits (e.g., 377). Store raw + parsed int if possible.
        reach_raw = m_peer.group("reach")
        reach_oct = None
        try:
            # If reach is composed only of digits, interpret it as octal digits (ntpq convention).
            # This produces a numeric reachability indicator suitable for comparisons.
            if re.fullmatch(r"\d+", reach_raw):
                reach_oct = int(reach_raw, 8)
        except Exception:
            reach_oct = None

        when_raw = m_peer.group("when")
        when_s = None
        try:
            when_s = int(when_raw) if when_raw != "-" else None
        except Exception:
            when_s = None

        peer_row = {
            "hhmmss": f"{current_ts_s//3600:02d}:{(current_ts_s%3600)//60:02d}:{current_ts_s%60:02d}",
            "selected": selected,
            "remote": remote,
            "refid": m_peer.group("refid"),
            "stratum": int(m_peer.group("st")),
            "assoc_type": m_peer.group("t"),
            "when_s": when_s,
            "poll_s": int(m_peer.group("poll")),
            "reach_raw": reach_raw,
            "reach_oct": reach_oct,
            "delay_ms": float(m_peer.group("delay")),
            "offset_ms": float(m_peer.group("offset")),
            "jitter_ms": float(m_peer.group("jitter")),
            "raw": line_stripped,
        }
        snapshot_peers.append(peer_row)

    # Flush last snapshot.
    flush_snapshot()

    samples = pd.DataFrame(sample_rows)
    events = pd.DataFrame(event_rows)

    if not samples.empty:
        samples = _normalize_time(samples, "t_s")
    if not events.empty:
        events = _normalize_time(events, "t_s")

    return ParsedRun(role=role, scenario=scenario, source_file=path, samples=samples, events=events)


# ----------------------------
# Summaries (minimal)
# ----------------------------

def summarize_run(run: ParsedRun) -> pd.DataFrame:
    s = run.samples

    def safe(fn, series: Optional[pd.Series]):
        if series is None or series.empty:
            return None
        return fn(series)

    # Lock time = first selected sample.
    t_first_selected = None
    if not s.empty and "selected" in s.columns and s["selected"].any():
        t_first_selected = float(s.loc[s["selected"], "t_rel_s"].min())

    post = s[s["selected"]].copy() if not s.empty and "selected" in s.columns else pd.DataFrame()

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "source_file": str(run.source_file),
        "t_first_selected_s": t_first_selected,

        "offset_mean_ms_post": safe(lambda x: float(x.mean()), post.get("offset_ms")),
        "offset_std_ms_post": safe(lambda x: float(x.std(ddof=1)), post.get("offset_ms")),
        "offset_p95_ms_post": safe(lambda x: float(x.quantile(0.95)), post.get("offset_ms")),
        "offset_maxabs_ms_post": safe(lambda x: float(x.abs().max()), post.get("offset_ms")),

        "jitter_mean_ms_post": safe(lambda x: float(x.mean()), post.get("jitter_ms")),
        "jitter_p95_ms_post": safe(lambda x: float(x.quantile(0.95)), post.get("jitter_ms")),

        "delay_mean_ms_post": safe(lambda x: float(x.mean()), post.get("delay_ms")),
        "delay_p95_ms_post": safe(lambda x: float(x.quantile(0.95)), post.get("delay_ms")),

        "reach_final_raw": None if s.empty else str(s.iloc[-1].get("reach_raw")),
        "reach_final_oct": None if s.empty else s.iloc[-1].get("reach_oct"),
    }
    return pd.DataFrame([out])


# ----------------------------
# Plotting
# ----------------------------

def _plot_series(df: pd.DataFrame, x: str, y: str, title: str, ylabel: str, outpath: Path) -> None:
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


def plot_run(run: ParsedRun, outdir: Path) -> None:
    s = run.samples
    if s.empty:
        return

    prefix = f"ntpsec_{run.role}_{run.scenario}"

    _plot_series(
        s, "t_rel_s", "offset_ms",
        f"NTPsec {run.role} offset (ms) - {run.scenario}",
        "offset (ms)",
        outdir / f"{prefix}_offset_ms.png",
    )

    _plot_series(
        s, "t_rel_s", "jitter_ms",
        f"NTPsec {run.role} jitter (ms) - {run.scenario}",
        "jitter (ms)",
        outdir / f"{prefix}_jitter_ms.png",
    )

    _plot_series(
        s, "t_rel_s", "delay_ms",
        f"NTPsec {run.role} delay (ms) - {run.scenario}",
        "delay (ms)",
        outdir / f"{prefix}_delay_ms.png",
    )


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Parse NTPsec ntpq-style logs and generate CSV/plots.")
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
    ensure_outdir(outdir)

    parser_dir = outdir / "parser_ntpsec"
    plots_dir = outdir / "plots_ntpsec"
    parser_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    runs: List[ParsedRun] = []
    summaries: List[pd.DataFrame] = []

    for p in args.inputs:
        role = args.role
        scenario = args.scenario

        if role is None or scenario is None:
            r_i, s_i = infer_role_and_scenario_from_filename(p)
            role = role or r_i
            scenario = scenario or s_i

        if role is None or scenario is None:
            raise ValueError(
                f"Cannot infer role/scenario from filename: {p.name}. "
                f"Use --role and/or --scenario."
            )

        run = parse_ntpq_snapshots(p, role=role, scenario=scenario)
        runs.append(run)

        # Export parsed tables.
        if not run.samples.empty:
            run.samples.to_csv(parser_dir / f"{role}_{scenario}_samples.csv", index=False)
        if not run.events.empty:
            run.events.to_csv(parser_dir / f"{role}_{scenario}_events.csv", index=False)

        # Plots.
        plot_run(run, plots_dir)

        # Summary per run.
        summaries.append(summarize_run(run))

    if summaries:
        pd.concat(summaries, ignore_index=True).to_csv(parser_dir / "summary.csv", index=False)


if __name__ == "__main__":
    main()
