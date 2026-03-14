#!/usr/bin/env python3
import argparse
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

PARAMS = ["delay_ms", "offset_ms", "jitter_ms"]
SCENARIOS = ["low", "medium", "high"]
NODES = ["client", "boundary"]


def safe_cv(mean_val: float, std_val: float) -> float:
    if pd.isna(mean_val) or pd.isna(std_val):
        return np.nan
    if abs(mean_val) < 1e-12:
        return np.nan
    return std_val / mean_val


def extract_node_scenario(filename: str):
    """
    Estrae node e scenario da nomi tipo:
    client_low_samples.csv
    boundary_high_samples.csv
    """
    m = re.match(r"^(client|boundary)_(low|medium|high)_samples\.csv$", filename)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def compute_stats(series: pd.Series):
    """
    Statistiche descrittive su una serie numerica.
    Usa ddof=1 per la deviazione standard campionaria.
    """
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


def analyze_file(csv_path: Path):
    df = pd.read_csv(csv_path)

    node, scenario = extract_node_scenario(csv_path.name)
    if node is None or scenario is None:
        return []

    # Campioni totali
    n_total_rows = len(df)

    # Filtro per regime operativo:
    # selected == True
    if "selected" not in df.columns:
        raise ValueError(f"Colonna 'selected' mancante in {csv_path}")

    df_valid = df[df["selected"] == True].copy()
    n_selected_rows = len(df_valid)

    # Informazioni temporali sul primo campione valido
    first_valid_t_rel_s = np.nan
    if n_selected_rows > 0 and "t_rel_s" in df_valid.columns:
        first_valid_t_rel_s = pd.to_numeric(df_valid["t_rel_s"], errors="coerce").dropna()
        first_valid_t_rel_s = first_valid_t_rel_s.iloc[0] if len(first_valid_t_rel_s) > 0 else np.nan

    rows = []

    for param in PARAMS:
        if param not in df.columns:
            continue

        stats = compute_stats(df_valid[param])

        row = {
            "node": node,
            "scenario": scenario,
            "parameter": param,
            "source_file": csv_path.name,
            "n_total_rows": n_total_rows,
            "n_selected_rows": n_selected_rows,
            "first_valid_t_rel_s": first_valid_t_rel_s,
            **stats,
        }
        rows.append(row)

    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Calcola statistiche descrittive per i parser NTPsec."
    )
    parser.add_argument(
        "input_dir",
        type=str,
        help="Cartella contenente i file *_samples.csv di NTPsec",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        raise FileNotFoundError(f"Cartella non trovata: {input_dir}")

    sample_files = sorted(input_dir.glob("*_samples.csv"))
    if not sample_files:
        raise FileNotFoundError(f"Nessun file '*_samples.csv' trovato in {input_dir}")

    all_rows = []
    for csv_file in sample_files:
        all_rows.extend(analyze_file(csv_file))

    if not all_rows:
        raise RuntimeError("Nessuna statistica prodotta.")

    out_df = pd.DataFrame(all_rows)

    # Ordinamento coerente
    node_order = {n: i for i, n in enumerate(NODES)}
    scenario_order = {s: i for i, s in enumerate(SCENARIOS)}
    param_order = {p: i for i, p in enumerate(PARAMS)}

    out_df["_node_ord"] = out_df["node"].map(node_order)
    out_df["_scenario_ord"] = out_df["scenario"].map(scenario_order)
    out_df["_param_ord"] = out_df["parameter"].map(param_order)

    out_df = out_df.sort_values(
        by=["_node_ord", "_scenario_ord", "_param_ord"]
    ).drop(columns=["_node_ord", "_scenario_ord", "_param_ord"])

    # Arrotondamento per leggibilità
    numeric_cols = [
        "first_valid_t_rel_s",
        "mean", "std", "min", "q1", "median", "q3", "max",
        "range", "iqr", "cv"
    ]
    for col in numeric_cols:
        if col in out_df.columns:
            out_df[col] = out_df[col].round(6)

    # Output nella sottocartella statistics
    stats_dir = input_dir / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)

    output_csv = stats_dir / "ntpsec_statistics.csv"
    out_df.to_csv(output_csv, index=False)

    print(f"[OK] File statistiche creato: {output_csv}")


if __name__ == "__main__":
    main()