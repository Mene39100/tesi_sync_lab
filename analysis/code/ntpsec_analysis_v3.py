#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd


# ----------------------------
# Regex patterns
# ----------------------------

RE_SNAPSHOT_TS = re.compile(r"^---\s+(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\s+---\s*$")

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

HEADER_PREFIXES = ("remote", "refid", "====", "==============================================================================", "=====")


# ----------------------------
# Data containers
# ----------------------------

@dataclass
class ParsedRun:
    role: str
    scenario: str
    run_id: str
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
    out = df.copy()
    t0 = float(out[t_col].min())
    out["t_rel_s"] = out[t_col] - t0
    out["t_bin_s"] = out["t_rel_s"].round().astype(int)

    # allineamento per indice del campione
    out = out.reset_index(drop=True)
    out["sample_idx"] = out.index.astype(int)

    return out


def _t_critical_95(n: int) -> float:
    table = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
        26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    }
    if n <= 1:
        return float("nan")
    df = n - 1
    if df in table:
        return table[df]
    return 1.96


def _compute_global_ylim(
    aggregated_tables: List[pd.DataFrame],
    lower_col: str,
    upper_col: str,
    symmetric: bool,
    pad: float = 0.05,
) -> Optional[Tuple[float, float]]:
    vals = []
    for df in aggregated_tables:
        if df.empty or lower_col not in df.columns or upper_col not in df.columns:
            continue
        vals.extend(pd.to_numeric(df[lower_col], errors="coerce").dropna().tolist())
        vals.extend(pd.to_numeric(df[upper_col], errors="coerce").dropna().tolist())

    if not vals:
        return None

    if symmetric:
        m = max(abs(v) for v in vals)
        m *= (1.0 + pad)
        return (-m, m)

    lo = min(vals)
    hi = max(vals)
    if lo > 0:
        lo = 0.0
    span = hi - lo
    if span == 0:
        span = max(abs(hi), 1.0)
    return (lo, hi + pad * span)


# ----------------------------
# Parsing
# ----------------------------

def parse_ntpq_snapshots(path: Path, role: str, scenario: str, run_id: str) -> ParsedRun:
    lines = _read_lines(path)

    sample_rows: List[Dict] = []
    event_rows: List[Dict] = []

    current_ts_s: Optional[int] = None
    current_hhmmss: Optional[str] = None
    snapshot_peers: List[Dict] = []

    day_offset = 0
    last_clock_s: Optional[int] = None

    def flush_snapshot() -> None:
        nonlocal snapshot_peers, current_ts_s, sample_rows, event_rows, current_hhmmss
        if current_ts_s is None or not snapshot_peers:
            snapshot_peers = []
            return

        chosen = None
        for pr in snapshot_peers:
            if pr["selected"]:
                chosen = pr
                break
        if chosen is None:
            chosen = snapshot_peers[0]

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
            "sel_char": chosen["sel_char"],
            "selected": chosen["selected"],
            "delay_ms": chosen["delay_ms"],
            "offset_ms": chosen["offset_ms"],
            "jitter_ms": chosen["jitter_ms"],
            "raw": chosen["raw"],
        })

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
            flush_snapshot()

            h = int(m_ts.group("h"))
            m = int(m_ts.group("m"))
            s = int(m_ts.group("s"))

            clock_s = _hhmmss_to_seconds(h, m, s)

            if last_clock_s is not None and clock_s < last_clock_s:
                day_offset += 86400

            current_ts_s = clock_s + day_offset
            current_hhmmss = f"{h:02d}:{m:02d}:{s:02d}"
            last_clock_s = clock_s
            continue

        if not line_stripped:
            continue

        if any(line_stripped.startswith(p) for p in HEADER_PREFIXES) or line_stripped.startswith("="):
            continue

        if current_ts_s is None:
            continue

        m_peer = RE_PEER_LINE.match(line_stripped)
        if not m_peer:
            continue

        remote_tok = m_peer.group("remote_tok")

        sel_char = ""
        remote = remote_tok
        if remote_tok and not remote_tok[0].isalnum() and remote_tok[0] not in (".", "_"):
            sel_char = remote_tok[0]
            remote = remote_tok[1:]
        elif remote_tok.startswith("*"):
            sel_char = "*"
            remote = remote_tok[1:]

        selected = (sel_char == "*")

        reach_raw = m_peer.group("reach")
        reach_oct = None
        try:
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
            "hhmmss": current_hhmmss,
            "sel_char": sel_char,
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

    flush_snapshot()

    samples = pd.DataFrame(sample_rows)
    events = pd.DataFrame(event_rows)

    if not samples.empty:
        samples = _normalize_time(samples, "t_s")
        samples["scenario"] = scenario
        samples["run_id"] = run_id
        samples["role"] = role

    if not events.empty:
        events = _normalize_time(events, "t_s")
        events["scenario"] = scenario
        events["run_id"] = run_id
        events["role"] = role

    return ParsedRun(
        role=role,
        scenario=scenario,
        run_id=run_id,
        source_file=path,
        samples=samples,
        events=events,
    )


# ----------------------------
# Summaries
# ----------------------------

def summarize_run(run: ParsedRun) -> pd.DataFrame:
    s = run.samples

    def safe(fn, series: Optional[pd.Series]):
        if series is None or series.empty:
            return None
        return fn(series)

    t_first_selected = None
    if not s.empty and "selected" in s.columns and bool(s["selected"].any()):
        t_first_selected = float(s.loc[s["selected"], "t_rel_s"].min())

    post = s[s["selected"]].copy() if not s.empty and "selected" in s.columns else pd.DataFrame()

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "run_id": run.run_id,
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
# Aggregation
# ----------------------------

def aggregate_metric(runs: List[ParsedRun], role: str, scenario: str, metric: str) -> pd.DataFrame:
    pieces = []
    for run in runs:
        if run.role != role or run.scenario != scenario or run.samples.empty:
            continue
        if metric not in run.samples.columns:
            continue

        df = run.samples[["sample_idx", metric, "run_id"]].copy()
        df = df.dropna(subset=[metric])
        pieces.append(df)

    if not pieces:
        return pd.DataFrame()

    long_df = pd.concat(pieces, ignore_index=True)

    def agg_fn(g: pd.DataFrame) -> pd.Series:
        vals = pd.to_numeric(g[metric], errors="coerce").dropna()
        n = len(vals)
        if n == 0:
            return pd.Series(dtype=float)

        mean = vals.mean()
        std = vals.std(ddof=1) if n > 1 else 0.0
        se = std / math.sqrt(n) if n > 1 else 0.0
        tcrit = _t_critical_95(n)
        ci_half = tcrit * se if n > 1 else 0.0

        return pd.Series({
            "n_runs": n,
            "mean": mean,
            "std": std,
            "ci95_low": mean - ci_half,
            "ci95_high": mean + ci_half,
            "q10": vals.quantile(0.10),
            "q25": vals.quantile(0.25),
            "q50": vals.quantile(0.50),
            "q75": vals.quantile(0.75),
            "q90": vals.quantile(0.90),
            "min": vals.min(),
            "max": vals.max(),
        })

    out = long_df.groupby("sample_idx", as_index=False).apply(agg_fn)
    if isinstance(out.index, pd.MultiIndex):
        out = out.reset_index()
    if "level_0" in out.columns:
        out = out.drop(columns=["level_0"])
    return out


# ----------------------------
# Plotting
# ----------------------------

def plot_mean_ci(
    df: pd.DataFrame,
    scenario: str,
    role: str,
    metric: str,
    ylabel: str,
    outpath: Path,
    ylim: Optional[Tuple[float, float]] = None,
) -> None:
    if df.empty:
        return

    plt.figure()
    plt.plot(df["sample_idx"], df["mean"], label="mean")
    plt.fill_between(df["sample_idx"], df["ci95_low"], df["ci95_high"], alpha=0.25, label="95% CI")
    plt.xlabel("sample index")
    plt.ylabel(ylabel)
    plt.title(f"{role} - {scenario} - {metric} - mean + 95% CI")
    if ylim is not None:
        plt.ylim(*ylim)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def plot_mean_iqr_p10p90(
    df: pd.DataFrame,
    scenario: str,
    role: str,
    metric: str,
    ylabel: str,
    outpath: Path,
    ylim: Optional[Tuple[float, float]] = None,
) -> None:
    if df.empty:
        return

    plt.figure()
    plt.plot(df["sample_idx"], df["mean"], label="mean")
    plt.fill_between(df["sample_idx"], df["q10"], df["q90"], alpha=0.15, label="p10-p90")
    plt.fill_between(df["sample_idx"], df["q25"], df["q75"], alpha=0.30, label="IQR")
    plt.xlabel("sample index")
    plt.ylabel(ylabel)
    plt.title(f"{role} - {scenario} - {metric} - mean + IQR + p10/p90")
    if ylim is not None:
        plt.ylim(*ylim)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Parse and aggregate NTPsec multi-run logs.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of NTPsec multi-run logs, e.g. .../analysis/raw_logs/T3_multiplerun/ntpsec",
    )
    args = ap.parse_args()

    root = args.root
    scenarios = ["low", "medium", "high"]

    runs: List[ParsedRun] = []
    summaries: List[pd.DataFrame] = []

    for scenario in scenarios:
        scenario_dir = root / scenario
        if not scenario_dir.exists():
            continue

        for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
            run_id = run_dir.name

            client_log = run_dir / "ntp_client_live.log"
            boundary_log = run_dir / "ntp_boundary_live.log"

            if client_log.exists():
                run = parse_ntpq_snapshots(client_log, role="client", scenario=scenario, run_id=run_id)
                runs.append(run)
                if not run.samples.empty:
                    run.samples.to_csv(run_dir / "parsed_client_samples.csv", index=False)
                if not run.events.empty:
                    run.events.to_csv(run_dir / "parsed_client_events.csv", index=False)
                summaries.append(summarize_run(run))

            if boundary_log.exists():
                run = parse_ntpq_snapshots(boundary_log, role="boundary", scenario=scenario, run_id=run_id)
                runs.append(run)
                if not run.samples.empty:
                    run.samples.to_csv(run_dir / "parsed_boundary_samples.csv", index=False)
                if not run.events.empty:
                    run.events.to_csv(run_dir / "parsed_boundary_events.csv", index=False)
                summaries.append(summarize_run(run))

    agg_root = root / "_aggregated"
    client_dir = agg_root / "client"
    boundary_dir = agg_root / "boundary"
    client_dir.mkdir(parents=True, exist_ok=True)
    boundary_dir.mkdir(parents=True, exist_ok=True)

    if summaries:
        pd.concat(summaries, ignore_index=True).to_csv(
            agg_root / "summary_all_runs.csv", index=False
        )

    metric_specs = {
        "offset_ms": ("offset (ms)", True),
        "jitter_ms": ("jitter (ms)", False),
        "delay_ms": ("delay (ms)", False),
    }

    scenario_metric_tables: Dict[Tuple[str, str, str], pd.DataFrame] = {}

    client_ci_tables = {m: [] for m in metric_specs}
    client_iqr_tables = {m: [] for m in metric_specs}
    boundary_ci_tables = {m: [] for m in metric_specs}
    boundary_iqr_tables = {m: [] for m in metric_specs}

    for scenario in scenarios:
        for metric in metric_specs:
            df = aggregate_metric(runs, role="client", scenario=scenario, metric=metric)
            scenario_metric_tables[("client", scenario, metric)] = df
            if not df.empty:
                client_ci_tables[metric].append(df)
                client_iqr_tables[metric].append(df)

            df = aggregate_metric(runs, role="boundary", scenario=scenario, metric=metric)
            scenario_metric_tables[("boundary", scenario, metric)] = df
            if not df.empty:
                boundary_ci_tables[metric].append(df)
                boundary_iqr_tables[metric].append(df)

    client_ylims_ci = {
        metric: _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in metric_specs.items()
        for tbls in [client_ci_tables[metric]]
    }
    client_ylims_iqr = {
        metric: _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in metric_specs.items()
        for tbls in [client_iqr_tables[metric]]
    }

    boundary_ylims_ci = {
        metric: _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in metric_specs.items()
        for tbls in [boundary_ci_tables[metric]]
    }
    boundary_ylims_iqr = {
        metric: _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in metric_specs.items()
        for tbls in [boundary_iqr_tables[metric]]
    }

    for scenario in scenarios:
        scenario_client_dir = client_dir / scenario
        scenario_boundary_dir = boundary_dir / scenario
        scenario_client_dir.mkdir(parents=True, exist_ok=True)
        scenario_boundary_dir.mkdir(parents=True, exist_ok=True)

        for metric, (ylabel, _) in metric_specs.items():
            df = scenario_metric_tables.get(("client", scenario, metric), pd.DataFrame())
            if not df.empty:
                df.to_csv(scenario_client_dir / f"{metric}_aggregated.csv", index=False)

                plot_mean_ci(
                    df=df,
                    scenario=scenario,
                    role="client",
                    metric=metric,
                    ylabel=ylabel,
                    outpath=scenario_client_dir / f"{metric}_mean_ci95.png",
                    ylim=client_ylims_ci[metric],
                )

                plot_mean_iqr_p10p90(
                    df=df,
                    scenario=scenario,
                    role="client",
                    metric=metric,
                    ylabel=ylabel,
                    outpath=scenario_client_dir / f"{metric}_mean_iqr_p10_p90.png",
                    ylim=client_ylims_iqr[metric],
                )

            df = scenario_metric_tables.get(("boundary", scenario, metric), pd.DataFrame())
            if not df.empty:
                df.to_csv(scenario_boundary_dir / f"{metric}_aggregated.csv", index=False)

                plot_mean_ci(
                    df=df,
                    scenario=scenario,
                    role="boundary",
                    metric=metric,
                    ylabel=ylabel,
                    outpath=scenario_boundary_dir / f"{metric}_mean_ci95.png",
                    ylim=boundary_ylims_ci[metric],
                )

                plot_mean_iqr_p10p90(
                    df=df,
                    scenario=scenario,
                    role="boundary",
                    metric=metric,
                    ylabel=ylabel,
                    outpath=scenario_boundary_dir / f"{metric}_mean_iqr_p10_p90.png",
                    ylim=boundary_ylims_iqr[metric],
                )

    print(f"[OK] Parsing per-run completato e aggregazione salvata in: {agg_root}")


if __name__ == "__main__":
    main()