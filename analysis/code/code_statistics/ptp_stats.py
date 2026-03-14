#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd


def safe_cv(mean_val: float, std_val: float) -> float:
    if pd.isna(mean_val) or pd.isna(std_val):
        return np.nan
    if abs(mean_val) < 1e-12:
        return np.nan
    return std_val / mean_val


def compute_stats(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()

    if len(s) == 0:
        return {
            "n_valid_metric": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "q1": np.nan,
            "median": np.nan,
            "q3": np.nan,
            "max": np.nan,
            "range": np.nan,
            "iqr": np.nan,
            "cv": np.nan,
        }

    mean_val = s.mean()
    std_val = s.std(ddof=1) if len(s) > 1 else 0.0
    min_val = s.min()
    q1_val = s.quantile(0.25)
    median_val = s.median()
    q3_val = s.quantile(0.75)
    max_val = s.max()
    range_val = max_val - min_val
    iqr_val = q3_val - q1_val
    cv_val = safe_cv(mean_val, std_val)

    return {
        "n_valid_metric": int(len(s)),
        "mean": mean_val,
        "std": std_val,
        "min": min_val,
        "q1": q1_val,
        "median": median_val,
        "q3": q3_val,
        "max": max_val,
        "range": range_val,
        "iqr": iqr_val,
        "cv": cv_val,
    }


def extract_node_scenario(filename: str):
    """
    Estrae node e scenario da nomi flessibili contenenti:
    - client / boundary
    - low / medium / high

    Esempi compatibili:
    client_low.csv
    boundary_medium_parser.csv
    ptp_boundary_high_samples.csv
    """
    name = filename.lower()

    node = None
    scenario = None

    for n in ["client", "boundary"]:
        if re.search(rf"(^|[_\-]){n}([_\-.]|$)", name):
            node = n
            break

    for s in ["low", "medium", "high"]:
        if re.search(rf"(^|[_\-]){s}([_\-.]|$)", name):
            scenario = s
            break

    return node, scenario


def analyze_boundary(df: pd.DataFrame, csv_name: str, scenario: str):
    rows = []
    n_total_rows = len(df)

    # offset_ns su tutti i campioni
    if "offset_ns" in df.columns:
        stats = compute_stats(df["offset_ns"])
        rows.append({
            "node": "boundary",
            "scenario": scenario,
            "parameter": "offset_ns",
            "source_file": csv_name,
            "filter_rule": "all_rows",
            "n_total_rows": n_total_rows,
            "n_filtered_rows": n_total_rows,
            "first_valid_t_rel_s": pd.to_numeric(df["t_rel_s"], errors="coerce").dropna().iloc[0] if "t_rel_s" in df.columns and pd.to_numeric(df["t_rel_s"], errors="coerce").dropna().size > 0 else np.nan,
            **stats
        })

    # offset_ns_postlock_s2 solo servo_state == 2
    if "offset_ns" in df.columns and "servo_state" in df.columns:
        df_s2 = df[df["servo_state"] == 2].copy()
        first_valid_t = np.nan
        if "t_rel_s" in df_s2.columns:
            tvals = pd.to_numeric(df_s2["t_rel_s"], errors="coerce").dropna()
            if len(tvals) > 0:
                first_valid_t = tvals.iloc[0]

        stats = compute_stats(df_s2["offset_ns"])
        rows.append({
            "node": "boundary",
            "scenario": scenario,
            "parameter": "offset_ns_postlock_s2",
            "source_file": csv_name,
            "filter_rule": "servo_state==2",
            "n_total_rows": n_total_rows,
            "n_filtered_rows": len(df_s2),
            "first_valid_t_rel_s": first_valid_t,
            **stats
        })

    # path_delay_ns su tutti i campioni
    if "path_delay_ns" in df.columns:
        stats = compute_stats(df["path_delay_ns"])
        rows.append({
            "node": "boundary",
            "scenario": scenario,
            "parameter": "path_delay_ns",
            "source_file": csv_name,
            "filter_rule": "all_rows",
            "n_total_rows": n_total_rows,
            "n_filtered_rows": n_total_rows,
            "first_valid_t_rel_s": pd.to_numeric(df["t_rel_s"], errors="coerce").dropna().iloc[0] if "t_rel_s" in df.columns and pd.to_numeric(df["t_rel_s"], errors="coerce").dropna().size > 0 else np.nan,
            **stats
        })

    return rows


def analyze_client(df: pd.DataFrame, csv_name: str, scenario: str):
    rows = []
    n_total_rows = len(df)
    first_valid_t = np.nan

    if "t_rel_s" in df.columns:
        tvals = pd.to_numeric(df["t_rel_s"], errors="coerce").dropna()
        if len(tvals) > 0:
            first_valid_t = tvals.iloc[0]

    for param in ["rms_ns", "path_delay_ns"]:
        if param in df.columns:
            stats = compute_stats(df[param])
            rows.append({
                "node": "client",
                "scenario": scenario,
                "parameter": param,
                "source_file": csv_name,
                "filter_rule": "all_rows",
                "n_total_rows": n_total_rows,
                "n_filtered_rows": n_total_rows,
                "first_valid_t_rel_s": first_valid_t,
                **stats
            })

    return rows


def analyze_file(csv_path: Path):
    df = pd.read_csv(csv_path)
    node, scenario = extract_node_scenario(csv_path.name)

    if node is None or scenario is None:
        return []

    # client high assente/non analizzabile: se non c'è file non fa nulla.
    # se per errore esiste un file client-high, puoi decidere se saltarlo:
    if node == "client" and scenario == "high":
        return []

    if node == "boundary":
        return analyze_boundary(df, csv_path.name, scenario)

    if node == "client":
        return analyze_client(df, csv_path.name, scenario)

    return []


def main():
    parser = argparse.ArgumentParser(description="Calcola statistiche descrittive per i parser PTP.")
    parser.add_argument(
        "input_dir",
        type=str,
        help="Cartella contenente i file CSV parser PTP"
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Cartella non trovata: {input_dir}")

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"Nessun file CSV trovato in {input_dir}")

    all_rows = []
    for csv_file in csv_files:
        all_rows.extend(analyze_file(csv_file))

    if not all_rows:
        raise RuntimeError("Nessuna statistica prodotta. Controlla i nomi dei file.")

    out_df = pd.DataFrame(all_rows)

    node_order = {"client": 0, "boundary": 1}
    scenario_order = {"low": 0, "medium": 1, "high": 2}
    param_order = {
        "rms_ns": 0,
        "offset_ns": 1,
        "offset_ns_postlock_s2": 2,
        "path_delay_ns": 3,
    }

    out_df["_node_ord"] = out_df["node"].map(node_order)
    out_df["_scenario_ord"] = out_df["scenario"].map(scenario_order)
    out_df["_param_ord"] = out_df["parameter"].map(param_order)

    out_df = out_df.sort_values(
        by=["_node_ord", "_scenario_ord", "_param_ord"]
    ).drop(columns=["_node_ord", "_scenario_ord", "_param_ord"])

    numeric_cols = [
        "first_valid_t_rel_s",
        "mean", "std", "min", "q1", "median", "q3",
        "max", "range", "iqr", "cv"
    ]
    for col in numeric_cols:
        if col in out_df.columns:
            out_df[col] = out_df[col].round(6)

    stats_dir = input_dir / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)

    output_csv = stats_dir / "ptp_statistics.csv"
    out_df.to_csv(output_csv, index=False)

    print(f"[OK] File statistiche creato: {output_csv}")


if __name__ == "__main__":
    main()