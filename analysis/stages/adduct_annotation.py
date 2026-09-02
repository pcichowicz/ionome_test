"""
Stage 8: Adduct Annotation

(standards_only profile)
AdductAnnotationStage

Looks for additional corroborating adducts once Stage 2 has already
confirmed the primary one.


(cohort_with_qc profile)
CohortAdductAnnotationStage

Cross-sample version: infers adduct/isotope/dimer relationships directly
from the aligned feature table (mass-delta + RT co-elution + intensity
correlation across samples), rather than confirming known compounds via
system_suitability first. Replaces the standards_only per-sample logic
in the sibling standards-only stage class.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

from analysis.utils.adducts import compute_adduct_mz, compute_neutral_mass
from analysis.context import LCMSContext
from analysis.utils.protocols import PrecursorReader
from analysis.pipeline import FatalStageError
from analysis.stages.system_suitability import find_best_match
from core.ingestion import find_raw_file
from analysis.utils.adducts import annotate_adducts, NEGATIVE_ADDUCTS, AdductDef
from analysis.utils.cache_utils import load_filehash_cache, save_filehash_cache, hash_file, compute_cache_key

CACHE_SCHEMA_VERSION = "v1"

class AdductAnnotationStage:
    """
    Stage 8: Adduct Annotation (standards_only profile)
    """
    _name: str = "adduct_annotation"

    def __init__(
        self,
        reader: PrecursorReader,
        candidate_adducts: list[str],
        primary_adduct: str = "[M-H]-",
        ppm_tolerance: float = 5.0,
    ):
        self.reader = reader
        self.candidate_adducts = candidate_adducts
        self.primary_adduct = primary_adduct
        self.ppm_tolerance = ppm_tolerance

    def validate_input(self, context: LCMSContext) -> bool:
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("adduct_annotation: system_suitability must run first")
        if context.mzml_dir is None:
            raise FatalStageError("adduct_annotation: mzml_directory not set")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        ss_results = context.qc_metrics["system_suitability"]["results"]
        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_compounds_checked = 0
        n_with_extra_adducts = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                continue

            mzml_path = find_raw_file(context.mzml_dir, sample_id)
            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML missing, adduct annotation skipped")
                continue

            observed_mzs = self.reader.get_precursor_mzs(mzml_path)
            compounds = []

            for match in confirmed_matches:
                n_compounds_checked += 1
                neutral_mass = compute_neutral_mass(match["matched_mz"], self.primary_adduct)

                adducts_detected = [
                    {
                    "adduct": self.primary_adduct,
                    "mz": match["matched_mz"],
                    "mass_error_ppm": match["mass_error_ppm"],
                    }
                ]

                for adduct in self.candidate_adducts:
                    if adduct == self.primary_adduct:
                        continue
                    expected_mz = compute_adduct_mz(neutral_mass, adduct)
                    found = find_best_match(expected_mz, observed_mzs, self.ppm_tolerance)
                    if found is not None:
                        matched_mz, ppm_error = found
                        adducts_detected.append(
                            {"adduct": adduct, "mz": matched_mz,
                             "mass_error_ppm": ppm_error}
                        )

                if len(adducts_detected) > 1:
                    n_with_extra_adducts += 1

                compounds.append(
                    {
                    "compound": match["compound"],
                    "neutral_mass_estimate": neutral_mass,
                    "adducts_detected": adducts_detected,
                    }
                )

            results[sample_id] = {"status": "checked", "compounds": compounds}

        context.qc_metrics[self._name] = {
            "results": results,
            "n_compounds_checked": n_compounds_checked,
            "n_with_extra_adducts": n_with_extra_adducts,
        }
        context.log_step(
            self._name,
            parameters={"candidate_adducts": self.candidate_adducts,
                        "ppm_tolerance": self.ppm_tolerance},
            metrics={"n_compounds_checked": n_compounds_checked,
                     "n_with_extra_adducts": n_with_extra_adducts},
            warnings=warnings,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return "adduct_annotation" in context.qc_metrics

class CohortAdductAnnotationStage:
    """
    Stage 8: Adduct Annotation (cohort_with_qc profile).
    """
    _name: str = "adduct_annotation"

    def __init__(
        self,
        mz_tolerance_ppm: float = 10.0,
        rt_tolerance_sec: float = 15.0,
        correlation_threshold: float = 0.75,
        adduct_table: list[AdductDef] = NEGATIVE_ADDUCTS,
    ):
        self.mz_tolerance_ppm = mz_tolerance_ppm
        self.rt_tolerance_sec = rt_tolerance_sec
        self.correlation_threshold = correlation_threshold
        self.adduct_table = adduct_table

    def _aligned_path(self, context: LCMSContext) -> Path:
        return context.featurejson_dir / f"{context.study_id}_aligned_features.parquet"

    def _annotated_path(self, context: LCMSContext) -> Path:
        return context.featurejson_dir / f"{context.study_id}_annotated_features.parquet"

    def cache_key(self, context: LCMSContext) -> str:
        hash_cache = load_filehash_cache(context.cache_dir)
        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "mz_tolerance_ppm": self.mz_tolerance_ppm,
            "rt_tolerance_sec": self.rt_tolerance_sec,
            "correlation_threshold": self.correlation_threshold,
            "adduct_table": [(a.name, a.mass_shift, a.multiplier) for a in self.adduct_table],
            "aligned_features_hash": hash_file(self._aligned_path(context), hash_cache),
        }
        save_filehash_cache(context.cache_dir, hash_cache)
        return compute_cache_key(payload)

    def validate_input(self, context: LCMSContext) -> bool:
        if "feature_alignment" not in context.qc_metrics:
            raise FatalStageError("adduct_annotation: feature_alignment must run first")
        if not self._aligned_path(context).exists():
            raise FatalStageError(
                f"adduct_annotation: aligned features file not found at {self._aligned_path(context)}"
            )
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        aligned_table = pd.read_parquet(self._aligned_path(context))

        result = annotate_adducts(
            aligned_table,
            mz_tolerance_ppm=self.mz_tolerance_ppm,
            rt_tolerance_sec=self.rt_tolerance_sec,
            correlation_threshold=self.correlation_threshold,
            adduct_table=self.adduct_table,
        )
        result.to_parquet(self._annotated_path(context))

        group_sizes = result.groupby("adduct_group_id").size()
        context.qc_metrics[self._name] = {
            "n_features": len(result),
            "n_groups": result["adduct_group_id"].nunique(),
            "n_singleton_groups": int((group_sizes == 1).sum()),
            "largest_group_size": int(group_sizes.max()),
            "group_size_distribution": group_sizes.value_counts().sort_index().to_dict(),
        }

        context.log_step(
            self._name,
            parameters={
                "mz_tolerance_ppm": self.mz_tolerance_ppm,
                "rt_tolerance_sec": self.rt_tolerance_sec,
                "correlation_threshold": self.correlation_threshold,
            },
            metrics=context.qc_metrics[self._name],
            input_files=[str(self._aligned_path(context))],
            output_files=[str(self._annotated_path(context))],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics and self._annotated_path(context).exists()