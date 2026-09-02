"""
Stage 10: Spectral Library Matching

For every compound/feature, extracts its MS2 spectrum from the sample's
mzML and scores it against every reference spectrum in a *pre-built,
independently downloaded* library (e.g. EMBL-MCF from curatr.mcf.embl.de/MS2/export/)

Failure handling
- No match found for one compound/feature -> recoverable, logged,
  library_match_id/match_score stay None, is_correct_match = False.
- Reference library file missing or unparseable -> fatal (nothing in
  this run can be validated without it).
- MS2 extraction failing for every confirmed compound in the whole run
  -> fatal (instrument/acquisition-mode problem, not a single-compound
  problem)
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
from tqdm import tqdm

from analysis.utils.constants import NON_SAMPLE_COLS
from analysis.context import LCMSContext
from analysis.pipeline import FatalStageError
from analysis.utils.protocols import MS2SpectrumReader
from analysis.utils.spectral_library import ReferenceSpectrum, load_library, find_best_library_match, classify_confidence, empty_match_record
from core.ingestion import find_raw_file
from analysis.utils.mzml_parsing import load_ms1_scans, compute_ms1_coelution_purity
from analysis.utils.spectral_merging import merge_ms2_spectra
from analysis.utils.mzml_parsing import build_ms2_index, lookup_best_ms2
from analysis.utils.spectral_matching import names_match

# Bump whenever cosine_similarity/match_peaks or the reference library
# parsing logic changes -- file hashes alone won't catch an algorithm
# change, and the reference library file itself isn't in filehash_cache
# (it's outside results_dir), so this stage does not implement
# cache_key() at all for now: always re-run. Safer than a stale match
# silently surviving a scoring-logic change.
STAGE_LOGIC_VERSION = "v1"

class SpectralLibraryMatchingStage:
    """
    Stage 10: Spectral Library Matching (standards_only)
    """
    _name = "library_matching"

    def __init__(
        self,
        ms2_reader: MS2SpectrumReader,
        reference_library_path: Path,
        reference_library_format: str,
        precursor_mz_tolerance_ppm: float = 10.0,
        fragment_mz_tolerance_da: float = 0.02,
        min_match_score: float = 0.7,
    ):
        self.ms2_reader = ms2_reader
        self.reference_library_path = Path(reference_library_path)
        self.reference_library_format = reference_library_format
        self.precursor_mz_tolerance_ppm = precursor_mz_tolerance_ppm
        self.fragment_mz_tolerance_da = fragment_mz_tolerance_da
        self.min_match_score = min_match_score
        self._library: list[ReferenceSpectrum] | None = None

    def validate_input(self, context: LCMSContext) -> bool:
        if "system_suitability" not in context.qc_metrics:
            raise FatalStageError("library_matching: system_suitability must run first")
        if context.mzml_dir is None:
            raise FatalStageError("library_matching: mzml_directory not set")
        if not self.reference_library_path.exists():
            raise FatalStageError(
                f"library_matching: reference library not found at "
                f"{self.reference_library_path} -- download it from "
                f"curatr.mcf.embl.de/MS2/export/ and set "
                f"library_matching.reference_library_path in the config"
            )
        return True

    def _load_library(self) -> list[ReferenceSpectrum]:
        if self._library is None:
            try:
                self._library = load_library(self.reference_library_path, self.reference_library_format)
            except Exception as exc:
                raise FatalStageError(
                    f"library_matching: reference library unreadable "
                    f"({self.reference_library_path}): {exc}"
                ) from exc
            if not self._library:
                raise FatalStageError(
                    f"library_matching: reference library at "
                    f"{self.reference_library_path} parsed to zero usable "
                    f"entries -- check reference_library_format matches the file"
                )
        return self._library

    def execute(self, context: LCMSContext) -> LCMSContext:
        library = self._load_library()
        ss_results = context.qc_metrics["system_suitability"]["results"]

        results: dict[str, dict] = {}
        warnings: list[str] = []
        input_files: list[str] = [str(self.reference_library_path)]
        n_attempted = 0
        n_with_ms2 = 0
        n_matched = 0
        n_correct = 0

        for sample_id, ss_result in ss_results.items():
            if ss_result.get("status") != "checked":
                continue

            confirmed_matches = [m for m in ss_result["matches"] if m["confirmed"]]
            if not confirmed_matches:
                continue

            mzml_path = context.mzml_dir / f"{sample_id}.mzML"
            if not mzml_path.exists():
                warnings.append(f"{sample_id}: mzML missing, library matching skipped")
                continue
            input_files.append(str(mzml_path))

            sample_matches = []
            for match in confirmed_matches:
                n_attempted += 1
                compound = match["compound"]
                precursor_mz = match["matched_mz"]

                ms2_spectrum = self.ms2_reader.get_ms2_spectrum(
                    mzml_path, precursor_mz, precursor_tolerance_da=0.01
                )

                if not ms2_spectrum:
                    warnings.append(
                        f"{sample_id}: no MS2 spectrum extracted for {compound!r} "
                        f"(m/z {precursor_mz}) -- library matching skipped for this compound"
                    )
                    sample_matches.append(
                        empty_match_record(compound, precursor_mz, "no_ms2_spectrum")
                    )
                    continue

                n_with_ms2 += 1
                found = find_best_library_match(
                    ms2_spectrum,
                    precursor_mz,
                    library,
                    self.precursor_mz_tolerance_ppm,
                    self.fragment_mz_tolerance_da,
                )

                if found is None:
                    warnings.append(
                        f"{sample_id}: no library entry within "
                        f"{self.precursor_mz_tolerance_ppm} ppm of {compound!r} "
                        f"(m/z {precursor_mz}) -- no match found"
                    )
                    sample_matches.append(
                        {
                            "compound": compound,
                            "expected_mz": precursor_mz,
                            "ms2_spectrum": ms2_spectrum,
                            "n_ms2_peaks": len(ms2_spectrum),
                            "library_match_id": None,
                            "match_compound_name": None,
                            "match_score": None,
                            "match_adduct": None,
                            "known_identity": compound,
                            "is_correct_match": False,
                            "status": "no_precursor_candidates",
                        }
                    )
                    continue

                ref, score = found
                n_matched += 1
                passes_threshold = score >= self.min_match_score
                correct = passes_threshold and names_match(compound, ref.compound_name)
                if correct:
                    n_correct += 1
                elif passes_threshold:
                    warnings.append(
                        f"{sample_id}: top match for {compound!r} is "
                        f"{ref.compound_name!r} (score {score:.3f}) -- name mismatch"
                    )
                else:
                    warnings.append(
                        f"{sample_id}: best match for {compound!r} scored "
                        f"{score:.3f}, below threshold {self.min_match_score}"
                    )

                sample_matches.append(
                    {
                        "compound": compound,
                        "expected_mz": precursor_mz,
                        "ms2_spectrum": ms2_spectrum,
                        "n_ms2_peaks": len(ms2_spectrum),
                        "library_match_id": ref.library_id,
                        "match_compound_name": ref.compound_name,
                        "match_score": score,
                        "match_adduct": ref.adduct,
                        "known_identity": compound,
                        "is_correct_match": correct,
                        "status": "matched" if passes_threshold else "below_threshold",
                    }
                )

            results[sample_id] = {"status": "checked", "matches": sample_matches}

        if n_attempted > 0 and n_with_ms2 == 0:
            raise FatalStageError(
                "library_matching: could not extract an MS2 spectrum for any "
                f"confirmed compound across all {n_attempted} attempted -- "
                "likely an acquisition-mode/precursor-list problem, not a "
                "single-compound problem"
            )

        context.qc_metrics[self._name] = {
            "results": results,
            "n_attempted": n_attempted,
            "n_with_ms2": n_with_ms2,
            "n_matched": n_matched,
            "n_correct": n_correct,
            "validation_rate": (n_correct / n_attempted) if n_attempted else None,
            "reference_library_size": len(library),
        }
        context.log_step(
            self._name,
            parameters={
                "reference_library_path": str(self.reference_library_path),
                "reference_library_format": self.reference_library_format,
                "precursor_mz_tolerance_ppm": self.precursor_mz_tolerance_ppm,
                "fragment_mz_tolerance_da": self.fragment_mz_tolerance_da,
                "min_match_score": self.min_match_score,
            },
            metrics={
                "n_attempted": n_attempted,
                "n_with_ms2": n_with_ms2,
                "n_matched": n_matched,
                "n_correct": n_correct,
            },
            warnings=warnings,
            input_files=input_files,
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics

class CohortLibraryMatchingStage:
    """
    Stage 10: Library Matching (cohort_with_qc profile)
    """
    _name = "library_matching"

    def __init__(
        self,
        reference_library_path: Path,
        reference_library_format: str,
        precursor_mz_tolerance_ppm: float = 10.0,
        fragment_mz_tolerance_da: float = 0.02,
        min_match_score: float = 0.7,
        min_purity_high_confidence: float = 0.8,
        min_purity_tentative: float = 0.5,
        min_relative_intensity: float = 0.01,
        isolation_window_da: float = 1.0,
    ):
        self.reference_library_path = Path(reference_library_path)
        self.reference_library_format = reference_library_format
        self.precursor_mz_tolerance_ppm = precursor_mz_tolerance_ppm
        self.fragment_mz_tolerance_da = fragment_mz_tolerance_da
        self.min_match_score = min_match_score
        self.min_purity_high_confidence = min_purity_high_confidence
        self.min_purity_tentative = min_purity_tentative
        self.min_relative_intensity = min_relative_intensity
        self.isolation_window_da = isolation_window_da
        self._library: list[ReferenceSpectrum] | None = None

    def _annotated_path(self, context: LCMSContext) -> Path:
        return context.featurejson_dir / f"{context.study_id}_annotated_features.parquet"

    def validate_input(self, context: LCMSContext) -> bool:
        if "adduct_annotation" not in context.qc_metrics:
            raise FatalStageError("library_matching: adduct_annotation must run first")
        if not self._annotated_path(context).exists():
            raise FatalStageError(f"library_matching: annotated features not found at {self._annotated_path(context)}")
        if not self.reference_library_path.exists():
            raise FatalStageError(f"library_matching: reference library not found at {self.reference_library_path}")
        return True

    def _load_library(self) -> list[ReferenceSpectrum]:
        if self._library is None:
            self._library = load_library(self.reference_library_path, self.reference_library_format)
            if not self._library:
                raise FatalStageError("library_matching: reference library parsed to zero usable entries")
        return self._library

    def execute(self, context: LCMSContext) -> LCMSContext:
        library = self._load_library()
        table = pd.read_parquet(self._annotated_path(context))

        sample_cols = [c for c in table.columns if c not in NON_SAMPLE_COLS]
        primary_rows = table[
            table["ion_type"].str.contains("primary", na=False)
            | table["ion_type"].str.contains("assumed, ungrouped", na=False)
            ]

        # Cache one sample's parsed MS1 scans across the WHOLE run, not
        # per-group -- reloading a raw file per (group, sample) pair would
        # reparse the same ~5000-6000-scan file thousands of times.
        ms1_scan_cache: dict[str, list[dict]] = {}

        def get_ms1_scans(ms1_sample_id: str) -> list[dict]:
            if ms1_sample_id not in ms1_scan_cache:
                raw_path = find_raw_file(context.mzml_dir, ms1_sample_id)
                ms1_scan_cache[ms1_sample_id] = load_ms1_scans(raw_path) if raw_path else []
            return ms1_scan_cache[ms1_sample_id]

        ms2_index_cache: dict[str, list] = {}

        def get_ms2_index(ms2_sample_id: str) -> list:
            if ms2_sample_id not in ms2_index_cache:
                raw_path = find_raw_file(context.mzml_dir, ms2_sample_id)
                ms2_index_cache[ms2_sample_id] = build_ms2_index(raw_path) if raw_path else []
            return ms2_index_cache[ms2_sample_id]

        results: dict[str, dict] = {}
        warnings: list[str] = []
        n_groups_attempted = 0
        n_groups_with_ms2 = 0
        n_matched = 0
        confidence_counts = {"high_confidence": 0, "tentative": 0, "low_confidence": 0, "no_match": 0}

        for _, row in tqdm(primary_rows.iterrows(), total=len(primary_rows), desc=self._name):
            group_id = row["adduct_group_id"]
            n_groups_attempted += 1
            target_mz, target_rt = row["mz"], row["rt"]

            present_samples = [sid for sid in sample_cols if pd.notna(row[sid])]

            collected_spectra = []
            purities = []

            for sample_id in present_samples:
                ms2_spectrum = lookup_best_ms2(
                    get_ms2_index(sample_id), target_mz, 0.01, self.min_relative_intensity
                )
                if ms2_spectrum:
                    collected_spectra.append(ms2_spectrum)

                purity = compute_ms1_coelution_purity(
                    get_ms1_scans(sample_id), target_mz, target_rt, self.isolation_window_da,
                )
                if purity is not None:
                    purities.append(purity)

            avg_purity = sum(purities) / len(purities) if purities else None

            if not collected_spectra:
                results[str(group_id)] = {"status": "no_ms2_available", "purity": avg_purity}
                confidence_counts["no_match"] += 1
                continue

            n_groups_with_ms2 += 1
            merged_spectrum = merge_ms2_spectra(collected_spectra, self.fragment_mz_tolerance_da)

            found = find_best_library_match(
                merged_spectrum, target_mz, library,
                self.precursor_mz_tolerance_ppm, self.fragment_mz_tolerance_da,
            )

            if found is None:
                results[str(group_id)] = {"status": "no_precursor_candidates", "purity": avg_purity}
                confidence_counts["no_match"] += 1
                continue

            ref, score = found
            n_matched += 1
            confidence = classify_confidence(
                score, avg_purity, self.min_match_score,
                self.min_purity_high_confidence, self.min_purity_tentative,
            )
            confidence_counts[confidence] += 1

            results[str(group_id)] = {
                "status": "matched",
                "match_compound_name": ref.compound_name,
                "match_score": score,
                "match_adduct": ref.adduct,
                "n_contributing_samples": len(collected_spectra),
                "purity": avg_purity,
                "confidence": confidence,
            }

        context.qc_metrics[self._name] = {
            "results": results,
            "n_groups_attempted": n_groups_attempted,
            "n_groups_with_ms2": n_groups_with_ms2,
            "n_matched": n_matched,
            "confidence_counts": confidence_counts,
            "reference_library_size": len(library),
        }
        context.log_step(
            self._name,
            parameters={
                "precursor_mz_tolerance_ppm": self.precursor_mz_tolerance_ppm,
                "fragment_mz_tolerance_da": self.fragment_mz_tolerance_da,
                "min_match_score": self.min_match_score,
                "min_purity_high_confidence": self.min_purity_high_confidence,
                "min_purity_tentative": self.min_purity_tentative,
            },
            metrics=context.qc_metrics[self._name],
            warnings=warnings,
            input_files=[str(self._annotated_path(context)), str(self.reference_library_path)],
        )
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return self._name in context.qc_metrics
