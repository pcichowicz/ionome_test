"""
Cohort-mode statistical/biological plot stages: volcano, heatmap+clustering,
PLS-DA, XIC.

Reuses prepare_pca_matrix()/compute_pca_scores() and reads directly from
context.final_feature_table
"""

from __future__ import annotations
import itertools
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analysis.pipeline import FatalStageError
from analysis.utils.plotting import prepare_pca_matrix
from analysis.utils.mzml_parsing import load_ms1_scans

def _biological_sample_cols(table: pd.DataFrame, sample_metadata: pd.DataFrame) -> list[str]:
    """
    QC excluded from all three stat plots. Sourced from sample_metadata rather than
    NON_SAMPLE_COLS, so it works regardless of what extra identification
    columns final_feature_table carries.
    """
    bio_ids = sample_metadata.loc[sample_metadata["sample_role"] != "QC", "sample_id"]
    return [c for c in bio_ids if c in table.columns]

def _role_map(sample_metadata: pd.DataFrame) -> dict:
    return sample_metadata.set_index("sample_id")["sample_role"].to_dict()

# --------------------------------------------------------------------------
# 1. Volcano plot
# --------------------------------------------------------------------------
def compute_volcano_stats(
    log2_matrix: pd.DataFrame,  # features x samples, from prepare_pca_matrix(...).T — already fully imputed, no NaNs
    raw_presence: pd.DataFrame,  # features x samples, boolean — notna() on the RAW pre-imputation table
    group_a_samples: list[str],
    group_b_samples: list[str],
    min_valid_per_group: int,
    fdr_threshold: float,
    fc_threshold: float,
) -> pd.DataFrame:
    results = []
    a_cols = [c for c in group_a_samples if c in log2_matrix.columns]
    b_cols = [c for c in group_b_samples if c in log2_matrix.columns]
    for feature_id, row in log2_matrix.iterrows():
        a_real_count = int(raw_presence.loc[feature_id, a_cols].sum())
        b_real_count = int(raw_presence.loc[feature_id, b_cols].sum())
        if a_real_count < min_valid_per_group or b_real_count < min_valid_per_group:
            continue
        a = row[a_cols]
        b = row[b_cols]
        log2_fc = a.mean() - b.mean()

        _, p_val = stats.ttest_ind(a, b, equal_var=False)
        results.append({"feature_id": feature_id, "log2_fc": log2_fc, "p_value": p_val})
    if not results:
        return pd.DataFrame(columns=["log2_fc", "p_value", "fdr", "significant"])
    df = pd.DataFrame(results).set_index("feature_id")
    df["fdr"] = multipletests(df["p_value"], method="fdr_bh")[1]
    df["significant"] = (df["fdr"] < fdr_threshold) & (df["log2_fc"].abs() > fc_threshold)
    return df

def plot_volcano(
    results_df: pd.DataFrame,
    comparison_name: str,
    fc_threshold: float,
    fdr_threshold: float,
    output_path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(6, 5))
    neg_log10_fdr = -np.log10(results_df["fdr"].clip(lower=1e-300))
    colors = np.where(results_df["significant"], "#C44E52", "#8C8C8C")
    ax.scatter(results_df["log2_fc"], neg_log10_fdr, s=8, c=colors, alpha=0.6, linewidths=0)
    ax.axhline(-np.log10(fdr_threshold), linestyle="--", linewidth=0.8, color="#4C72B0")
    ax.axvline(fc_threshold, linestyle="--", linewidth=0.8, color="#4C72B0")
    ax.axvline(-fc_threshold, linestyle="--", linewidth=0.8, color="#4C72B0")
    ax.set_xlabel("log2 fold change")
    ax.set_ylabel("-log10(FDR)")
    ax.set_title(f"Volcano — {comparison_name}")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

class VolcanoPlotStage:
    _name: str = "volcano_plot"

    def __init__(
        self,
        fc_threshold: float = 1.0,
        fdr_threshold: float = 0.05,
        min_valid_per_group: int = 2,  # out of n=3 replicates per cell line
        min_presence_frac: float = 0.5,  # passed through to prepare_pca_matrix
        comparisons: Optional[list[tuple[str, str]]] = None,
        exclude_samples: Optional[list[str]] = None,  # e.g. ["DKFZ_Haikum_Samples_TUM6_neg_rep_1"] for a sensitivity re-run
    ):
        self.fc_threshold = fc_threshold
        self.fdr_threshold = fdr_threshold
        self.min_valid_per_group = min_valid_per_group
        self.min_presence_frac = min_presence_frac
        self.comparisons = comparisons
        self.exclude_samples = exclude_samples or []

    def validate_input(self, context) -> bool:
        if "library_assembly" not in context.qc_metrics:
            raise FatalStageError("volcano_plot: library_assembly must run first")
        if context.final_feature_table is None:
            raise FatalStageError("volcano_plot: context.final_feature_table not set")
        if context.sample_metadata is None:
            raise FatalStageError("volcano_plot: sample_metadata not loaded on context")
        return True

    def _resolve_comparisons(self, role_map: dict) -> list[tuple[str, str]]:
        if self.comparisons is not None:
            return self.comparisons
        roles = sorted({r for r in role_map.values() if r != "QC"})
        return list(itertools.combinations(roles, 2))

    def execute(self, context):
        table = context.final_feature_table
        sample_cols = _biological_sample_cols(table, context.sample_metadata)
        if self.exclude_samples:
            sample_cols = [c for c in sample_cols if c not in self.exclude_samples]
        role_map = _role_map(context.sample_metadata)

        # prepare_pca_matrix returns samples x features (presence-frac
        # filtered, global-min/2 imputed, log2(x+1)) — transpose back to
        # features x samples for the per-feature loop below
        log2_matrix = prepare_pca_matrix(table, sample_cols, self.min_presence_frac).T
        # raw (pre-imputation) presence, reindexed to the features that
        # survived prepare_pca_matrix's presence-frac filter — this is
        # what min_valid_per_group actually checks against, NOT log2_matrix
        raw_presence = table[sample_cols].notna().reindex(log2_matrix.index)

        out_dir = context.plots_dir / "volcano"
        if self.exclude_samples:
            out_dir = out_dir / "sensitivity_excl"
        out_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        comparisons = self._resolve_comparisons(role_map)
        metrics = {}
        output_files = []
        significant_features = {}  # comparison_name -> list of feature_ids, for downstream stages (XIC)

        for group_a, group_b in comparisons:
            comparison_name = f"{group_a}_vs_{group_b}"
            a_samples = [c for c in sample_cols if role_map.get(c) == group_a]
            b_samples = [c for c in sample_cols if role_map.get(c) == group_b]
            if len(a_samples) < self.min_valid_per_group or len(b_samples) < self.min_valid_per_group:
                warnings.append(f"volcano_plot: skipped {comparison_name}, insufficient replicates")
                continue
            results_df = compute_volcano_stats(
                log2_matrix, raw_presence, a_samples, b_samples,
                self.min_valid_per_group, self.fdr_threshold, self.fc_threshold,
            )
            plot_path = out_dir / f"volcano_{comparison_name}.png"
            plot_volcano(results_df, comparison_name, self.fc_threshold, self.fdr_threshold, plot_path)
            output_files.append(str(plot_path))
            # Full results (all tested features, not just significant ones)
            # to CSV -- lets you re-slice by a different threshold or just
            # eyeball the data without rerunning the stage or touching plot code
            csv_path = out_dir / f"volcano_{comparison_name}.csv"
            results_df.to_csv(csv_path, index_label="feature_id")
            output_files.append(str(csv_path))
            sig_ids = results_df[results_df["significant"]].index.tolist() if len(results_df) else []
            metrics[comparison_name] = {
                "n_features_tested": int(len(results_df)),
                "n_significant": len(sig_ids),
                # Actual feature IDs, not just the count -- kept in qc_metrics
                # (not just the context.volcano_significant_features attribute
                # below) specifically so this survives into whatever final
                # export/report aggregates context.qc_metrics. The attribute
                # is still set for same-run in-process consumers (XICPlottingStage).
                "significant_feature_ids": sig_ids,
            }
            if sig_ids:
                significant_features[comparison_name] = sig_ids

        context.qc_metrics["volcano_plot"] = metrics
        # Full significant-feature IDs per comparison, kept separately from
        # qc_metrics's small summary dict — this is what XICPlottingStage
        # (and anything else downstream) reads to know WHICH features to
        # follow up on, not just how many.
        context.volcano_significant_features = significant_features
        context.log_step(
            self._name,
            parameters={
                "fc_threshold": self.fc_threshold,
                "fdr_threshold": self.fdr_threshold,
                "min_valid_per_group": self.min_valid_per_group,
                "min_presence_frac": self.min_presence_frac,
            },
            metrics=metrics,
            warnings=warnings,
            input_files=[],  # source is in-memory context.final_feature_table, not a file -- export (which writes it to disk) now runs AFTER these stages
            output_files=output_files,
        )
        return context

    def validate_output(self, context) -> bool:
        return self._name in context.qc_metrics


# --------------------------------------------------------------------------
# 2. Heatmap with clustering
# --------------------------------------------------------------------------
class HeatmapClusteringStage:
    _name = "heatmap_clustering"

    def __init__(
        self,
        n_features: int = 75,
        restrict_to_matched: bool = True,
        linkage_method: str = "average",
        distance_metric: str = "correlation",
        min_presence_frac: float = 0.5,
    ):
        self.n_features = n_features
        self.restrict_to_matched = restrict_to_matched
        self.linkage_method = linkage_method
        self.distance_metric = distance_metric
        self.min_presence_frac = min_presence_frac

    def validate_input(self, context) -> bool:
        if "library_assembly" not in context.qc_metrics:
            raise FatalStageError("heatmap_clustering: library_assembly must run first")
        if context.final_feature_table is None:
            raise FatalStageError("heatmap_clustering: context.final_feature_table not set")
        if context.sample_metadata is None:
            raise FatalStageError("heatmap_clustering: sample_metadata not loaded on context")
        return True

    def execute(self, context):
        table = context.final_feature_table
        role_map = _role_map(context.sample_metadata)
        bio_sample_cols = _biological_sample_cols(table, context.sample_metadata)

        warnings: list[str] = []
        candidates = table
        used_matched_only = False
        if self.restrict_to_matched and "compound_name" in table.columns:
            candidates = table[table["compound_name"].notna()]
            used_matched_only = True
            if candidates.empty:
                warnings.append("heatmap_clustering: no matched features found, falling back to all features")
                candidates = table

        log2_matrix = prepare_pca_matrix(candidates, bio_sample_cols, self.min_presence_frac).T
        n_features = min(self.n_features, len(log2_matrix))
        top_ids = log2_matrix.var(axis=1).sort_values(ascending=False).head(n_features).index
        top_matrix = log2_matrix.loc[top_ids]

        z_matrix = top_matrix.sub(top_matrix.mean(axis=1), axis=0).div(top_matrix.std(axis=1), axis=0)

        out_dir = context.plots_dir / "heatmap_clustering"
        out_dir.mkdir(parents=True, exist_ok=True)
        plot_path = out_dir / "heatmap_clustered.png"

        row_labels = None
        if used_matched_only and "compound_name" in candidates.columns:
            row_labels = candidates.set_index(candidates.index).loc[top_ids, "compound_name"]

        role_colors = {"NSC": "#55A868", "T691": "#C44E52", "TUM6": "#8172B2"}
        col_colors = pd.Series(
            [role_colors.get(role_map.get(c), "#8C8C8C") for c in bio_sample_cols],
            index=bio_sample_cols,
        )

        cg = sns.clustermap(
            z_matrix,
            row_cluster=True,
            col_cluster=True,
            method=self.linkage_method,
            metric=self.distance_metric,
            col_colors=col_colors,
            yticklabels=row_labels if row_labels is not None else False,
            cmap="vlag",
            figsize=(8, max(6, n_features * 0.12)),
        )
        cg.savefig(plot_path, dpi=150)
        plt.close(cg.figure)

        # z-scored matrix, reordered to match the dendrogram's visual
        # clustering order, with compound_name attached when available --
        # lets you re-inspect exactly what was plotted without rerunning
        # clustering or touching plot code
        row_order = z_matrix.index[cg.dendrogram_row.reordered_ind]
        col_order = z_matrix.columns[cg.dendrogram_col.reordered_ind]
        csv_matrix = z_matrix.loc[row_order, col_order].copy()
        if row_labels is not None:
            csv_matrix.insert(0, "compound_name", row_labels.reindex(row_order))
        csv_path = out_dir / "heatmap_z_matrix.csv"
        csv_matrix.to_csv(csv_path, index_label="feature_id")

        metrics = {
            "n_features_used": int(len(top_matrix)),
            "used_matched_only": used_matched_only,
        }
        context.qc_metrics["heatmap_clustering"] = metrics
        context.log_step(
            self._name,
            parameters={
                "n_features": self.n_features,
                "restrict_to_matched": self.restrict_to_matched,
                "linkage_method": self.linkage_method,
                "distance_metric": self.distance_metric,
                "min_presence_frac": self.min_presence_frac,
            },
            metrics=metrics,
            warnings=warnings,
            input_files=[],  # source is in-memory context.final_feature_table, not a file -- export (which writes it to disk) now runs AFTER these stages
            output_files=[str(plot_path), str(csv_path)],
        )
        return context

    def validate_output(self, context) -> bool:
        return self._name in context.qc_metrics

# --------------------------------------------------------------------------
# 3. PLS-DA
# --------------------------------------------------------------------------
def _vip_scores(pls, x: np.ndarray) -> np.ndarray:
    t = pls.x_scores_
    w = pls.x_weights_
    q = pls.y_loadings_
    p, h = w.shape
    vips = np.zeros((p,))
    s = np.diag(t.T @ t @ q.T @ q)  # shape (h,) — variance explained per component
    total_s = np.sum(s)
    for i in range(p):
        weight = np.array([(w[i, j] / np.linalg.norm(w[:, j])) ** 2 for j in range(h)])
        vips[i] = np.sqrt(p * (weight @ s) / total_s)
    return vips

def plot_plsda_scores(scores: np.ndarray, labels: pd.Series, output_path: Path) -> None:
    role_colors = {"NSC": "#55A868", "T691": "#C44E52", "TUM6": "#8172B2"}
    fig, ax = plt.subplots(figsize=(6, 5))
    for role in labels.unique():
        mask = (labels == role).values
        ax.scatter(scores[mask, 0], scores[mask, 1], label=role, color=role_colors.get(role, "#8C8C8C"), s=40)
    ax.set_xlabel("Component 1")
    ax.set_ylabel("Component 2")
    ax.set_title("PLS-DA scores")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

class PLSDAStage:
    _name = "plsda"

    def __init__(self, n_components: int = 2, n_permutations: int = 999, min_presence_frac: float = 0.5):
        self.n_components = n_components
        self.n_permutations = n_permutations
        self.min_presence_frac = min_presence_frac

    def validate_input(self, context) -> bool:
        if "library_assembly" not in context.qc_metrics:
            raise FatalStageError("plsda: library_assembly must run first")
        if context.final_feature_table is None:
            raise FatalStageError("plsda: context.final_feature_table not set")
        if context.sample_metadata is None:
            raise FatalStageError("plsda: sample_metadata not loaded on context")
        return True

    def execute(self, context):
        from sklearn.cross_decomposition import PLSRegression
        from sklearn.preprocessing import StandardScaler, LabelBinarizer
        from sklearn.model_selection import LeaveOneOut

        table = context.final_feature_table
        role_map = _role_map(context.sample_metadata)
        bio_sample_cols = _biological_sample_cols(table, context.sample_metadata)

        log2_matrix = prepare_pca_matrix(table, bio_sample_cols, self.min_presence_frac)  # samples x features
        labels = pd.Series([role_map[c] for c in log2_matrix.index], index=log2_matrix.index)

        x = StandardScaler().fit_transform(log2_matrix.values)
        y = LabelBinarizer().fit_transform(labels.values)

        pls = PLSRegression(n_components=self.n_components)
        pls.fit(x, y)
        vip = _vip_scores(pls, x)

        # Leave-one-out CV — cheap at n=9, and the actual bar for "is this
        # separation real" rather than eyeballing the score plot
        loo = LeaveOneOut()
        correct = 0
        for train_idx, test_idx in loo.split(x):
            fold_pls = PLSRegression(n_components=self.n_components)
            fold_pls.fit(x[train_idx], y[train_idx])
            pred = fold_pls.predict(x[test_idx])
            correct += int(np.argmax(y[test_idx]) == np.argmax(pred))
        loo_accuracy = correct / len(x)

        perm_p_value = None
        if self.n_permutations > 0:
            rng = np.random.default_rng()
            real_score = pls.score(x, y)
            perm_scores = []
            for _ in range(self.n_permutations):
                shuffled_y = y[rng.permutation(len(y))]
                perm_pls = PLSRegression(n_components=self.n_components)
                perm_pls.fit(x, shuffled_y)
                perm_scores.append(perm_pls.score(x, shuffled_y))
            perm_p_value = float(np.mean(np.array(perm_scores) >= real_score))

        out_dir = context.plots_dir / "plsda"
        out_dir.mkdir(parents=True, exist_ok=True)
        plot_path = out_dir / "plsda_scores.png"
        plot_plsda_scores(pls.x_scores_, labels, plot_path)

        # Score-plot coordinates (sample_id, role, component values) to CSV
        scores_csv_path = out_dir / "plsda_scores.csv"
        scores_df = pd.DataFrame(
            pls.x_scores_,
            index=log2_matrix.index,
            columns=[f"component_{i+1}" for i in range(self.n_components)],
        )
        scores_df.insert(0, "sample_role", labels)
        scores_df.to_csv(scores_csv_path, index_label="sample_id")

        # VIP scores to CSV
        vip_series = pd.Series(vip, index=log2_matrix.columns, name="vip_score").sort_values(ascending=False)
        vip_csv_path = out_dir / "plsda_vip_scores.csv"
        vip_series.to_csv(vip_csv_path, index_label="feature_id")

        metrics = {
            "loo_accuracy": float(loo_accuracy),
            "permutation_p_value": perm_p_value,
            "n_components": self.n_components,
        }
        context.qc_metrics["plsda"] = metrics
        # Still kept as a full Series on context too, for same-run
        # in-process consumers (e.g. cross-referencing against
        # VolcanoPlotStage's significant features) -- the CSV above is
        # what makes it durable past this run.
        context.vip_scores = vip_series

        context.log_step(
            self._name,
            parameters={
                "n_components": self.n_components,
                "n_permutations": self.n_permutations,
                "min_presence_frac": self.min_presence_frac,
            },
            metrics=metrics,
            warnings=[],
            input_files=[],  # source is in-memory context.final_feature_table, not a file -- export (which writes it to disk) now runs AFTER these stages
            output_files=[str(plot_path), str(scores_csv_path), str(vip_csv_path)],
        )
        return context

    def validate_output(self, context) -> bool:
        return self._name in context.qc_metrics

# --------------------------------------------------------------------------
# 4. XIC plots (verification plots for volcano-significant features)
# --------------------------------------------------------------------------

def _find_raw_file(mzml_dir: Path, sample_id: str) -> Optional[Path]:
    """
    GUESS — replace with the real _find_raw_file if its signature differs.
    sample_metadata's sample_id values already look like literal file
    basenames (e.g. "DKFZ_Haikum_Samples_NSC_neg_rep_1"), so this tries
    both extensions directly under context.mzml_dir.
    """
    for suffix in (".mzXML", ".mzML"):
        candidate = mzml_dir / f"{sample_id}{suffix}"
        if candidate.exists():
            return candidate
    return None

def _normalize_rt_to_minutes(rt_values: np.ndarray, expected_gradient_min: float = 20.0) -> np.ndarray:
    """
    _load_ms1_scans' field is named rt_sec, but mzXML retentionTime was
    separately confirmed (via pyteomics unit_info, cross-checked against
    the real 16-min gradient) to already parse to minutes -- the naming
    is inconsistent with that finding. Auto-detect instead of assuming:
    if the max RT looks like seconds (>> expected gradient in minutes),
    convert; otherwise assume it's already in minutes.
    """
    if len(rt_values) == 0:
        return rt_values
    if np.nanmax(rt_values) > expected_gradient_min * 3:  # generous margin
        return rt_values / 60.0
    return rt_values


def _extract_xic(
    scans: list[dict],
    target_mz: float,
    mz_tolerance_ppm: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    scans: list of {"rt": <auto-detected units>, "mz": array, "intensity": array}
    from _load_ms1_scans. Returns (rt_minutes, summed_intensity) arrays,
    one point per scan, summing all peaks within the ppm window per scan.
    """
    window = target_mz * mz_tolerance_ppm / 1e6
    rt_raw = np.array([s["rt"] for s in scans], dtype=float)
    rt_min = _normalize_rt_to_minutes(rt_raw)

    intensities = np.zeros(len(scans))
    for i, s in enumerate(scans):
        mz_arr = s["mz"]
        if mz_arr.size == 0:
            continue
        mask = np.abs(mz_arr - target_mz) <= window
        if mask.any():
            intensities[i] = s["intensity"][mask].sum()

    order = np.argsort(rt_min)
    return rt_min[order], intensities[order]

def plot_xic_overlay(
    xic_by_sample: dict[str, tuple[np.ndarray, np.ndarray]],
    role_map: dict,
    feature_label: str,
    target_rt_min: float,
    rt_window_min: float,
    output_path: Path,
) -> None:
    role_colors = {"QC": "#8C8C8C", "NSC": "#55A868", "T691": "#C44E52", "TUM6": "#8172B2"}
    fig, ax = plt.subplots(figsize=(8, 4.5))
    seen_roles = set()
    xlim_lo, xlim_hi = target_rt_min - rt_window_min, target_rt_min + rt_window_min
    visible_max = 0.0
    for sample_id, (rt_min, intensity) in xic_by_sample.items():
        role = role_map.get(sample_id, "unknown")
        color = role_colors.get(role, "#4C72B0")
        label = role if role not in seen_roles else None
        seen_roles.add(role)
        ax.plot(rt_min, intensity, linewidth=0.9, alpha=0.8, color=color, label=label)
        # Only consider points inside the visible window for y-autoscale --
        # otherwise a misaligned target_rt  (seconds/minutes bug)
        # produces a misleadingly huge y-scale with an apparently-empty
        # plot, instead of an obviously-empty plot at a sane scale.
        in_window = (rt_min >= xlim_lo) & (rt_min <= xlim_hi)
        if in_window.any():
            visible_max = max(visible_max, float(intensity[in_window].max()))
    ax.axvline(target_rt_min, linestyle="--", linewidth=0.8, color="black", alpha=0.5)
    ax.set_xlim(xlim_lo, xlim_hi)
    ax.set_ylim(0, visible_max * 1.1 if visible_max > 0 else 1.0)
    ax.set_xlabel("Retention time (min)")
    ax.set_ylabel("Extracted ion intensity")
    ax.set_title(f"XIC — {feature_label}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

class XICPlottingStage:
    """
    Verification plots for volcano-significant features: does the feature
    correspond to a real, clean chromatographic peak, or could it be a
    misalignment/noise artifact? Labeled with compound_name when the
    feature also has a library match, otherwise by mz/rt.

    Scope is deliberately volcano-significant features only, not the full
    set of high-confidence library matches: verifying a specific biological CLAIM
    (this feature differs between groups), not a general library-match gallery.
    """

    _name = "xic_plotting"

    def __init__(
        self,
        mz_tolerance_ppm: float = 10.0,  # matches feature_alignment's mz_tolerance_ppm
        rt_window_min: float = 1.0,  # +/- window around the feature's own RT
        include_qc: bool = True,  # QC presence/absence is itself informative
    ):
        self.mz_tolerance_ppm = mz_tolerance_ppm
        self.rt_window_min = rt_window_min
        self.include_qc = include_qc

    def validate_input(self, context) -> bool:
        if "volcano_plot" not in context.qc_metrics:
            raise FatalStageError("xic_plotting: volcano_plot must run first")
        if not getattr(context, "volcano_significant_features", None):
            # Not fatal -- just means nothing to plot (e.g. all comparisons had 0 hits)
            return True
        if context.final_feature_table is None:
            raise FatalStageError("xic_plotting: context.final_feature_table not set")
        if context.sample_metadata is None:
            raise FatalStageError("xic_plotting: sample_metadata not loaded on context")
        return True

    def execute(self, context):
        significant_by_comparison = getattr(context, "volcano_significant_features", {}) or {}
        table = context.final_feature_table
        role_map = _role_map(context.sample_metadata)

        sample_ids = context.sample_metadata["sample_id"].tolist()
        if not self.include_qc:
            sample_ids = [s for s in sample_ids if role_map.get(s) != "QC"]

        out_dir = context.plots_dir / "xic"
        out_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []
        output_files = []
        plotted_features = []

        # Union of all significant feature_ids across comparisons, so a
        # feature significant in multiple comparisons only gets one XIC,
        # not a duplicate per comparison
        all_significant_ids = sorted({fid for ids in significant_by_comparison.values() for fid in ids})

        if not all_significant_ids:
            warnings.append("xic_plotting: no volcano-significant features found across any comparison")
            context.qc_metrics["xic_plotting"] = {"n_features_plotted": 0}
            context.log_step(
                self.name, parameters={"mz_tolerance_ppm": self.mz_tolerance_ppm, "rt_window_min": self.rt_window_min},
                metrics=context.qc_metrics["xic_plotting"], warnings=warnings, input_files=[], output_files=[],
            )
            return context

        # Load raw MS1 scans ONCE per sample (not once per feature)
        # loading is the expensive part, and a sample's scans get reused
        # across every feature we plot
        scans_by_sample: dict[str, list[dict]] = {}
        for sample_id in sample_ids:
            raw_path = _find_raw_file(context.mzml_dir, sample_id)
            if raw_path is None:
                warnings.append(f"xic_plotting: no raw file found for {sample_id}, skipped")
                continue
            scans_by_sample[sample_id] = load_ms1_scans(raw_path)

        for feature_id in all_significant_ids:
            if feature_id not in table.index:
                warnings.append(f"xic_plotting: {feature_id} not found in final_feature_table, skipped")
                continue
            row = table.loc[feature_id]
            target_mz = float(row["mz"])
            # final_feature_table's rt column is in SECONDS (feature_alignment's
            # rt_tolerance_sec is applied to it directly, unconverted) -- a
            # DIFFERENT object from the raw scan rt (confirmed in minutes).
            # Reuse the same auto-detect heuristic rather than a blind /60,
            # in case some other table variant already stores minutes.
            target_rt_min = float(_normalize_rt_to_minutes(np.array([float(row["rt"])]))[0])
            compound_name = row.get("compound_name") if hasattr(row, "get") else None
            feature_label = compound_name if pd.notna(compound_name) else f"{feature_id} (mz {target_mz:.4f}, rt {target_rt_min:.2f} min)"

            xic_by_sample = {}
            for sample_id, scans in scans_by_sample.items():
                xic_by_sample[sample_id] = _extract_xic(scans, target_mz, self.mz_tolerance_ppm)

            safe_name = feature_id if pd.isna(compound_name) else f"{feature_id}_{str(compound_name).replace(' ', '_')}"
            plot_path = out_dir / f"xic_{safe_name}.png"
            plot_xic_overlay(xic_by_sample, role_map, feature_label, target_rt_min, self.rt_window_min, plot_path)
            output_files.append(str(plot_path))

            # Raw XIC trace per sample to CSV. Long format (not one column
            # per sample) since each sample's own scan RTs differ slightly
            # long format avoids forcing them onto a shared RT grid.
            xic_rows = []
            for sample_id, (rt_min, intensity) in xic_by_sample.items():
                xic_rows.append(pd.DataFrame({
                    "sample_id": sample_id,
                    "sample_role": role_map.get(sample_id, "unknown"),
                    "rt_min": rt_min,
                    "intensity": intensity,
                }))
            xic_csv_path = out_dir / f"xic_{safe_name}.csv"
            if xic_rows:
                pd.concat(xic_rows, ignore_index=True).to_csv(xic_csv_path, index=False)
                output_files.append(str(xic_csv_path))

            plotted_features.append({
                "feature_id": feature_id,
                "compound_name": compound_name if pd.notna(compound_name) else None,
                "comparisons": [c for c, ids in significant_by_comparison.items() if feature_id in ids],
            })

        metrics = {"n_features_plotted": len(plotted_features),
                   "features": plotted_features}
        context.qc_metrics["xic_plotting"] = metrics
        context.log_step(
            self._name,
            parameters={
                "mz_tolerance_ppm": self.mz_tolerance_ppm,
                "rt_window_min": self.rt_window_min,
                "include_qc": self.include_qc,
            },
            metrics=metrics,
            warnings=warnings,
            input_files=[],  # source is in-memory context.final_feature_table, not a file -- export (which writes it to disk) now runs AFTER these stages
            output_files=output_files,
        )
        return context

    def validate_output(self, context) -> bool:
        return self._name in context.qc_metrics