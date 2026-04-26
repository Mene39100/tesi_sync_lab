#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


SCENARIOS = ["low", "medium", "high"]
ROLES = ["client", "boundary"]

ROLE_FILE_MAP = {
    "client": "parsed_client_samples.csv",
    "boundary": "parsed_boundary_samples.csv",
}

METRICS = ["offset_ms", "jitter_ms", "delay_ms"]


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


def load_run_files(root: Path, scenario: str, role: str) -> pd.DataFrame:
    rows: List[pd.DataFrame] = []
    scenario_dir = root / scenario
    fname = ROLE_FILE_MAP[role]

    if not scenario_dir.exists():
        return pd.DataFrame()

    for run_dir in sorted([p for p in scenario_dir.iterdir() if p.is_dir() and p.name.startswith("run")]):
        csv_path = run_dir / fname
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


def filter_post_selected_per_run(df_all: pd.DataFrame) -> pd.DataFrame:
    """
    Per ogni run mantiene solo i campioni dal primo selected == True in poi.
    Se una run non ha selected oppure non ha mai selected == True, viene scartata.
    """
    if df_all.empty or "run_id" not in df_all.columns or "selected" not in df_all.columns:
        return pd.DataFrame()

    parts: List[pd.DataFrame] = []

    for run_id, g in df_all.groupby("run_id", sort=True):
        g = g.copy()

        sel = g["selected"].astype(bool)
        if not sel.any():
            continue

        first_sel_idx = g.loc[sel, "sample_idx"].min()
        g_post = g[g["sample_idx"] >= first_sel_idx].copy()

        if not g_post.empty:
            parts.append(g_post)

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)


def build_global_raw_stats(df_all: pd.DataFrame, scenario: str, role: str, source_label: str) -> pd.DataFrame:
    rows = []

    if df_all.empty:
        return pd.DataFrame()

    n_runs = df_all["run_id"].nunique() if "run_id" in df_all.columns else np.nan

    for metric in METRICS:
        if metric not in df_all.columns:
            continue

        stats = compute_stats(df_all[metric])

        rows.append({
            "scenario": scenario,
            "role": role,
            "metric": metric,
            "source": source_label,
            "n_runs_total": int(n_runs) if not pd.isna(n_runs) else np.nan,
            "n_total_rows": int(len(df_all)),
            **stats,
        })

    return pd.DataFrame(rows)


def load_aggregated_curve_csv(root: Path, scenario: str, role: str, metric: str) -> Optional[pd.DataFrame]:
    csv_path = root / "_aggregated" / role / scenario / f"{metric}_aggregated.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        return None
    return df


def build_aggregated_curve_stats(
    root: Path,
    scenario: str,
    role: str,
) -> pd.DataFrame:
    rows = []

    for metric in METRICS:
        df = load_aggregated_curve_csv(root, scenario, role, metric)
        if df is None or df.empty:
            continue

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

        rows.append({
            "scenario": scenario,
            "role": role,
            "metric": metric,
            "source": "aggregated_curve_over_sample_idx",
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
        })

    return pd.DataFrame(rows)


def build_per_run_summary(df_all: pd.DataFrame, scenario: str, role: str, summary_source: str) -> pd.DataFrame:
    rows = []

    if df_all.empty or "run_id" not in df_all.columns:
        return pd.DataFrame()

    for run_id, g in df_all.groupby("run_id"):
        row = {
            "scenario": scenario,
            "role": role,
            "run_id": run_id,
            "summary_source": summary_source,
            "n_rows": int(len(g)),
        }

        if "sample_idx" in g.columns:
            sidx = pd.to_numeric(g["sample_idx"], errors="coerce").dropna()
            row["min_sample_idx"] = int(sidx.min()) if not sidx.empty else np.nan
            row["max_sample_idx"] = int(sidx.max()) if not sidx.empty else np.nan

        if "t_rel_s" in g.columns:
            tvals = pd.to_numeric(g["t_rel_s"], errors="coerce").dropna()
            row["t_rel_min_s"] = float(tvals.min()) if not tvals.empty else np.nan
            row["t_rel_max_s"] = float(tvals.max()) if not tvals.empty else np.nan

        if "selected" in g.columns:
            sel = g["selected"].astype(bool)
            row["n_selected_rows"] = int(sel.sum())
            row["selected_fraction"] = float(sel.mean()) if len(sel) > 0 else np.nan

        for metric in METRICS:
            if metric in g.columns:
                metric_vals = pd.to_numeric(g[metric], errors="coerce").dropna()
                stats = compute_stats(g[metric])
                row[f"{metric}_mean"] = stats["mean"]
                row[f"{metric}_std"] = stats["std"]
                row[f"{metric}_median"] = stats["median"]
                row[f"{metric}_p95"] = float(metric_vals.quantile(0.95)) if not metric_vals.empty else np.nan
                row[f"{metric}_max"] = stats["max"]

        rows.append(row)

    return pd.DataFrame(rows)


def ensure_stats_dirs(root: Path) -> Dict[str, Path]:
    base = root / "_aggregated" / "stats"
    base.mkdir(parents=True, exist_ok=True)

    out = {}
    for scenario in SCENARIOS:
        d = base / scenario
        d.mkdir(parents=True, exist_ok=True)
        out[scenario] = d

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Compute aggregated statistics for NTPsec multiple-run analysis.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root directory of NTPsec multi-run logs, e.g. .../analysis/raw_logs/T3_multiplerun/ntpsec",
    )
    args = ap.parse_args()

    root = args.root.resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Root directory not found: {root}")

    stats_dirs = ensure_stats_dirs(root)

    for scenario in SCENARIOS:
        scenario_frames_global_raw = []
        scenario_frames_global_post = []
        scenario_frames_curve = []
        scenario_frames_per_run_raw = []
        scenario_frames_per_run_post = []

        for role in ROLES:
            df_all = load_run_files(root, scenario, role)
            df_post = filter_post_selected_per_run(df_all)

            global_raw = build_global_raw_stats(
                df_all=df_all,
                scenario=scenario,
                role=role,
                source_label="all_raw_samples_across_runs",
            )

            global_post = build_global_raw_stats(
                df_all=df_post,
                scenario=scenario,
                role=role,
                source_label="post_selected_samples_across_runs",
            )

            curve_stats = build_aggregated_curve_stats(root, scenario, role)

            per_run_raw = build_per_run_summary(
                df_all=df_all,
                scenario=scenario,
                role=role,
                summary_source="raw",
            )

            per_run_post = build_per_run_summary(
                df_all=df_post,
                scenario=scenario,
                role=role,
                summary_source="post_selected",
            )

            if not global_raw.empty:
                scenario_frames_global_raw.append(global_raw)
            if not global_post.empty:
                scenario_frames_global_post.append(global_post)
            if not curve_stats.empty:
                scenario_frames_curve.append(curve_stats)
            if not per_run_raw.empty:
                scenario_frames_per_run_raw.append(per_run_raw)
            if not per_run_post.empty:
                scenario_frames_per_run_post.append(per_run_post)

        outdir = stats_dirs[scenario]

        if scenario_frames_global_raw:
            global_raw_df = pd.concat(scenario_frames_global_raw, ignore_index=True)
            global_raw_df = round_numeric_columns(global_raw_df)
            global_raw_df.to_csv(outdir / "global_raw_stats.csv", index=False)

        if scenario_frames_global_post:
            global_post_df = pd.concat(scenario_frames_global_post, ignore_index=True)
            global_post_df = round_numeric_columns(global_post_df)
            global_post_df.to_csv(outdir / "global_post_selected_stats.csv", index=False)

        if scenario_frames_curve:
            curve_df = pd.concat(scenario_frames_curve, ignore_index=True)
            curve_df = round_numeric_columns(curve_df)
            curve_df.to_csv(outdir / "aggregated_curve_stats.csv", index=False)

        if scenario_frames_per_run_raw:
            per_run_raw_df = pd.concat(scenario_frames_per_run_raw, ignore_index=True)
            per_run_raw_df = round_numeric_columns(per_run_raw_df)
            per_run_raw_df.to_csv(outdir / "per_run_summary.csv", index=False)

        if scenario_frames_per_run_post:
            per_run_post_df = pd.concat(scenario_frames_per_run_post, ignore_index=True)
            per_run_post_df = round_numeric_columns(per_run_post_df)
            per_run_post_df.to_csv(outdir / "per_run_post_selected_summary.csv", index=False)

    print(f"[OK] NTPsec aggregated statistics saved in: {root / '_aggregated' / 'stats'}")


if __name__ == "__main__":
    main()