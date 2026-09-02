"""
Stage 6: Feature Alignment (cohort_with_qc profile)

Builds a cross-sample consensus feature table from per-sample .featureJSON
files.
Required before any cohort-mode stage that needs a unified feature set (blank_qc, adduct_annotation, library_matching)
"""
import json
from pathlib import Path

from analysis.context import LCMSContext
from analysis.utils.feature_alignment import align_features
from analysis.utils.cache_utils import load_filehash_cache, hash_files, save_filehash_cache, compute_cache_key
from analysis.utils.constants import FEATURE_FILE_SUFFIX

CACHE_SCHEMA_VERSION = "v1"

class FeatureAlignmentStage:
    """
    Stage 6: Feature Alignment (cohort_with_qc profile)
    """
    _name: str = "feature_alignment"

    def __init__(self, mz_tolerance_ppm: float, rt_tolerance_sec: float):
        self.mz_tolerance_ppm = mz_tolerance_ppm
        self.rt_tolerance_sec = rt_tolerance_sec

    def _aligned_path(self, context: LCMSContext) -> Path:
        return context.featurejson_dir / f"{context.study_id}_aligned_features.parquet"

    def cache_key(self, context: LCMSContext) -> str:
        hash_cache = load_filehash_cache(context.cache_dir)
        fd_results = context.qc_metrics.get("feature_detection", {}).get("results", {})
        ok_sample_ids = [sid for sid, r in fd_results.items() if r.get("status") == "ok"]
        featurejson_paths = [
            context.featurejson_dir / f"{sid}{FEATURE_FILE_SUFFIX}" for sid in ok_sample_ids
        ]
        featurejson_paths = [p for p in featurejson_paths if p.exists()]

        payload = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "mz_tolerance_ppm": self.mz_tolerance_ppm,
            "rt_tolerance_sec": self.rt_tolerance_sec,
            "featurejson_hashes": hash_files(featurejson_paths, hash_cache),
        }
        save_filehash_cache(context.cache_dir, hash_cache)
        return compute_cache_key(payload)

    def validate_input(self, context: LCMSContext) -> bool:
        fd_results = context.qc_metrics.get("feature_detection", {}).get("results", {})
        return any(r.get("status") == "ok" for r in fd_results.values())

    def execute(self, context: LCMSContext) -> LCMSContext:
        fd_results = context.qc_metrics["feature_detection"]["results"]

        per_sample_features = {}
        skipped = []
        for sample_id, result in fd_results.items():
            if result.get("status") != "ok":
                skipped.append(sample_id)
                continue
            path = context.featurejson_dir / f"{sample_id}{FEATURE_FILE_SUFFIX}"
            if not path.exists():
                skipped.append(sample_id)
                continue
            with open(path) as f:
                per_sample_features[sample_id] = json.load(f)

        table = align_features(per_sample_features, self.mz_tolerance_ppm, self.rt_tolerance_sec)
        table.to_parquet(self._aligned_path(context))

        context.qc_metrics[self._name] = {
            "n_consensus_features": len(table),
            "n_samples_included": len(per_sample_features),
            "n_samples_skipped": len(skipped),
            "skipped_sample_ids": skipped,
        }
        context.log_step(
            self._name,
            parameters={
                "mz_tolerance_ppm": self.mz_tolerance_ppm,
                "rt_tolerance_sec": self.rt_tolerance_sec,
            },
            metrics={"n_consensus_features": len(table),
                     "n_samples_included": len(per_sample_features)},
            warnings=[f"{sid}: skipped (missing/failed feature detection)" for sid in skipped],
            input_files=[str(context.featurejson_dir / f"{sid}.featurejson") for sid in per_sample_features],
            output_files=[str(self._aligned_path(context))],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics and self._aligned_path(context).exists()