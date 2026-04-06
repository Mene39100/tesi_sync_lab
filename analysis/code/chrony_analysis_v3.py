#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd


RE_SAMPLE_HDR = re.compile(r"^=+\s*SAMPLE\s+\d+/\d+\s+@\s+(?P<ts>[^ ]+)\s*=+\s*$")

RE_TRACKING_SYSTEM_TIME = re.compile(
    r"^System time\s*:\s*(?P<val>[+-]?\d+(?:\.\d+)?)\s+seconds\s+(?P<dir>slow|fast)\s+of\s+NTP\s+time\s*$"
)
RE_TRACKING_LAST_OFFSET = re.compile(r"^Last offset\s*:\s*(?P<val>[+-]?\d+(?:\.\d+)?)\s+seconds\s*$")

RE_SOURCESTATS_ROW = re.compile(
    r"^(?P<name>\S+)\s+"
    r"(?P<np>\d+)\s+(?P<nr>\d+)\s+(?P<span>\d+)\s+"
    r"(?P<freq>[+-]?\d+(?:\.\d+)?)\s+(?P<skew>[+-]?\d+(?:\.\d+)?)\s+"
    r"(?P<offset>[+-]?\d+(?:\.\d+)?(?:ns|us|ms|s)?)\s+"
    r"(?P<stddev>[+-]?\d+(?:\.\d+)?(?:ns|us|ms|s)?)\s*$"
)

RE_TABLE_SEPARATOR = re.compile(r"^=+\s*$")


@dataclass
class TrackingSeries:
    t: List[datetime]
    system_time_s: List[float]
    last_offset_s: List[float]


@dataclass
class SourceStatsSeries:
    t: List[datetime]
    source: List[str]
    offset_s: List[float]
    stddev_s: List[float]


@dataclass
class ParsedRun:
    scenario: str
    run_id: str
    run_dir: Path
    tracking_df: pd.DataFrame
    sourcestats_df: pd.DataFrame


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

    return SourceStatsSeries(times, sources, offsets, stddevs)


def build_tracking_df(ts: TrackingSeries, scenario: str, run_id: str) -> pd.DataFrame:
    if not ts.t:
        return pd.DataFrame()

    rel = to_rel_seconds(ts.t)
    rows = []
    for i in range(len(ts.t)):
        rows.append({
            "sample_idx": i,
            "iso_ts": ts.t[i].isoformat(),
            "t_s": ts.t[i].timestamp(),
            "t_rel_s": rel[i],
            "t_bin_s": round(rel[i]),
            "system_time_s": ts.system_time_s[i],
            "system_time_us": ts.system_time_s[i] * 1e6 if ts.system_time_s[i] == ts.system_time_s[i] else float("nan"),
            "last_offset_s": ts.last_offset_s[i],
            "last_offset_us": ts.last_offset_s[i] * 1e6 if ts.last_offset_s[i] == ts.last_offset_s[i] else float("nan"),
            "scenario": scenario,
            "run_id": run_id,
        })
    return pd.DataFrame(rows)


def build_sourcestats_df(ss: SourceStatsSeries, scenario: str, run_id: str) -> pd.DataFrame:
    if not ss.t:
        return pd.DataFrame()

    rel = to_rel_seconds(ss.t)
    rows = []
    for i in range(len(ss.t)):
        rows.append({
            "sample_idx": i,
            "iso_ts": ss.t[i].isoformat(),
            "t_s": ss.t[i].timestamp(),
            "t_rel_s": rel[i],
            "t_bin_s": round(rel[i]),
            "source": ss.source[i],
            "offset_s": ss.offset_s[i],
            "offset_us": ss.offset_s[i] * 1e6,
            "stddev_s": ss.stddev_s[i],
            "stddev_us": ss.stddev_s[i] * 1e6,
            "scenario": scenario,
            "run_id": run_id,
        })
    return pd.DataFrame(rows)


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


def aggregate_metric(df_all: pd.DataFrame, scenario: str, metric: str, source: Optional[str] = None) -> pd.DataFrame:
    if df_all.empty or metric not in df_all.columns:
        return pd.DataFrame()

    df = df_all[df_all["scenario"] == scenario].copy()

    if source is not None and "source" in df.columns:
        df = df[df["source"] == source].copy()

    if df.empty:
        return pd.DataFrame()

    df = df[["sample_idx", metric, "run_id"]].copy()
    df = df.dropna(subset=[metric])

    if df.empty:
        return pd.DataFrame()

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

    out = df.groupby("sample_idx", as_index=False).apply(agg_fn)
    if isinstance(out.index, pd.MultiIndex):
        out = out.reset_index()
    if "level_0" in out.columns:
        out = out.drop(columns=["level_0"])
    return out


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


def plot_mean_ci(
    df: pd.DataFrame,
    title: str,
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
    plt.title(title)
    if ylim is not None:
        plt.ylim(*ylim)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def plot_mean_iqr_p10p90(
    df: pd.DataFrame,
    title: str,
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
    plt.title(title)
    if ylim is not None:
        plt.ylim(*ylim)
    plt.legend()
    plt.tight_layout()
    plt.savefig(outpath, dpi=200)
    plt.close()


def summarize_tracking_run(df: pd.DataFrame, scenario: str, run_id: str, run_dir: Path) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame([{
            "scenario": scenario,
            "run_id": run_id,
            "run_dir": str(run_dir),
        }])

    out = {
        "scenario": scenario,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "system_time_mean_us": float(df["system_time_us"].mean()) if "system_time_us" in df else None,
        "system_time_std_us": float(df["system_time_us"].std(ddof=1)) if "system_time_us" in df and len(df) > 1 else None,
        "last_offset_mean_us": float(df["last_offset_us"].mean()) if "last_offset_us" in df else None,
        "last_offset_std_us": float(df["last_offset_us"].std(ddof=1)) if "last_offset_us" in df and len(df) > 1 else None,
    }
    return pd.DataFrame([out])


def summarize_sourcestats_run(df: pd.DataFrame, scenario: str, run_id: str, run_dir: Path) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame([{
            "scenario": scenario,
            "run_id": run_id,
            "run_dir": str(run_dir),
        }])

    out = {
        "scenario": scenario,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "offset_mean_us": float(df["offset_us"].mean()) if "offset_us" in df else None,
        "offset_std_us": float(df["offset_us"].std(ddof=1)) if "offset_us" in df and len(df) > 1 else None,
        "stddev_mean_us": float(df["stddev_us"].mean()) if "stddev_us" in df else None,
        "stddev_std_us": float(df["stddev_us"].std(ddof=1)) if "stddev_us" in df and len(df) > 1 else None,
    }
    return pd.DataFrame([out])


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse and aggregate Chrony multi-run logs.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of Chrony multi-run logs, e.g. .../analysis/raw_logs/T3_multiplerun/chrony_servergm",
    )
    args = ap.parse_args()

    root = args.root
    scenarios = ["low", "medium", "high"]

    parsed_runs: List[ParsedRun] = []
    tracking_summaries: List[pd.DataFrame] = []
    sourcestats_summaries: List[pd.DataFrame] = []

    for scenario in scenarios:
        scenario_dir = root / scenario
        if not scenario_dir.exists():
            continue

        for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
            run_id = run_dir.name

            tracking_path = run_dir / "chrony_tracking_series.txt"
            sourcestats_path = run_dir / "chrony_sourcestats_series.txt"

            if not tracking_path.exists() or not sourcestats_path.exists():
                continue

            tr = parse_tracking_series(tracking_path)
            ss = parse_sourcestats_series(sourcestats_path)

            tracking_df = build_tracking_df(tr, scenario, run_id)
            sourcestats_df = build_sourcestats_df(ss, scenario, run_id)

            if not tracking_df.empty:
                tracking_df.to_csv(run_dir / "parsed_tracking.csv", index=False)
            if not sourcestats_df.empty:
                sourcestats_df.to_csv(run_dir / "parsed_sourcestats.csv", index=False)

            parsed_runs.append(
                ParsedRun(
                    scenario=scenario,
                    run_id=run_id,
                    run_dir=run_dir,
                    tracking_df=tracking_df,
                    sourcestats_df=sourcestats_df,
                )
            )

            tracking_summaries.append(summarize_tracking_run(tracking_df, scenario, run_id, run_dir))
            sourcestats_summaries.append(summarize_sourcestats_run(sourcestats_df, scenario, run_id, run_dir))

    agg_root = root / "_aggregated"
    tracking_dir = agg_root / "tracking"
    sourcestats_dir = agg_root / "sourcestats"
    tracking_dir.mkdir(parents=True, exist_ok=True)
    sourcestats_dir.mkdir(parents=True, exist_ok=True)

    if tracking_summaries:
        pd.concat(tracking_summaries, ignore_index=True).to_csv(
            agg_root / "tracking_summary_all_runs.csv", index=False
        )
    if sourcestats_summaries:
        pd.concat(sourcestats_summaries, ignore_index=True).to_csv(
            agg_root / "sourcestats_summary_all_runs.csv", index=False
        )

    tracking_all = pd.concat(
        [r.tracking_df for r in parsed_runs if not r.tracking_df.empty],
        ignore_index=True
    ) if parsed_runs else pd.DataFrame()

    sourcestats_all = pd.concat(
        [r.sourcestats_df for r in parsed_runs if not r.sourcestats_df.empty],
        ignore_index=True
    ) if parsed_runs else pd.DataFrame()

    tracking_metrics = {
        "system_time_us": ("system time offset (us)", True),
        "last_offset_us": ("last offset (us)", True),
    }

    # per sourcestats conviene aggregare per metrica e per source
    sourcestats_metrics = {
        "offset_us": ("source offset (us)", True),
        "stddev_us": ("std dev (us)", False),
    }

    tracking_tables: Dict[Tuple[str, str], pd.DataFrame] = {}
    sourcestats_tables: Dict[Tuple[str, str, str], pd.DataFrame] = {}

    tracking_ci_tables = {m: [] for m in tracking_metrics}
    tracking_iqr_tables = {m: [] for m in tracking_metrics}

    sourcestats_ci_tables: Dict[Tuple[str, str], List[pd.DataFrame]] = {}
    sourcestats_iqr_tables: Dict[Tuple[str, str], List[pd.DataFrame]] = {}

    available_sources = []
    if not sourcestats_all.empty and "source" in sourcestats_all.columns:
        available_sources = sorted(sourcestats_all["source"].dropna().unique().tolist())

    for metric in sourcestats_metrics:
        for source in available_sources:
            sourcestats_ci_tables[(metric, source)] = []
            sourcestats_iqr_tables[(metric, source)] = []

    for scenario in scenarios:
        for metric in tracking_metrics:
            df = aggregate_metric(tracking_all, scenario=scenario, metric=metric)
            tracking_tables[(scenario, metric)] = df
            if not df.empty:
                tracking_ci_tables[metric].append(df)
                tracking_iqr_tables[metric].append(df)

        for metric in sourcestats_metrics:
            for source in available_sources:
                df = aggregate_metric(sourcestats_all, scenario=scenario, metric=metric, source=source)
                sourcestats_tables[(scenario, metric, source)] = df
                if not df.empty:
                    sourcestats_ci_tables[(metric, source)].append(df)
                    sourcestats_iqr_tables[(metric, source)].append(df)

    tracking_ylims_ci = {
        metric: _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in tracking_metrics.items()
        for tbls in [tracking_ci_tables[metric]]
    }
    tracking_ylims_iqr = {
        metric: _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in tracking_metrics.items()
        for tbls in [tracking_iqr_tables[metric]]
    }

    sourcestats_ylims_ci = {
        (metric, source): _compute_global_ylim(tbls, "ci95_low", "ci95_high", symmetric=sym)
        for metric, (_, sym) in sourcestats_metrics.items()
        for source in available_sources
        for tbls in [sourcestats_ci_tables[(metric, source)]]
    }
    sourcestats_ylims_iqr = {
        (metric, source): _compute_global_ylim(tbls, "q10", "q90", symmetric=sym)
        for metric, (_, sym) in sourcestats_metrics.items()
        for source in available_sources
        for tbls in [sourcestats_iqr_tables[(metric, source)]]
    }

    for scenario in scenarios:
        scenario_tracking_dir = tracking_dir / scenario
        scenario_sourcestats_dir = sourcestats_dir / scenario
        scenario_tracking_dir.mkdir(parents=True, exist_ok=True)
        scenario_sourcestats_dir.mkdir(parents=True, exist_ok=True)

        for metric, (ylabel, _) in tracking_metrics.items():
            df = tracking_tables.get((scenario, metric), pd.DataFrame())
            if df.empty:
                continue

            df.to_csv(scenario_tracking_dir / f"{metric}_aggregated.csv", index=False)

            plot_mean_ci(
                df=df,
                title=f"tracking - {scenario} - {metric} - mean + 95% CI",
                ylabel=ylabel,
                outpath=scenario_tracking_dir / f"{metric}_mean_ci95.png",
                ylim=tracking_ylims_ci[metric],
            )

            plot_mean_iqr_p10p90(
                df=df,
                title=f"tracking - {scenario} - {metric} - mean + IQR + p10/p90",
                ylabel=ylabel,
                outpath=scenario_tracking_dir / f"{metric}_mean_iqr_p10_p90.png",
                ylim=tracking_ylims_iqr[metric],
            )

        for metric, (ylabel, _) in sourcestats_metrics.items():
            for source in available_sources:
                df = sourcestats_tables.get((scenario, metric, source), pd.DataFrame())
                if df.empty:
                    continue

                safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(source))
                source_dir = scenario_sourcestats_dir / safe_source
                source_dir.mkdir(parents=True, exist_ok=True)

                df.to_csv(source_dir / f"{metric}_aggregated.csv", index=False)

                plot_mean_ci(
                    df=df,
                    title=f"sourcestats - {scenario} - {safe_source} - {metric} - mean + 95% CI",
                    ylabel=ylabel,
                    outpath=source_dir / f"{metric}_mean_ci95.png",
                    ylim=sourcestats_ylims_ci[(metric, source)],
                )

                plot_mean_iqr_p10p90(
                    df=df,
                    title=f"sourcestats - {scenario} - {safe_source} - {metric} - mean + IQR + p10/p90",
                    ylabel=ylabel,
                    outpath=source_dir / f"{metric}_mean_iqr_p10_p90.png",
                    ylim=sourcestats_ylims_iqr[(metric, source)],
                )

    print(f"[OK] Parsing per-run completato e aggregazione salvata in: {agg_root}")


if __name__ == "__main__":
    main()