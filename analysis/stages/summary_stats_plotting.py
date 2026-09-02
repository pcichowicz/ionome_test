"""
Stage 12: Summary Stats Plotting (cohort_with_qc profile).

Reads the aligned/annotated feature table and produces cohort-scale
data-quality plots: RSD distribution (QC replicate reproducibility) and
a PCA scores plot (whole-dataset structure, QC clustering check).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

from analysis.context import LCMSContext
from analysis.pipeline import FatalStageError
from analysis.utils.constants import NON_SAMPLE_COLS
from analysis.utils.plotting import plot_rsd_distribution, plot_pca_scores, prepare_pca_matrix, compute_feature_rsd,compute_pca_scores

class SummaryStatsPlottingStage:
    """
    Stage 12: Summary Stats Plotting (cohort_with_qc profile)
    """
    _name = "summary_stats_plotting"

    def __init__(self, rsd_threshold: float = 20.0, min_presence_frac: float = 0.5):
        self.rsd_threshold = rsd_threshold
        self.min_presence_frac = min_presence_frac

    def _feature_table_path(self, context: LCMSContext) -> Path:
        annotated = context.featurejson_dir / f"{context.study_id}_annotated_features.parquet"
        aligned = context.featurejson_dir / f"{context.study_id}_aligned_features.parquet"
        return annotated if annotated.exists() else aligned

    def validate_input(self, context: LCMSContext) -> bool:
        if "feature_alignment" not in context.qc_metrics:
            raise FatalStageError("summary_stats_plotting: feature_alignment must run first")
        if not self._feature_table_path(context).exists():
            raise FatalStageError(f"summary_stats_plotting: no feature table found at {self._feature_table_path(context)}")
        if context.sample_metadata is None:
            raise FatalStageError("summary_stats_plotting: sample_metadata not loaded on context")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        table = pd.read_parquet(self._feature_table_path(context))
        sample_cols = [c for c in table.columns if c not in NON_SAMPLE_COLS]

        role_map = context.sample_metadata.set_index("sample_id")["sample_role"].to_dict()
        qc_sample_cols = [c for c in sample_cols if role_map.get(c) == "QC"]

        out_dir = context.plots_dir / "summary_stats"
        out_dir.mkdir(parents=True, exist_ok=True)

        warnings: list[str] = []

        # --- RSD ---
        if len(qc_sample_cols) < 2:
            warnings.append(f"summary_stats_plotting: only {len(qc_sample_cols)} QC sample(s) found, RSD skipped")
            rsd_result = {"n_features_scored": 0, "pct_above_threshold": None}
        else:
            rsd_values = compute_feature_rsd(table, qc_sample_cols)
            plot_rsd_distribution(rsd_values, self.rsd_threshold, out_dir / "rsd_distribution.png")
            valid = rsd_values.dropna()
            rsd_result = {
                "n_features_scored": int(len(valid)),
                "pct_above_threshold": float((valid.to_numpy() > self.rsd_threshold).mean() * 100) if len(valid) else None,
                "median_rsd": float(valid.median()) if len(valid) else None,
            }

        # --- PCA ---
        matrix = prepare_pca_matrix(table, sample_cols, self.min_presence_frac)
        if matrix.shape[1] < 2 or matrix.shape[0] < 3:
            warnings.append("summary_stats_plotting: not enough features/samples for PCA, skipped")
            pca_result = {"n_features_used": matrix.shape[1], "explained_variance": None}
        else:
            scores_df, explained_variance = compute_pca_scores(matrix)
            plot_pca_scores(scores_df, role_map, explained_variance, out_dir / "pca_scores.png")
            pca_result = {
                "n_features_used": int(matrix.shape[1]),
                "explained_variance_pc1": float(explained_variance[0]),
                "explained_variance_pc2": float(explained_variance[1]),
            }

        context.qc_metrics[self._name] = {"rsd": rsd_result, "pca": pca_result}
        context.log_step(
            self._name,
            parameters={"rsd_threshold": self.rsd_threshold,
                        "min_presence_frac": self.min_presence_frac},
            metrics=context.qc_metrics[self._name],
            warnings=warnings,
            input_files=[str(self._feature_table_path(context))],
            output_files=[str(p) for p in out_dir.glob("*.png")],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics