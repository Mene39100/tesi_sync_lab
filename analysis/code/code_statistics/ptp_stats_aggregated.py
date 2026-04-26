#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


SCENARIOS = ["low", "medium", "high"]

PTP_LAYOUT = {
    "boundary": ["offset_ns", "path_delay_ns"],
    "client": ["rms_ns", "path_delay_ns"],
}


def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").dropna()


def compute_basic_stats(series: pd.Series, prefix: str) -> Dict[str, float]:
    s = safe_numeric(series)

    if s.empty:
        return {
            f"{prefix}_n_valid": 0,
            f"{prefix}_mean": np.nan,
            f"{prefix}_std": np.nan,
            f"{prefix}_min": np.nan,
            f"{prefix}_q25": np.nan,
            f"{prefix}_median": np.nan,
            f"{prefix}_q75": np.nan,
            f"{prefix}_max": np.nan,
            f"{prefix}_iqr": np.nan,
        }

    q25 = float(s.quantile(0.25))
    q75 = float(s.quantile(0.75))

    return {
        f"{prefix}_n_valid": int(len(s)),
        f"{prefix}_mean": float(s.mean()),
        f"{prefix}_std": float(s.std(ddof=1)) if len(s) > 1 else 0.0,
        f"{prefix}_min": float(s.min()),
        f"{prefix}_q25": q25,
        f"{prefix}_median": float(s.median()),
        f"{prefix}_q75": q75,
        f"{prefix}_max": float(s.max()),
        f"{prefix}_iqr": q75 - q25,
    }


def compute_abs_stats(series: pd.Series, prefix: str) -> Dict[str, float]:
    s = safe_numeric(series).abs()

    if s.empty:
        return {
            f"{prefix}_abs_mean": np.nan,
            f"{prefix}_abs_q95": np.nan,
            f"{prefix}_abs_max": np.nan,
        }

    return {
        f"{prefix}_abs_mean": float(s.mean()),
        f"{prefix}_abs_q95": float(s.quantile(0.95)),
        f"{prefix}_abs_max": float(s.max()),
    }


def summarize_aggregated_file(csv_path: Path, role: str, scenario: str, metric: str) -> Dict[str, object]:
    df = pd.read_csv(csv_path)

    out: Dict[str, object] = {
        "role": role,
        "scenario": scenario,
        "metric": metric,
        "source_file": str(csv_path.name),
        "n_samples_aggregated": int(len(df)),
    }

    # curva centrale
    if "mean" in df.columns:
        out.update(compute_basic_stats(df["mean"], "central"))
        if metric == "offset_ns":
            out.update(compute_abs_stats(df["mean"], "central"))
    else:
        out.update(compute_basic_stats(pd.Series(dtype=float), "central"))
        if metric == "offset_ns":
            out.update(compute_abs_stats(pd.Series(dtype=float), "central"))

    # banda IQR
    if "q25" in df.columns and "q75" in df.columns:
        iqr_width = pd.to_numeric(df["q75"], errors="coerce") - pd.to_numeric(df["q25"], errors="coerce")
        out.update(compute_basic_stats(iqr_width, "iqr_width"))
    else:
        out.update(compute_basic_stats(pd.Series(dtype=float), "iqr_width"))

    # banda p10-p90
    if "q10" in df.columns and "q90" in df.columns:
        p10p90_width = pd.to_numeric(df["q90"], errors="coerce") - pd.to_numeric(df["q10"], errors="coerce")
        out.update(compute_basic_stats(p10p90_width, "p10p90_width"))
    else:
        out.update(compute_basic_stats(pd.Series(dtype=float), "p10p90_width"))

    # banda CI95
    if "ci95_low" in df.columns and "ci95_high" in df.columns:
        ci95_width = pd.to_numeric(df["ci95_high"], errors="coerce") - pd.to_numeric(df["ci95_low"], errors="coerce")
        out.update(compute_basic_stats(ci95_width, "ci95_width"))
    else:
        out.update(compute_basic_stats(pd.Series(dtype=float), "ci95_width"))

    # numero di run per sample
    if "n_runs" in df.columns:
        out.update(compute_basic_stats(df["n_runs"], "n_runs"))
    else:
        out.update(compute_basic_stats(pd.Series(dtype=float), "n_runs"))

    return out


def build_scenario_stats(root: Path, scenario: str) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    agg_root = root / "_aggregated"

    for role, metrics in PTP_LAYOUT.items():
        role_dir = agg_root / role / scenario
        if not role_dir.exists():
            continue

        for metric in metrics:
            csv_path = role_dir / f"{metric}_aggregated.csv"
            if not csv_path.exists():
                continue

            rows.append(summarize_aggregated_file(csv_path, role=role, scenario=scenario, metric=metric))

    if not rows:
        return pd.DataFrame()

    out = pd.DataFrame(rows)

    role_order = {"client": 0, "boundary": 1}
    metric_order = {
        "rms_ns": 0,
        "offset_ns": 1,
        "path_delay_ns": 2,
    }

    out["_role_ord"] = out["role"].map(role_order)
    out["_metric_ord"] = out["metric"].map(metric_order)
    out = out.sort_values(["_role_ord", "_metric_ord"]).drop(columns=["_role_ord", "_metric_ord"])

    numeric_cols = out.select_dtypes(include=["number"]).columns.tolist()
    for col in numeric_cols:
        out[col] = out[col].round(6)

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build PTP statistics tables from already aggregated multi-run CSVs.")
    ap.add_argument(
        "--root",
        type=Path,
        required=True,
        help="PTP root directory, e.g. .../analysis/raw_logs/T3_multiplerun/ptp",
    )
    args = ap.parse_args()

    root = args.root.resolve()
    agg_root = root / "_aggregated"
    if not agg_root.exists():
        raise FileNotFoundError(f"Cartella non trovata: {agg_root}")

    stats_root = agg_root / "stats"
    stats_root.mkdir(parents=True, exist_ok=True)

    produced = []

    for scenario in SCENARIOS:
        scenario_dir = stats_root / scenario
        scenario_dir.mkdir(parents=True, exist_ok=True)

        df = build_scenario_stats(root, scenario)
        if df.empty:
            continue

        out_csv = scenario_dir / f"ptp_stats_{scenario}.csv"
        df.to_csv(out_csv, index=False)
        produced.append(out_csv)

    if not produced:
        raise RuntimeError("Nessun file statistico prodotto. Controlla che i CSV aggregati esistano.")

    print("[OK] File statistici creati:")
    for p in produced:
        print(f" - {p}")


if __name__ == "__main__":
    main()