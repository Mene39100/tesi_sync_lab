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

    for _, g in df_all.groupby("run_id", sort=True):
        g = g.copy()
        sel = g["selected"].astype(bool)

        if not sel.any():
            continue

        first_sel_sample_idx = g.loc[sel, "sample_idx"].min()
        g_post = g[g["sample_idx"] >= first_sel_sample_idx].copy()

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


def rebuild_post_selected_curve(df_all: pd.DataFrame, metric: str) -> pd.DataFrame:
    """
    Ricostruisce la curva aggregata post-selected a partire dai parsed per-run:
    per ogni run tiene solo i campioni dal primo selected=True in poi,
    poi reindicizza sample_idx da 0 all'interno della porzione post-selected
    e riaggrega tra run.
    """
    if df_all.empty or metric not in df_all.columns:
        return pd.DataFrame()

    if "selected" not in df_all.columns or "run_id" not in df_all.columns:
        return pd.DataFrame()

    pieces = []

    for _, g in df_all.groupby("run_id", sort=True):
        g = g.copy()
        sel = g["selected"].astype(bool)

        if not sel.any():
            continue

        first_sel_sample_idx = g.loc[sel, "sample_idx"].min()
        g_post = g[g["sample_idx"] >= first_sel_sample_idx].copy()

        if g_post.empty:
            continue

        g_post = g_post.reset_index(drop=True)
        g_post["sample_idx"] = g_post.index.astype(int)

        tmp = g_post[["sample_idx", metric, "run_id"]].copy()
        tmp = tmp.dropna(subset=[metric])
        if not tmp.empty:
            pieces.append(tmp)

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
        se = std / np.sqrt(n) if n > 1 else 0.0
        ci_half = 1.96 * se if n > 1 else 0.0

        return pd.Series({
            "n_runs": int(n),
            "mean": float(mean),
            "std": float(std),
            "ci95_low": float(mean - ci_half),
            "ci95_high": float(mean + ci_half),
            "q10": float(vals.quantile(0.10)),
            "q25": float(vals.quantile(0.25)),
            "q50": float(vals.quantile(0.50)),
            "q75": float(vals.quantile(0.75)),
            "q90": float(vals.quantile(0.90)),
            "min": float(vals.min()),
            "max": float(vals.max()),
        })

    out = long_df.groupby("sample_idx", as_index=False).apply(agg_fn)
    if isinstance(out.index, pd.MultiIndex):
        out = out.reset_index()
    if "level_0" in out.columns:
        out = out.drop(columns=["level_0"])

    return out


def build_curve_stats_row(
    df: pd.DataFrame,
    scenario: str,
    role: str,
    metric: str,
    curve_scope: str,
    source_label: str,
) -> Optional[Dict]:
    if df is None or df.empty:
        return None

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

    if "ci95_high" in df.columns and "ci95_low" in df.columns:
        ci95_width = pd.to_numeric(df["ci95_high"], errors="coerce") - pd.to_numeric(df["ci95_low"], errors="coerce")
    else:
        ci95_width = pd.Series(dtype=float)

    iqr_stats = compute_stats(iqr_width)
    p10p90_stats = compute_stats(p10p90_width)
    ci95_stats = compute_stats(ci95_width)

    n_runs_stats = compute_stats(pd.to_numeric(df["n_runs"], errors="coerce")) if "n_runs" in df.columns else compute_stats(pd.Series(dtype=float))

    abs_mean_stats = compute_stats(pd.to_numeric(df["mean"], errors="coerce").abs()) if "mean" in df.columns else compute_stats(pd.Series(dtype=float))

    return {
        "scenario": scenario,
        "role": role,
        "metric": metric,
        "curve_scope": curve_scope,
        "source_file": source_label,
        "n_samples_aggregated": int(len(df)),

        "central_n_valid": mean_stats["n_valid"],
        "central_mean": mean_stats["mean"],
        "central_std": mean_stats["std"],
        "central_min": mean_stats["min"],
        "central_q25": mean_stats["q25"],
        "central_median": mean_stats["median"],
        "central_q75": mean_stats["q75"],
        "central_max": mean_stats["max"],
        "central_iqr": mean_stats["iqr"],

        "central_abs_mean": abs_mean_stats["mean"],
        "central_abs_q95": float(pd.to_numeric(df["mean"], errors="coerce").abs().quantile(0.95)) if "mean" in df.columns and not pd.to_numeric(df["mean"], errors="coerce").dropna().empty else np.nan,
        "central_abs_max": float(pd.to_numeric(df["mean"], errors="coerce").abs().max()) if "mean" in df.columns and not pd.to_numeric(df["mean"], errors="coerce").dropna().empty else np.nan,

        "iqr_width_n_valid": iqr_stats["n_valid"],
        "iqr_width_mean": iqr_stats["mean"],
        "iqr_width_std": iqr_stats["std"],
        "iqr_width_min": iqr_stats["min"],
        "iqr_width_q25": iqr_stats["q25"],
        "iqr_width_median": iqr_stats["median"],
        "iqr_width_q75": iqr_stats["q75"],
        "iqr_width_max": iqr_stats["max"],
        "iqr_width_iqr": iqr_stats["iqr"],

        "p10p90_width_n_valid": p10p90_stats["n_valid"],
        "p10p90_width_mean": p10p90_stats["mean"],
        "p10p90_width_std": p10p90_stats["std"],
        "p10p90_width_min": p10p90_stats["min"],
        "p10p90_width_q25": p10p90_stats["q25"],
        "p10p90_width_median": p10p90_stats["median"],
        "p10p90_width_q75": p10p90_stats["q75"],
        "p10p90_width_max": p10p90_stats["max"],
        "p10p90_width_iqr": p10p90_stats["iqr"],

        "ci95_width_n_valid": ci95_stats["n_valid"],
        "ci95_width_mean": ci95_stats["mean"],
        "ci95_width_std": ci95_stats["std"],
        "ci95_width_min": ci95_stats["min"],
        "ci95_width_q25": ci95_stats["q25"],
        "ci95_width_median": ci95_stats["median"],
        "ci95_width_q75": ci95_stats["q75"],
        "ci95_width_max": ci95_stats["max"],
        "ci95_width_iqr": ci95_stats["iqr"],

        "n_runs_n_valid": n_runs_stats["n_valid"],
        "n_runs_mean": n_runs_stats["mean"],
        "n_runs_std": n_runs_stats["std"],
        "n_runs_min": n_runs_stats["min"],
        "n_runs_q25": n_runs_stats["q25"],
        "n_runs_median": n_runs_stats["median"],
        "n_runs_q75": n_runs_stats["q75"],
        "n_runs_max": n_runs_stats["max"],
        "n_runs_iqr": n_runs_stats["iqr"],
    }


def build_aggregated_curve_stats(
    root: Path,
    scenario: str,
    role: str,
    df_all: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for metric in METRICS:
        raw_curve = load_aggregated_curve_csv(root, scenario, role, metric)
        post_curve = rebuild_post_selected_curve(df_all, metric)

        raw_row = build_curve_stats_row(
            df=raw_curve,
            scenario=scenario,
            role=role,
            metric=metric,
            curve_scope="raw",
            source_label=f"{metric}_aggregated.csv",
        )
        if raw_row is not None:
            rows.append(raw_row)

        post_row = build_curve_stats_row(
            df=post_curve,
            scenario=scenario,
            role=role,
            metric=metric,
            curve_scope="post_selected",
            source_label=f"{metric}_aggregated_post_selected_rebuilt",
        )
        if post_row is not None:
            rows.append(post_row)

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

            curve_stats = build_aggregated_curve_stats(root, scenario, role, df_all)

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