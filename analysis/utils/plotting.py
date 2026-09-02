import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import numpy as np

def plot_mass_error_distribution(mass_errors_ppm: list[float], output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(mass_errors_ppm, bins=10, color="#4C72B0", edgecolor="black")
    ax.axvline(0, color="black", linestyle="--", linewidth=1)
    ax.set_xlabel("Mass error (ppm)")
    ax.set_ylabel("Count")
    ax.set_title("Mass error distribution")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_purity_distribution(purity_values: list[float], min_purity: float, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(purity_values, bins=10, color="#55A868", edgecolor="black")
    ax.axvline(min_purity, color="red", linestyle="--", linewidth=1, label=f"threshold ({min_purity})")
    ax.set_xlabel("Spectral purity")
    ax.set_ylabel("Count")
    ax.set_title("Spectral purity distribution")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_identification_summary(identification_rate: float, validation_rate: float | None, output_path: Path) -> None:
    labels, values = ["Identification rate"], [identification_rate]
    if validation_rate is not None:
        labels.append("Library validation rate")
        values.append(validation_rate)

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(labels, values, color=["#4C72B0", "#C44E52"][:len(values)])
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Rate")
    ax.set_title("Identification / validation summary")
    for i, v in enumerate(values):
        ax.text(i, v + 0.02, f"{v:.2f}", ha="center")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_tic(scan_df: pd.DataFrame, sample_id: str, output_path: Path) -> None:
    ms1 = scan_df[scan_df["ms_level"] == 1].sort_values("retention_time_min")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(ms1["retention_time_min"], ms1["total_ion_current"], linewidth=0.8, color="#4C72B0")
    ax.set_xlabel("Retention time (min)")
    ax.set_ylabel("Total ion current")
    ax.set_title(f"TIC — {sample_id}")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_bpc(scan_df: pd.DataFrame, sample_id: str, output_path: Path) -> None:
    ms1 = scan_df[scan_df["ms_level"] == 1].sort_values("retention_time_min")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(ms1["retention_time_min"], ms1["base_peak_intensity"], linewidth=0.8, color="#55A868")
    ax.set_xlabel("Retention time (min)")
    ax.set_ylabel("Base peak intensity")
    ax.set_title(f"BPC — {sample_id}")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_tic_overlay(scan_dfs: dict[str, pd.DataFrame], output_path: Path, color_by_group: dict[str, str] | None = None) -> None:
    """
    Overlays every sample's TIC on one figure
    The standard cohort-scale QC check: do all runs look similar in shape/timing, or does one
    obviously deviate (contamination, instrument drift, wrong injection)?
    color_by_group: optional {sample_id: group_label} (e.g. "QC"/"NSC"/
    "T691"/"TUM6") to color-code lines by role instead of one flat color.
    """
    fig, ax = plt.subplots(figsize=(10, 5))
    group_colors = {}
    palette = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2"]

    for i, (sample_id, df) in enumerate(scan_dfs.items()):
        ms1 = df[df["ms_level"] == 1].sort_values("retention_time_min")
        group = color_by_group.get(sample_id) if color_by_group else None
        if group is not None:
            if group not in group_colors:
                group_colors[group] = palette[len(group_colors) % len(palette)]
            color = group_colors[group]
        else:
            color = palette[i % len(palette)]
        ax.plot(ms1["retention_time_min"], ms1["total_ion_current"], linewidth=0.6, alpha=0.7, color=color, label=group or sample_id)

    # Dedupe legend entries when grouping by role (avoid 3 identical "QC" labels)
    handles, labels = ax.get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    ax.legend(seen.values(), seen.keys(), fontsize=8)

    ax.set_xlabel("Retention time (min)")
    ax.set_ylabel("Total ion current")
    ax.set_title("TIC overlay — all samples")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def plot_bpc_overlay(scan_dfs: dict[str, pd.DataFrame], output_path: Path, color_by_group: dict[str, str] | None = None) -> None:
    """
    Overlays every sample's BPC on one figure, similar to TIC
    """
    fig, ax = plt.subplots(figsize=(10, 5))
    group_colors = {}
    palette = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2"]

    for i, (sample_id, df) in enumerate(scan_dfs.items()):
        ms1 = df[df["ms_level"] == 1].sort_values("retention_time_min")
        group = color_by_group.get(sample_id) if color_by_group else None
        if group is not None:
            if group not in group_colors:
                group_colors[group] = palette[len(group_colors) % len(palette)]
            color = group_colors[group]
        else:
            color = palette[i % len(palette)]
        ax.plot(ms1["retention_time_min"], ms1["base_peak_intensity"], linewidth=0.6, alpha=0.7, color=color, label=group or sample_id)

    # Dedupe legend entries when grouping by role (avoid 3 identical "QC" labels)
    handles, labels = ax.get_legend_handles_labels()
    seen = dict(zip(labels, handles))
    ax.legend(seen.values(), seen.keys(), fontsize=8)

    ax.set_xlabel("Retention time (min)")
    ax.set_ylabel("Base peak intensity  ")
    ax.set_title("BPC overlay — all samples")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

def compute_feature_rsd(table: pd.DataFrame, qc_sample_cols: list[str]) -> pd.Series:
    """
    Per-feature RSD% across QC replicate columns only. Features with all-NaN
    or single non-NaN QC values return NaN (can't compute variability from
    <2 points) -- these get dropped before plotting, not treated as 0% RSD.
    """
    qc_values = table[qc_sample_cols]
    means = qc_values.mean(axis=1, skipna=True)
    stds = qc_values.std(axis=1, skipna=True)
    n_valid = qc_values.notna().sum(axis=1)
    rsd = (stds / means * 100).where(n_valid >= 2)
    return rsd


def plot_rsd_distribution(rsd_values: pd.Series, threshold: float, output_path: Path) -> None:
    valid = rsd_values.dropna()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(valid, bins=50, color="#4C72B0", edgecolor="black")
    ax.axvline(threshold, color="red", linestyle="--", label=f"threshold ({threshold}%)")
    pct_above = (valid > threshold).sum() / len(valid) * 100
    ax.set_xlabel("RSD (%) across QC replicates")
    ax.set_ylabel("Feature count")
    ax.set_title(f"QC feature RSD distribution ({pct_above:.1f}% of features above threshold)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def prepare_pca_matrix(table: pd.DataFrame, sample_cols: list[str], min_presence_frac: float = 0.5) -> pd.DataFrame:
    """
    Builds a samples x features matrix ready for PCA: filters to features
    present in at least min_presence_frac of samples, imputes remaining
    gaps with half the minimum observed intensity (standard practice --
    avoids biasing toward 0, which would distort the log transform), then
    log2-transforms.
    """
    intensities = table[sample_cols]
    presence_frac = intensities.notna().sum(axis=1) / len(sample_cols)
    filtered = intensities[presence_frac >= min_presence_frac]

    global_min = filtered.min().min()
    imputed = filtered.fillna(global_min / 2)

    log_transformed = np.log2(imputed + 1)  # +1 guards against log(0) on any residual zero
    return log_transformed.T  # transpose: rows=samples, columns=features


def compute_pca_scores(matrix: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    scaled = StandardScaler().fit_transform(matrix)
    pca = PCA(n_components=2)
    scores = pca.fit_transform(scaled)
    scores_df = pd.DataFrame(scores, columns=["PC1", "PC2"], index=matrix.index)
    return scores_df, pca.explained_variance_ratio_


def plot_pca_scores(scores_df: pd.DataFrame, sample_groups: dict[str, str], explained_variance: np.ndarray, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 6))
    palette = {"QC": "#333333", "NSC": "#4C72B0", "T691": "#DD8452", "TUM6": "#55A868"}
    for group in scores_df.index.map(sample_groups).unique():
        mask = scores_df.index.map(sample_groups) == group
        ax.scatter(scores_df.loc[mask, "PC1"], scores_df.loc[mask, "PC2"],
                   label=group, color=palette.get(group, "#999999"), s=60, edgecolor="black")
    ax.set_xlabel(f"PC1 ({explained_variance[0]*100:.1f}% variance)")
    ax.set_ylabel(f"PC2 ({explained_variance[1]*100:.1f}% variance)")
    ax.set_title("PCA scores plot")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)