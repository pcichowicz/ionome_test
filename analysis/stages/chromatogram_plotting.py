"""
Stage 3: Chromatogram_Plotting
Reads cached scan-summary parquet files, no mzML reparsing.
Produces one TIC + one BPC plot per sample.
Must run after scan_summary_cache.
"""
import pandas as pd

from analysis.context import LCMSContext
from analysis.utils.plotting import plot_tic, plot_bpc, plot_tic_overlay, plot_bpc_overlay


class ChromatogramPlottingStage:
    """
    Stage 3: Chromatogram_Plotting
    """
    _name: str = "chromatogram_plotting"

    def validate_input(self, context: LCMSContext) -> bool:
        cache_dir = context.cache_dir / "scan_summary"
        return cache_dir.exists() and any(cache_dir.glob("*.parquet"))

    def execute(self, context: LCMSContext) -> LCMSContext:
        cache_dir = context.cache_dir / "scan_summary"
        out_dir = context.plots_dir / "chromatograms"
        out_dir.mkdir(parents=True, exist_ok=True)

        scan_dfs = {}
        n_processed = 0
        for parquet_path in cache_dir.glob("*.parquet"):
            sample_id = parquet_path.stem
            df = pd.read_parquet(parquet_path)
            scan_dfs[sample_id] = df

            plot_tic(df, sample_id, out_dir / f"{sample_id}_tic.png")
            plot_bpc(df, sample_id, out_dir / f"{sample_id}_bpc.png")
            n_processed += 1

        # Cohort-scale overlay, in addition to per-sample plots
        sample_metadata = context.sample_metadata.set_index("sample_id")[
            "sample_role"].to_dict() if context.sample_metadata is not None else None
        plot_tic_overlay(scan_dfs, out_dir / "overlay_tic.png", color_by_group=sample_metadata)
        plot_bpc_overlay(scan_dfs, out_dir / "overlay_bpc.png", color_by_group=sample_metadata)

        context.qc_metrics[f"{self._name}"] = {"n_samples_plotted": n_processed}
        context.log_step(
            self._name,
            parameters={},
            metrics={"n_samples_plotted": n_processed},
            input_files=[str(p) for p in cache_dir.glob("*.parquet")],
            output_files=[str(p) for p in out_dir.glob("*.png")],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics