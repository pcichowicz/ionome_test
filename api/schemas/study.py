from datetime import datetime
from pydantic import BaseModel


class SampleStatusCounts(BaseModel):
    total: int = 0
    pending: int = 0
    running: int = 0
    success: int = 0
    failed: int = 0


class StudySummary(BaseModel):
    """One row of the dashboard table."""
    study_id: str
    dataset_profile: str | None
    status: str
    sample_counts: SampleStatusCounts
    created_at: datetime | None
    last_run_at: datetime | None


class StudyDetail(BaseModel):
    study_id: str
    dataset_profile: str | None
    status: str
    created_at: datetime | None
    config_path: str


class RawFileScanResult(BaseModel):
    study_id: str
    raw_data_dir: str
    dir_exists: bool
    sample_ids: list[str]


class SampleReadiness(BaseModel):
    """Diff between a study's declared sample_ids and what's actually on disk."""
    study_id: str
    expected: list[str]
    present: list[str]
    missing: list[str]


class StudyCreateRequest(BaseModel):
    """Body for POST /studies -- the intake wizard's single final submit.

    `config` is validated against ExperimentConfig server-side; `sample_rows`
    becomes the sample_metadata CSV (must include a sample_id column plus
    whatever other columns the lab records, e.g. sample_role/description).
    """
    config: dict
    sample_rows: list[dict]


class StudyCreateResult(BaseModel):
    study_id: str
    experiment_id: int
    yaml_path: str
    csv_path: str
    ingestion: dict
