from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
import yaml

class Polarity(str, Enum):
    positive = "positive"
    negative = "negative"

class DatasetProfile(str, Enum):
    standards_only = "standards_only"
    cohort_with_qc = "cohort_with_qc"

class LibraryFormat(str, Enum):
    msp = "msp"
    mgf = "mgf"

class StudyInfo(BaseModel):
    id: str
    polarity: Polarity
    instrument: str

class FilesInfo(BaseModel):
    sample_metadata: str # filename, resolved against study's input dir at runtime

class SystemSuitability(BaseModel):
    ppm_tolerance: float = Field(gt=0)

class FeatureDetection(BaseModel):
    mass_error_ppm: float = Field(gt=0)
    peak_width: tuple[float, float]
    max_gaps: int = Field(gt=0)
    min_scans: int = Field(ge=1)
    noise_threshold: float = Field(gt=0)

    @field_validator("peak_width")
    @classmethod
    def validate_peak_width(cls, peak_width: tuple[float, float]) -> tuple[float, float]:
        lower, upper = peak_width
        if lower >= upper:
            raise ValueError(f"peak_width lower bound {lower} must be < upper bound {upper}")
        return peak_width

class FeatureAlignment(BaseModel):
    alignment_mz_tolerance_ppm: float = Field(gt=0)
    alignment_rt_tolerance_sec: float = Field(gt=0)

class BlankQC(BaseModel):
    mz_tolerance_ppm: float = Field(gt=0)
    rt_tolerance_sec: float = Field(gt=0)

class AdductAnnotation(BaseModel):
    primary_adduct: str
    ppm_tolerance: float = Field(gt=0)
    candidate_adducts: list[str] = Field()

    @field_validator("candidate_adducts")
    @classmethod
    def primary_must_be_in_candidates(cls, candidates, info):
        primary = info.data.get("primary_adduct")
        if primary is not None and primary not in candidates:
            raise ValueError(f"primary adduct {primary} not in candidates {candidates}, it must be included")
        return candidates

class SpectralPurity(BaseModel):
    isolation_window_da: float = Field(gt=0)
    min_purity: float = Field(ge=0, le=1)

class LibraryMatching(BaseModel):
    reference_library: str
    reference_library_source: str
    reference_library_path: str
    reference_library_format: LibraryFormat
    similarity_metric: str
    precursor_mz_tolerance_ppm: float = Field(gt=0)
    fragment_mz_tolerance_da: float = Field(gt=0)
    min_match_score: float = Field(ge=0, le=1)
    validate_against_known_identity: bool = False

class ExperimentConfig(BaseModel):
    study: StudyInfo
    dataset_profile: DatasetProfile
    files: FilesInfo
    system_suitability: SystemSuitability
    feature_detection: FeatureDetection
    feature_alignment: FeatureAlignment
    blank_qc: BlankQC
    adduct_annotation: AdductAnnotation
    spectral_purity: SpectralPurity
    library_matching: LibraryMatching
    config_version: str

    model_config = {"extra": "forbid"}

def load_experiment_config(config_path: Path) -> ExperimentConfig:
    """
    Loads and validate experiment YAML config
    """
    with open(config_path, "r") as f:
        contents = yaml.safe_load(f)

    return ExperimentConfig(**contents)
