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

RE_TS = r"ptp4l\[(?P<t>\d+\.\d+)\]:\s+"

RE_BOUNDARY_SAMPLE = re.compile(
    RE_TS
    + r"master offset\s+(?P<offset>-?\d+)\s+s(?P<sstate>\d)\s+freq\s+(?P<freq>[+-]?\d+)\s+path delay\s+(?P<delay>\d+)"
)

RE_CLIENT_SAMPLE = re.compile(
    RE_TS
    + r"rms\s+(?P<rms>\d+)\s+max\s+(?P<max>\d+)\s+freq\s+(?P<freq>[+-]?\d+)\s+\+/-\s+(?P<freq_pm>\d+)"
    + r"(?:\s+delay\s+(?P<delay>\d+)(?:\s+\+/-\s+(?P<delay_pm>\d+))?)?"
)

RE_STATE = re.compile(
    RE_TS
    + r"port\s+(?P<port>\d+):\s+(?P<from>[A-Z_]+)\s+to\s+(?P<to>[A-Z_]+)\s+on\s+(?P<reason>[A-Z0-9_]+)"
)

RE_FAULT = re.compile(RE_TS + r".*\bFAULTY\b.*")
RE_FAULT_DETECTED = re.compile(RE_TS + r".*FAULT_DETECTED.*")
RE_BEST_MASTER = re.compile(
    RE_TS + r"selected best master clock\s+(?P<gm>[0-9a-f]+\.[0-9a-f]+\.[0-9a-f]+)"
)
RE_FOREIGN_NOT_PTP_TIMESCALE = re.compile(RE_TS + r"foreign master not using PTP timescale")
RE_NEW_FOREIGN = re.compile(
    RE_TS
    + r"port\s+(?P<port>\d+):\s+new foreign master\s+(?P<fm>[0-9a-f]+\.[0-9a-f]+\.[0-9a-f]+-\d+)"
)


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


def _normalize_time(df: pd.DataFrame, t_col: str = "t") -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    t0 = df[t_col].min()
    df["t_rel_s"] = df[t_col] - t0
    df["t_bin_s"] = df["t_rel_s"].round().astype(int)
    return df


def _t_critical_95(n: int) -> float:
    # due-sided 95%, approx Student-t critical values
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

def parse_ptp4l_log(path: Path, role: str, scenario: str, run_id: str) -> ParsedRun:
    lines = _read_lines(path)

    sample_rows: List[Dict] = []
    event_rows: List[Dict] = []

    for line in lines:
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

        if role == "boundary":
            m = RE_BOUNDARY_SAMPLE.search(line)
            if m:
                sample_rows.append({
                    "t": float(m.group("t")),
                    "offset_ns": int(m.group("offset")),
                    "servo_state": int(m.group("sstate")),
                    "freq_raw": int(m.group("freq")),
                    "path_delay_ns": int(m.group("delay")),
                    "raw": line.strip(),
                })
                continue

        elif role == "client":
            m = RE_CLIENT_SAMPLE.search(line)
            if m:
                sample_rows.append({
                    "t": float(m.group("t")),
                    "rms_ns": int(m.group("rms")),
                    "max_ns": int(m.group("max")),
                    "freq_raw": int(m.group("freq")),
                    "freq_pm_raw": int(m.group("freq_pm")) if m.group("freq_pm") else None,
                    "path_delay_ns": int(m.group("delay")) if m.group("delay") else None,
                    "path_delay_pm_ns": int(m.group("delay_pm")) if m.group("delay_pm") else None,
                    "raw": line.strip(),
                })
                continue
        else:
            raise ValueError(f"Unknown role: {role}")

    samples = pd.DataFrame(sample_rows)
    events = pd.DataFrame(event_rows)

    if not samples.empty:
        samples = _normalize_time(samples, "t")
        samples["scenario"] = scenario
        samples["run_id"] = run_id
        samples["role"] = role

    if not events.empty:
        events = _normalize_time(events, "t")
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

def _find_first_time(events: pd.DataFrame, predicate) -> Optional[float]:
    if events.empty:
        return None
    sub = events[predicate(events)]
    if sub.empty:
        return None
    return float(sub["t_rel_s"].min())


def compute_convergence_time_boundary(events: pd.DataFrame) -> Optional[float]:
    return _find_first_time(events, lambda df: (df["type"] == "state") & (df["to"] == "SLAVE"))


def compute_convergence_time_client(events: pd.DataFrame) -> Optional[float]:
    return _find_first_time(events, lambda df: (df["type"] == "state") & (df["to"] == "SLAVE"))


def summarize_boundary(run: ParsedRun) -> pd.DataFrame:
    s = run.samples
    e = run.events
    conv_s = compute_convergence_time_boundary(e)
    fault_count = int((e["type"] == "fault").sum()) if not e.empty else 0
    post = s[s["servo_state"] == 2].copy() if not s.empty and "servo_state" in s.columns else pd.DataFrame()

    def safe_stat(series: pd.Series, fn):
        return fn(series) if series is not None and not series.empty else None

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "run_id": run.run_id,
        "source_file": str(run.source_file),
        "convergence_time_s": conv_s,
        "fault_count": fault_count,
        "offset_mean_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.mean())),
        "offset_std_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.std(ddof=1))),
        "offset_p50_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.50))),
        "offset_p95_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.95))),
        "offset_p99_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.quantile(0.99))),
        "offset_maxabs_ns_s2": safe_stat(post.get("offset_ns"), lambda x: float(x.abs().max())),
        "path_delay_mean_ns_s2": safe_stat(post.get("path_delay_ns"), lambda x: float(x.mean())),
        "path_delay_std_ns_s2": safe_stat(post.get("path_delay_ns"), lambda x: float(x.std(ddof=1))),
    }
    return pd.DataFrame([out])


def summarize_client(run: ParsedRun) -> pd.DataFrame:
    s = run.samples
    e = run.events
    conv_s = compute_convergence_time_client(e)
    locked = conv_s is not None
    post = s[s["t_rel_s"] >= conv_s].copy() if locked and not s.empty else pd.DataFrame()

    def safe_stat(series: pd.Series, fn):
        return fn(series) if series is not None and not series.empty else None

    reselection_count = int((e["type"] == "best_master").sum()) if not e.empty else 0

    out = {
        "role": run.role,
        "scenario": run.scenario,
        "run_id": run.run_id,
        "source_file": str(run.source_file),
        "locked": locked,
        "convergence_time_s": conv_s,
        "best_master_reselection_count": reselection_count,
        "rms_mean_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.mean())),
        "rms_std_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.std(ddof=1))),
        "rms_p95_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.quantile(0.95))),
        "rms_max_ns_post": safe_stat(post.get("rms_ns"), lambda x: float(x.max())),
        "max_mean_ns_post": safe_stat(post.get("max_ns"), lambda x: float(x.mean())),
        "max_max_ns_post": safe_stat(post.get("max_ns"), lambda x: float(x.max())),
        "path_delay_mean_ns_post": safe_stat(
            post.get("path_delay_ns").dropna() if "path_delay_ns" in post else None,
            lambda x: float(x.mean()),
        ),
        "path_delay_std_ns_post": safe_stat(
            post.get("path_delay_ns").dropna() if "path_delay_ns" in post else None,
            lambda x: float(x.std(ddof=1)),
        ),
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

        df = run.samples[["t_bin_s", metric, "run_id"]].copy()
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

    out = long_df.groupby("t_bin_s", as_index=False).apply(agg_fn)
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
    plt.plot(df["t_bin_s"], df["mean"], label="mean")
    plt.fill_between(df["t_bin_s"], df["ci95_low"], df["ci95_high"], alpha=0.25, label="95% CI")
    plt.xlabel("time (s, relative, binned)")
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
    plt.plot(df["t_bin_s"], df["mean"], label="mean")
    plt.fill_between(df["t_bin_s"], df["q10"], df["q90"], alpha=0.15, label="p10-p90")
    plt.fill_between(df["t_bin_s"], df["q25"], df["q75"], alpha=0.30, label="IQR")
    plt.xlabel("time (s, relative, binned)")
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
    ap = argparse.ArgumentParser(description="Parse and aggregate PTP multi-run logs.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of PTP multi-run logs, e.g. .../analysis/raw_logs/T3_multiplerun/ptp",
    )
    args = ap.parse_args()

    root = args.root
    scenarios = ["low", "medium", "high"]

    runs: List[ParsedRun] = []
    boundary_summaries: List[pd.DataFrame] = []
    client_summaries: List[pd.DataFrame] = []

    # ----------------------------
    # 1) Parse per run and save parsed files in the same run directory
    # ----------------------------
    for scenario in scenarios:
        scenario_dir = root / scenario
        if not scenario_dir.exists():
            continue

        for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
            run_id = run_dir.name

            boundary_log = run_dir / "ptp_boundary.log"
            client_log = run_dir / "ptp_client.log"

            if boundary_log.exists():
                run = parse_ptp4l_log(boundary_log, role="boundary", scenario=scenario, run_id=run_id)
                runs.append(run)
                if not run.samples.empty:
                    run.samples.to_csv(run_dir / "parsed_boundary_samples.csv", index=False)
                if not run.events.empty:
                    run.events.to_csv(run_dir / "parsed_boundary_events.csv", index=False)
                boundary_summaries.append(summarize_boundary(run))

            if client_log.exists():
                run = parse_ptp4l_log(client_log, role="client", scenario=scenario, run_id=run_id)
                runs.append(run)
                if not run.samples.empty:
                    run.samples.to_csv(run_dir / "parsed_client_samples.csv", index=False)
                if not run.events.empty:
                    run.events.to_csv(run_dir / "parsed_client_events.csv", index=False)
                client_summaries.append(summarize_client(run))

    # ----------------------------
    # 2) Save per-run summaries aggregated in one place
    # ----------------------------
    agg_root = root / "_aggregated"
    boundary_dir = agg_root / "boundary"
    client_dir = agg_root / "client"
    boundary_dir.mkdir(parents=True, exist_ok=True)
    client_dir.mkdir(parents=True, exist_ok=True)

    if boundary_summaries:
        pd.concat(boundary_summaries, ignore_index=True).to_csv(
            boundary_dir / "boundary_summary_all_runs.csv", index=False
        )

    if client_summaries:
        pd.concat(client_summaries, ignore_index=True).to_csv(
            client_dir / "client_summary_all_runs.csv", index=False
        )

    # ----------------------------
    # 3) Aggregate per scenario + metric across runs
    # ----------------------------
    boundary_metrics = {
        "offset_ns": ("offset (ns)", True),
        "path_delay_ns": ("path delay (ns)", False),
    }

    client_metrics = {
        "rms_ns": ("RMS offset (ns)", False),
        "path_delay_ns": ("path delay (ns)", False),
    }

    # Precompute y-lims shared across scenarios for each metric and plot type
    boundary_ci_tables = {m: [] for m in boundary_metrics}
    boundary_iqr_tables = {m: [] for m in boundary_metrics}
    client_ci_tables = {m: [] for m in client_metrics}
    client_iqr_tables = {m: [] for m in client_metrics}

    scenario_metric_tables: Dict[Tuple[str, str, str], pd.DataFrame] = {}

    for scenario in scenarios:
        for metric in boundary_metrics:
            df = aggregate_metric(runs, role="boundary", scenario=scenario, metric=metric)
            scenario_metric_tables[("boundary", scenario, metric)] = df
            if not df.empty:
                boundary_ci_tables[metric].append(df)
                boundary_iqr_tables[metric].append(df)

        for metric in client_metrics:
            df = aggregate_metric(runs, role="client", scenario=scenario, metric=metric)
            scenario_metric_tables[("client", scenario, metric)] = df
            if not df.empty:
                client_ci_tables[metric].append(df)
                client_iqr_tables[metric].append(df)

    boundary_ylims_ci = {
        metric: _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in boundary_metrics.items()
        for tbls in [boundary_ci_tables[metric]]
    }
    boundary_ylims_iqr = {
        metric: _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in boundary_metrics.items()
        for tbls in [boundary_iqr_tables[metric]]
    }

    client_ylims_ci = {
        metric: _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in client_metrics.items()
        for tbls in [client_ci_tables[metric]]
    }
    client_ylims_iqr = {
        metric: _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in client_metrics.items()
        for tbls in [client_iqr_tables[metric]]
    }

    # ----------------------------
    # 4) Save aggregated CSV and plots
    # ----------------------------
    for scenario in scenarios:
        scenario_boundary_dir = boundary_dir / scenario
        scenario_client_dir = client_dir / scenario
        scenario_boundary_dir.mkdir(parents=True, exist_ok=True)
        scenario_client_dir.mkdir(parents=True, exist_ok=True)

        for metric, (ylabel, _) in boundary_metrics.items():
            df = scenario_metric_tables.get(("boundary", scenario, metric), pd.DataFrame())
            if df.empty:
                continue

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

        for metric, (ylabel, _) in client_metrics.items():
            df = scenario_metric_tables.get(("client", scenario, metric), pd.DataFrame())
            if df.empty:
                continue

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

    print(f"[OK] Parsing per-run completato e aggregazione salvata in: {agg_root}")


if __name__ == "__main__":
    main()