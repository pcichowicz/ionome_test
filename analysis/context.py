
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import pandas as pd

from core.config_schema import ExperimentConfig
from core.db import SyncSessionLocal
from analysis.utils.schemas import LibraryEntry
from core.paths import PROJECT_PATH
from core.models import Sample
from core.settings import settings

@dataclass
class LCMSContext:
    """
    Core context object that flows through every pipeline stage.

    LCMSContext carries file path and small in-memory metadata/results between
    stages -- NOT full DataFrames, spectra, or raw arrays. Large intermediate
    data (mzML, featureXML, etc.) lives on disk; the context just tracks where.
    This keeps memory bounded regardless of dataset size and makes every stage
    independently re-runnable/debuggable.
    """
    study_id: str
    experiment_id: int
    config: ExperimentConfig

    # Runtime Configurations (loads from yaml)
    dataset_profile: str = field(init=False)
    polarity: str = field(init=False)
    instrument: str = field(init=False)
    yaml_config: dict[str, Any] = field(default_factory=dict, repr=False)

    base_dir: Path = field(default=PROJECT_PATH)
    results_dir: Path = field(init=False)
    mzml_dir: Path = field(init=False)
    featurejson_dir: Path = field(init=False)
    library_dir: Path = field(init=False)
    qc_report_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    plots_dir: Path = field(init=False)
    cache_dir: Path = field(init=False)

    yaml_path: Path = field(init=False)
    sample_metadata_path: Path = field(init=False)
    aligned_features_path: Path = field(init=False)
    mzml_file_paths: list[Path] = field(default_factory=list, repr=False)

    # In memory Data / State
    sample_metadata: Optional[pd.DataFrame] = field(default=None, repr=False)
    qc_metrics: dict[str, Any] = field(default_factory=dict)
    processing_log: list[dict[str, Any]] = field(default_factory=list)

    #Final outputs
    library_entries: list[LibraryEntry] = field(default_factory=list)
    final_feature_table: pd.DataFrame = field(default=None, repr=False)

    def __post_init__(self):
        """
        Resolves paths, validates files, creates dirs, loads configs
        """
        self.base_dir = self.base_dir.resolve()
        self.results_dir = settings.lcms_results_dir / self.study_id
        self.mzml_dir = settings.lcms_raw_data_dir / self.study_id

        self.sample_metadata_path = self.mzml_dir / f"{self.study_id}_sample_metadata.csv"

        self._validate_dirs()

        self.polarity = self.config.study.polarity
        self.instrument = self.config.study.instrument
        self.dataset_profile = self.config.dataset_profile

        self.sample_metadata = pd.read_csv(self.sample_metadata_path)
        self.mzml_file_paths = self._load_mzml_file_paths()

        #outputs dir
        self.featurejson_dir = self.results_dir / "features"
        self.library_dir = self.results_dir / "library"
        self.qc_report_dir = self.results_dir / "qc_reports"
        self.plots_dir = self.results_dir / "plots"
        self.logs_dir = self.results_dir / "logs"
        self.cache_dir = self.results_dir / "cache"

        self.make_dirs(subdirs=settings.output_dirs)

    def log_step(
        self,
        step_name: str,
        parameters: dict[str, Any],
        metrics: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        input_files: list[str] | None = None,
        output_files: list[str] | None = None,
    ) -> None:
        """
        Record a provenance entry for a completed (or partially-failed) stage.

        Every stage should call this exactly once, even on a recoverable
        failure
        """
        self.processing_log.append(
            {
            "stage": step_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parameters": parameters,
            "metrics": metrics or {},
            "warnings": warnings or [],
            "input_files": input_files or [],
            "output_dirs": output_files or [],
            }
        )

    def _validate_dirs(self):
        """
        Checks if yaml config and cvs sample data files are upload prior with api/manually
        """
        if not self.sample_metadata_path.exists():
            raise FileNotFoundError(f"ERROR: Metadata CSV missing at {self.sample_metadata_path}")

    def _load_mzml_file_paths(self) -> list[Path]:
        with SyncSessionLocal() as session:
            samples = session.query(Sample).filter(
                Sample.experiment_id == self.experiment_id
            ).all()
        return [Path(s.raw_file_path) for s in samples if s.raw_file_path]

    def make_dirs(self, exist_ok: bool = True, subdirs: list[str] | None = None) -> None:
        self.results_dir.mkdir(exist_ok=exist_ok, parents=True)

        if subdirs:
            for s in subdirs:
                (self.results_dir / s).mkdir(exist_ok=exist_ok, parents=True)

    def resolve(self, *path_parts) -> Path:
        p = Path(*[part for part in path_parts if part is not None])
        out = p if p.is_absolute() else self.results_dir / p
        out.parent.mkdir(exist_ok=True, parents=True)
        return out

    def path_for(self, stem: str, ext: str = "", subdir: str | None = None) -> Path:
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        name = f"{stem}{ext}"
        return self.resolve(subdir, name)
