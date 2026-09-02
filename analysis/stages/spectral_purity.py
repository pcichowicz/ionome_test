"""
Stage 9: Spectral Purity (standards_only profile)

For every compound confirmed in Stage 2 (system suitability), checks how
"clean" its precursor isolation was -- i.e. whether something else
co-eluted and contaminated the MS/MS spectrum.
"""
from __future__ import annotations
import statistics

from analysis.context import LCMSContext
from analysis.pipeline import FatalStageError
from analysis.utils.mzml_parsing import PyteomicsSpectralPurityReader
from analysis.utils.spectral_purity import classify_purity

class SpectralPurityStage:
    """
    Stage 9: Spectral Purity (standards_only profile)
    """
    _name: str = "spectral_purity"

    def __init__(
        self,
        reader: PyteomicsSpectralPurityReader,
        isolation_window_da: float = 1.0,
        min_purity: float = 0.7,
    ):
        self.reader = reader
        self.isolation_window_da = isolation_window_da
        self.min_purity = min_purity

    def validate_input(self, context: LCMSContext) -> bool:
        if context.mzml_dir is None:
            raise FatalStageError("spectral_purity: mzml_directory not set")
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("spectral_purity: system_suitability must run first")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        ss_results = context.qc_metrics["system_suitability"]["results"]
        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_attempted = 0
        n_computed = 0
        n_below_threshold = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                results[sample_id] = {"status": "skipped_no_confirmed_matches"}
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            sample_purities = []

            for match in confirmed_matches:
                n_attempted += 1
                purity = self.reader.compute_precursor_purity(
                    mzml_path, match["matched_mz"], self.isolation_window_da
                )
                status = classify_purity(purity, self.min_purity)

                if purity is not None:
                    n_computed += 1
                    if status == "below_threshold":
                        n_below_threshold += 1
                        warnings.append(
                            f"{sample_id}: purity {purity:.2f} for "
                            f"{match['compound']!r} below threshold {self.min_purity}"
                        )
                else:
                    warnings.append(
                        f"{sample_id}: could not compute purity for {match['compound']!r}"
                    )

                sample_purities.append(
                    {
                    "compound": match["compound"],
                    "mz": match["matched_mz"],
                    "purity": purity,
                    "status": status,
                    }
                )

            results[sample_id] = {"status": "checked", "purities": sample_purities}

        if n_attempted > 0 and n_computed == 0:
            raise FatalStageError(
                "spectral_purity: could not compute purity for any confirmed match "
                "across the whole run -- likely no MS2 spectra present, not a "
                "single-compound problem"
            )

        all_purities = [
            p["purity"]
            for r in results.values()
            if r.get("status") == "checked"
            for p in r["purities"]
            if p["purity"] is not None
        ]
        median_purity = statistics.median(all_purities) if all_purities else None

        context.qc_metrics[self._name] = {
            "results": results,
            "n_attempted": n_attempted,
            "n_computed": n_computed,
            "n_below_threshold": n_below_threshold,
            "median_purity": median_purity,
        }
        context.log_step(
            self._name,
            parameters={
                "isolation_window_da": self.isolation_window_da,
                "min_purity": self.min_purity,
            },
            metrics={
                "n_attempted": n_attempted,
                "n_computed": n_computed,
                "n_below_threshold": n_below_threshold,
            },
            warnings=warnings,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics