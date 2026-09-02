"""
Stage 2: Scan Summary

Parses each raw mzML file once, writes a per-sample parquet with scan-level
summary columns (RT, TIC, base peak, precursor m/z).
Downstream chromatogram plotting reads these parquet files instead of reparsing mzML.
Runs right after ingestion -- only needs context.mzml_file_paths, nothing
computed by any other stage.
"""
from analysis.context import LCMSContext
from analysis.utils.scan_summary import extract_scan_summary

class ScanSummaryCacheStage:
    """
    Stage 2: Scan_Summary
    """
    _name:str = "scan_summary_cache"

    def validate_input(self, context: LCMSContext) -> bool:
        return bool(context.mzml_file_paths)

    def execute(self, context: LCMSContext) -> LCMSContext:
        out_dir = context.cache_dir / "scan_summary"
        out_dir.mkdir(parents=True, exist_ok=True)

        n_processed, n_skipped = 0, 0
        for mzml_path in context.mzml_file_paths:
            sample_id = mzml_path.stem
            out_path = out_dir / f"{sample_id}.parquet"
            if out_path.exists():
                n_skipped += 1
                continue
            df = extract_scan_summary(mzml_path)
            df.to_parquet(out_path)
            n_processed += 1

        context.qc_metrics[f"{self._name}"] = {
            "n_processed": n_processed,
            "n_skipped": n_skipped,
        }
        context.log_step(
            self._name,
            parameters={},
            metrics={"n_processed": n_processed,
                     "n_skipped": n_skipped},
            input_files=[str(p) for p in context.mzml_file_paths],
            output_files=[str(out_dir / f"{p.stem}.parquet") for p in context.mzml_file_paths],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics