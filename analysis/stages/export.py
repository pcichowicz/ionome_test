"""
Stage : Export.

    library.json
    library.csv
    qc_report.json
"""
from __future__ import annotations
import csv
import json
import platform
from typing import Any

from analysis.context import LCMSContext
from analysis.pipeline import FatalStageError
from analysis.utils.schemas import QCReport
from analysis.utils.qc_summary import build_qc_metrics_summary

# Explicit column order for the flattened CSV -- kept separate from
# schemas.LibraryEntry's key order so it stays stable
CSV_COLUMNS = [
    "entry_id",
    "compound_name",
    "precursor_mz",
    "rt_sec",
    "adduct",
    "charge",
    "mass_error_ppm",
    "n_ms2_peaks",
    "spectral_purity",
    "source_sample_id",
    "blank_flagged",
    "library_match_id",
    "match_score",
    "known_identity",
    "is_correct_match",
]

def _software_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    try:
        import pymzml  # type: ignore
        versions["pymzml"] = getattr(pymzml, "__version__", "unknown")
    except ImportError:
        pass
    return versions

class ExportStage:
    _name = "export"

    def validate_input(self, context: LCMSContext) -> bool:
        if not context.library_entries:
            raise FatalStageError("export: library_assembly must run first and produce entries")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        library_dir = context.library_dir
        qc_dir = context.qc_report_dir
        library_dir.mkdir(parents=True, exist_ok=True)
        qc_dir.mkdir(parents=True, exist_ok=True)

        json_path = library_dir / "library.json"
        csv_path = library_dir / "library.csv"
        report_path = qc_dir / "qc_report.json"

        json_path.write_text(json.dumps(context.library_entries, indent=2, default=str))
        self._write_csv(csv_path, context.library_entries)

        config_version = context.config.config_version
        software_versions = _software_versions()
        # input_files/output_files are now real (every stage's log_step call
        # reports what it actually read/wrote) -- config_version and
        # software_versions are the only fields still added here, since
        # they're cross-cutting rather than per-stage.
        enriched_log = [
            {**entry, "config_version": config_version, "software_versions": software_versions}
            for entry in context.processing_log
        ]

        report: QCReport = {
            "study_id": context.study_id,
            "config_version": config_version,
            "dataset_profile": context.dataset_profile,
            "qc_metrics": build_qc_metrics_summary(context.qc_metrics),
            "processing_log": enriched_log,
            "raw_qc_metrics": context.qc_metrics,
        }
        report_path.write_text(json.dumps(report, indent=2, default=str))

        context.qc_metrics["export"] = {
            "library_json": str(json_path),
            "library_csv": str(csv_path),
            "qc_report": str(report_path),
            "n_entries": len(context.library_entries),
        }
        context.log_step(
            self._name,
            parameters={},
            metrics={"n_entries": len(context.library_entries)},
        )
        return context

    @staticmethod
    def _write_csv(csv_path, entries: list[dict[str, Any]]) -> None:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for entry in entries:
                row = {col: entry.get(col) for col in CSV_COLUMNS}
                row["n_ms2_peaks"] = len(entry.get("ms2_spectrum") or [])
                writer.writerow(row)

    def validate_output(self, context: LCMSContext) -> bool:
        return (
            (context.library_dir / "library.json").exists()
            and (context.library_dir / "library.csv").exists()
            and (context.qc_report_dir / "qc_report.json").exists()
        )

class CohortExportStage:
    _name = "export"

    def validate_input(self, context: LCMSContext) -> bool:
        if context.final_feature_table is None:
            raise FatalStageError("export: library_assembly must run first")
        return True

    def execute(self, context: LCMSContext) -> LCMSContext:
        table = context.final_feature_table
        library_dir = context.library_dir
        qc_dir = context.qc_report_dir
        library_dir.mkdir(parents=True, exist_ok=True)
        qc_dir.mkdir(parents=True, exist_ok=True)

        json_path = library_dir / f"{context.study_id}_feature_table.json"
        csv_path = library_dir / f"{context.study_id}_feature_table.csv"
        report_path = qc_dir / f"{context.study_id}_qc_report.json"

        table.to_json(json_path, orient="records", indent=2)
        table.to_csv(csv_path, index=False)  # every column, dynamic -- no fixed schema needed

        report = {
            "study_id": context.study_id,
            "dataset_profile": context.dataset_profile,
            "qc_metrics": context.qc_metrics,
            "processing_log": context.processing_log,
        }
        report_path.write_text(json.dumps(report, indent=2, default=str))

        context.qc_metrics[self._name] = {
            "feature_table_json": str(json_path),
            "feature_table_csv": str(csv_path),
            "qc_report": str(report_path),
            "n_features": len(table),
        }
        context.log_step(self._name, parameters={}, metrics=context.qc_metrics["export"])
        return context

    def validate_output(self, context: LCMSContext) -> bool:
        return (context.library_dir / f"{context.study_id}_feature_table.csv").exists()