#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


SCENARIOS = ["low", "medium", "high"]

TRACKING_METRICS = ["system_time_us", "last_offset_us"]
SOURCESTATS_METRICS = ["offset_us", "stddev_us"]


def safe_cv(mean_val: float, std_val: float) -> float:
    if pd.isna(mean_val) or pd.isna(std_val):
        return np.nan
    if abs(mean_val) < 1e-12:
        return np.nan
    return std_val / mean_val


def compute_stats(series: pd.Series) -> Dict[str, float]:
    s = pd.to_numeric(series, errors="coerce").dropna()

    if len(s) == 0:
        return {
            "n_valid": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "q10": np.nan,
            "q25": np.nan,
            "median": np.nan,
            "q75": np.nan,
            "q90": np.nan,
            "max": np.nan,
            "range": np.nan,
            "iqr": np.nan,
            "cv": np.nan,
        }

    mean_val = s.mean()
    std_val = s.std(ddof=1) if len(s) > 1 else 0.0
    min_val = s.min()
    q10_val = s.quantile(0.10)
    q25_val = s.quantile(0.25)
    median_val = s.quantile(0.50)
    q75_val = s.quantile(0.75)
    q90_val = s.quantile(0.90)
    max_val = s.max()
    range_val = max_val - min_val
    iqr_val = q75_val - q25_val
    cv_val = safe_cv(mean_val, std_val)

    return {
        "n_valid": int(len(s)),
        "mean": float(mean_val),
        "std": float(std_val),
        "min": float(min_val),
        "q10": float(q10_val),
        "q25": float(q25_val),
        "median": float(median_val),
        "q75": float(q75_val),
        "q90": float(q90_val),
        "max": float(max_val),
        "range": float(range_val),
        "iqr": float(iqr_val),
        "cv": float(cv_val) if not pd.isna(cv_val) else np.nan,
    }


def round_numeric_columns(df: pd.DataFrame, digits: int = 6) -> pd.DataFrame:
    out = df.copy()
    numeric_cols = out.select_dtypes(include=[np.number]).columns
    out[numeric_cols] = out[numeric_cols].round(digits)
    return out


def ensure_stats_dirs(root: Path) -> Dict[str, Path]:
    base = root / "_aggregated" / "stats"
    base.mkdir(parents=True, exist_ok=True)

    out = {}
    for scenario in SCENARIOS:
        d = base / scenario
        d.mkdir(parents=True, exist_ok=True)
        out[scenario] = d
    return out


def load_tracking_runs(root: Path, scenario: str) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    scenario_dir = root / scenario

    if not scenario_dir.exists():
        return pd.DataFrame()

    for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
        csv_path = run_dir / "parsed_tracking.csv"
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path)
        if df.empty:
            continue

        df = df.copy()
        df["run_id"] = run_dir.name
        if "sample_idx" not in df.columns:
            df = df.reset_index(drop=True)
            df["sample_idx"] = df.index.astype(int)
        rows.append(df)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True)


def load_sourcestats_runs(root: Path, scenario: str) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    scenario_dir = root / scenario

    if not scenario_dir.exists():
        return pd.DataFrame()

    for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
        csv_path = run_dir / "parsed_sourcestats.csv"
        if not csv_path.exists():
            continue

        df = pd.read_csv(csv_path)
        if df.empty:
            continue

        df = df.copy()
        df["run_id"] = run_dir.name
        if "sample_idx" not in df.columns:
            df = df.reset_index(drop=True)
            df["sample_idx"] = df.index.astype(int)
        rows.append(df)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True)


def build_tracking_global_raw_stats(df_all: pd.DataFrame, scenario: str) -> pd.DataFrame:
    rows = []

    if df_all.empty:
        return pd.DataFrame()

    n_runs = df_all["run_id"].nunique() if "run_id" in df_all.columns else np.nan

    for metric in TRACKING_METRICS:
        if metric not in df_all.columns:
            continue

        stats = compute_stats(df_all[metric])

        rows.append({
            "scenario": scenario,
            "section": "tracking",
            "metric": metric,
            "source": "all_raw_samples_across_runs",
            "n_runs_total": int(n_runs) if not pd.isna(n_runs) else np.nan,
            "n_total_rows": int(len(df_all)),
            **stats,
        })

    return pd.DataFrame(rows)


def build_sourcestats_global_raw_stats(df_all: pd.DataFrame, scenario: str) -> pd.DataFrame:
    rows = []

    if df_all.empty:
        return pd.DataFrame()

    if "source" not in df_all.columns:
        return pd.DataFrame()

    for source_name, gsrc in df_all.groupby("source"):
        n_runs = gsrc["run_id"].nunique() if "run_id" in gsrc.columns else np.nan

        for metric in SOURCESTATS_METRICS:
            if metric not in gsrc.columns:
                continue

            stats = compute_stats(gsrc[metric])

            rows.append({
                "scenario": scenario,
                "section": "sourcestats",
                "source_name": source_name,
                "metric": metric,
                "source": "all_raw_samples_across_runs",
                "n_runs_total": int(n_runs) if not pd.isna(n_runs) else np.nan,
                "n_total_rows": int(len(gsrc)),
                **stats,
            })

    return pd.DataFrame(rows)


def load_tracking_aggregated_csv(root: Path, scenario: str, metric: str) -> Optional[pd.DataFrame]:
    csv_path = root / "_aggregated" / "tracking" / scenario / f"{metric}_aggregated.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    return df


def load_sourcestats_aggregated_csv(root: Path, scenario: str, source_name: str, metric: str) -> Optional[pd.DataFrame]:
    csv_path = root / "_aggregated" / "sourcestats" / scenario / source_name / f"{metric}_aggregated.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    return df


def summarize_curve_df(df: pd.DataFrame) -> Dict[str, object]:
    mean_stats = compute_stats(df["mean"]) if "mean" in df.columns else compute_stats(pd.Series(dtype=float))
    std_stats = compute_stats(df["std"]) if "std" in df.columns else compute_stats(pd.Series(dtype=float))

    if "q75" in df.columns and "q25" in df.columns:
        iqr_width = pd.to_numeric(df["q75"], errors="coerce") - pd.to_numeric(df["q25"], errors="coerce")
    else:
        iqr_width = pd.Series(dtype=float)

    if "q90" in df.columns and "q10" in df.columns:
        p10p90_width = pd.to_numeric(df["q90"], errors="coerce") - pd.to_numeric(df["q10"], errors="coerce")
    else:
        p10p90_width = pd.Series(dtype=float)

    iqr_stats = compute_stats(iqr_width)
    p10p90_stats = compute_stats(p10p90_width)

    n_runs_series = pd.to_numeric(df["n_runs"], errors="coerce") if "n_runs" in df.columns else pd.Series(dtype=float)

    return {
        "n_points_curve": int(len(df)),
        "n_runs_min": int(n_runs_series.min()) if not n_runs_series.dropna().empty else np.nan,
        "n_runs_max": int(n_runs_series.max()) if not n_runs_series.dropna().empty else np.nan,

        "curve_mean_of_mean": mean_stats["mean"],
        "curve_std_of_mean": mean_stats["std"],
        "curve_min_of_mean": mean_stats["min"],
        "curve_q10_of_mean": mean_stats["q10"],
        "curve_q25_of_mean": mean_stats["q25"],
        "curve_median_of_mean": mean_stats["median"],
        "curve_q75_of_mean": mean_stats["q75"],
        "curve_q90_of_mean": mean_stats["q90"],
        "curve_max_of_mean": mean_stats["max"],
        "curve_range_of_mean": mean_stats["range"],
        "curve_iqr_of_mean": mean_stats["iqr"],
        "curve_cv_of_mean": mean_stats["cv"],

        "curve_mean_of_std": std_stats["mean"],
        "curve_std_of_std": std_stats["std"],
        "curve_max_of_std": std_stats["max"],

        "curve_mean_iqr_width": iqr_stats["mean"],
        "curve_std_iqr_width": iqr_stats["std"],
        "curve_median_iqr_width": iqr_stats["median"],
        "curve_max_iqr_width": iqr_stats["max"],

        "curve_mean_p10p90_width": p10p90_stats["mean"],
        "curve_std_p10p90_width": p10p90_stats["std"],
        "curve_median_p10p90_width": p10p90_stats["median"],
        "curve_max_p10p90_width": p10p90_stats["max"],
    }


def build_tracking_aggregated_curve_stats(root: Path, scenario: str) -> pd.DataFrame:
    rows = []

    for metric in TRACKING_METRICS:
        df = load_tracking_aggregated_csv(root, scenario, metric)
        if df is None:
            continue

        row = {
            "scenario": scenario,
            "section": "tracking",
            "metric": metric,
            "source": "aggregated_curve_over_sample_idx",
        }
        row.update(summarize_curve_df(df))
        rows.append(row)

    return pd.DataFrame(rows)


def build_sourcestats_aggregated_curve_stats(root: Path, scenario: str, available_sources: List[str]) -> pd.DataFrame:
    rows = []

    for source_name in available_sources:
        for metric in SOURCESTATS_METRICS:
            df = load_sourcestats_aggregated_csv(root, scenario, source_name, metric)
            if df is None:
                continue

            row = {
                "scenario": scenario,
                "section": "sourcestats",
                "source_name": source_name,
                "metric": metric,
                "source": "aggregated_curve_over_sample_idx",
            }
            row.update(summarize_curve_df(df))
            rows.append(row)

    return pd.DataFrame(rows)


def build_tracking_per_run_summary(df_all: pd.DataFrame, scenario: str) -> pd.DataFrame:
    rows = []

    if df_all.empty or "run_id" not in df_all.columns:
        return pd.DataFrame()

    for run_id, g in df_all.groupby("run_id"):
        row = {
            "scenario": scenario,
            "section": "tracking",
            "run_id": run_id,
            "n_rows": int(len(g)),
        }

        if "sample_idx" in g.columns:
            sidx = pd.to_numeric(g["sample_idx"], errors="coerce").dropna()
            row["max_sample_idx"] = int(sidx.max()) if not sidx.empty else np.nan

        if "t_rel_s" in g.columns:
            tvals = pd.to_numeric(g["t_rel_s"], errors="coerce").dropna()
            row["t_rel_min_s"] = float(tvals.min()) if not tvals.empty else np.nan
            row["t_rel_max_s"] = float(tvals.max()) if not tvals.empty else np.nan

        for metric in TRACKING_METRICS:
            if metric in g.columns:
                stats = compute_stats(g[metric])
                row[f"{metric}_mean"] = stats["mean"]
                row[f"{metric}_std"] = stats["std"]
                row[f"{metric}_median"] = stats["median"]
                row[f"{metric}_p95"] = float(pd.to_numeric(g[metric], errors="coerce").dropna().quantile(0.95)) if not pd.to_numeric(g[metric], errors="coerce").dropna().empty else np.nan
                row[f"{metric}_max"] = stats["max"]

        rows.append(row)

    return pd.DataFrame(rows)


def build_sourcestats_per_run_summary(df_all: pd.DataFrame, scenario: str) -> pd.DataFrame:
    rows = []

    if df_all.empty or "run_id" not in df_all.columns or "source" not in df_all.columns:
        return pd.DataFrame()

    for (run_id, source_name), g in df_all.groupby(["run_id", "source"]):
        row = {
            "scenario": scenario,
            "section": "sourcestats",
            "run_id": run_id,
            "source_name": source_name,
            "n_rows": int(len(g)),
        }

        if "sample_idx" in g.columns:
            sidx = pd.to_numeric(g["sample_idx"], errors="coerce").dropna()
            row["max_sample_idx"] = int(sidx.max()) if not sidx.empty else np.nan

        if "t_rel_s" in g.columns:
            tvals = pd.to_numeric(g["t_rel_s"], errors="coerce").dropna()
            row["t_rel_min_s"] = float(tvals.min()) if not tvals.empty else np.nan
            row["t_rel_max_s"] = float(tvals.max()) if not tvals.empty else np.nan

        for metric in SOURCESTATS_METRICS:
            if metric in g.columns:
                stats = compute_stats(g[metric])
                row[f"{metric}_mean"] = stats["mean"]
                row[f"{metric}_std"] = stats["std"]
                row[f"{metric}_median"] = stats["median"]
                row[f"{metric}_p95"] = float(pd.to_numeric(g[metric], errors="coerce").dropna().quantile(0.95)) if not pd.to_numeric(g[metric], errors="coerce").dropna().empty else np.nan
                row[f"{metric}_max"] = stats["max"]

        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute aggregated statistics for Chrony multiple-run analysis.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of Chrony multi-run logs, e.g. .../analysis/raw_logs/T3_multiplerun/chrony_servergm",
    )
    args = ap.parse_args()

    root = args.root.resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Root directory not found: {root}")

    stats_dirs = ensure_stats_dirs(root)

    for scenario in SCENARIOS:
        tracking_all = load_tracking_runs(root, scenario)
        sourcestats_all = load_sourcestats_runs(root, scenario)

        available_sources = []
        if not sourcestats_all.empty and "source" in sourcestats_all.columns:
            available_sources = sorted(sourcestats_all["source"].dropna().unique().tolist())

        outdir = stats_dirs[scenario]

        tracking_global = build_tracking_global_raw_stats(tracking_all, scenario)
        if not tracking_global.empty:
            tracking_global = round_numeric_columns(tracking_global)
            tracking_global.to_csv(outdir / "tracking_global_raw_stats.csv", index=False)

        tracking_curve = build_tracking_aggregated_curve_stats(root, scenario)
        if not tracking_curve.empty:
            tracking_curve = round_numeric_columns(tracking_curve)
            tracking_curve.to_csv(outdir / "tracking_aggregated_curve_stats.csv", index=False)

        tracking_per_run = build_tracking_per_run_summary(tracking_all, scenario)
        if not tracking_per_run.empty:
            tracking_per_run = round_numeric_columns(tracking_per_run)
            tracking_per_run.to_csv(outdir / "tracking_per_run_summary.csv", index=False)

        sourcestats_global = build_sourcestats_global_raw_stats(sourcestats_all, scenario)
        if not sourcestats_global.empty:
            sourcestats_global = round_numeric_columns(sourcestats_global)
            sourcestats_global.to_csv(outdir / "sourcestats_global_raw_stats.csv", index=False)

        sourcestats_curve = build_sourcestats_aggregated_curve_stats(root, scenario, available_sources)
        if not sourcestats_curve.empty:
            sourcestats_curve = round_numeric_columns(sourcestats_curve)
            sourcestats_curve.to_csv(outdir / "sourcestats_aggregated_curve_stats.csv", index=False)

        sourcestats_per_run = build_sourcestats_per_run_summary(sourcestats_all, scenario)
        if not sourcestats_per_run.empty:
            sourcestats_per_run = round_numeric_columns(sourcestats_per_run)
            sourcestats_per_run.to_csv(outdir / "sourcestats_per_run_summary.csv", index=False)

    print(f"[OK] Chrony aggregated statistics saved in: {root / '_aggregated' / 'stats'}")


if __name__ == "__main__":
    main()