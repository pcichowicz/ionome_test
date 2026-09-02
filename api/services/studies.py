from pathlib import Path

import pandas as pd
import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config_schema import ExperimentConfig
from core.ingestion import find_raw_file, ingest_samples_from_csv
from core.models import Experiment, Pipeline, Sample
from core.settings import settings
from core.status import STATUS
from api.schemas.study import (
    RawFileScanResult,
    SampleReadiness,
    SampleStatusCounts,
    StudyCreateResult,
    StudySummary,
)

# core/status.py's STATUS.DONE is unused anywhere in the codebase -- treated
# as dead here too. If it ever gets a real meaning, it needs a bucket below.
_COUNT_FIELDS = {
    STATUS.PENDING: "pending",
    STATUS.RUNNING: "running",
    STATUS.SUCCESS: "success",
    STATUS.FAILED: "failed",
}


async def list_study_summaries(session: AsyncSession) -> list[StudySummary]:
    experiments = (await session.execute(select(Experiment))).scalars().all()

    sample_rows = (
        await session.execute(
            select(Sample.experiment_id, Sample.status, func.count())
            .group_by(Sample.experiment_id, Sample.status)
        )
    ).all()
    counts_by_experiment: dict[int, SampleStatusCounts] = {}
    for experiment_id, status, count in sample_rows:
        bucket = counts_by_experiment.setdefault(experiment_id, SampleStatusCounts())
        bucket.total += count
        field = _COUNT_FIELDS.get(status)
        if field is not None:
            setattr(bucket, field, getattr(bucket, field) + count)

    last_run_rows = (
        await session.execute(
            select(Pipeline.experiment_id, func.max(Pipeline.started_at))
            .group_by(Pipeline.experiment_id)
        )
    ).all()
    last_run_by_experiment = dict(last_run_rows)

    return [
        StudySummary(
            study_id=e.study_id,
            dataset_profile=_read_dataset_profile(e.config_path),
            status=e.status.value,
            sample_counts=counts_by_experiment.get(e.id, SampleStatusCounts()),
            created_at=e.created_at,
            last_run_at=last_run_by_experiment.get(e.id),
        )
        for e in experiments
    ]


def _read_dataset_profile(config_path: str) -> str | None:
    """Best-effort: dataset_profile isn't stored on Experiment itself, only
    in its config file. Missing/unreadable config shouldn't break the
    dashboard -- just show it blank."""
    try:
        with open(config_path) as f:
            return yaml.safe_load(f).get("dataset_profile")
    except (OSError, AttributeError):
        return None


def load_config_defaults() -> dict:
    """The intake wizard's config step pre-fills from this template -- the
    single source of truth for lab-standard stage parameters, also used
    directly by anyone hand-writing a YAML."""
    template_path = Path(__file__).resolve().parents[2] / "config" / "experiments" / "template.yaml"
    with open(template_path) as f:
        return yaml.safe_load(f)


def scan_raw_dir(study_id: str) -> RawFileScanResult:
    """Lists candidate sample_ids by stem-matching .mzML/.mzXML files already
    dropped in the study's raw-data dir. Deliberately has no DB dependency --
    this must work before the Experiment row (or even the YAML/CSV) exists,
    since it's the first step of the intake wizard."""
    raw_dir = settings.lcms_raw_data_dir / study_id
    if not raw_dir.is_dir():
        return RawFileScanResult(
            study_id=study_id, raw_data_dir=str(raw_dir), dir_exists=False, sample_ids=[]
        )
    sample_ids = sorted({
        p.stem for p in raw_dir.iterdir() if p.suffix in (".mzML", ".mzXML")
    })
    return RawFileScanResult(
        study_id=study_id, raw_data_dir=str(raw_dir), dir_exists=True, sample_ids=sample_ids
    )


async def get_sample_readiness(study_id: str, experiment_id: int, session: AsyncSession) -> SampleReadiness:
    """Diffs a study's declared samples (already-ingested Sample rows) against
    what's currently sitting in the raw-data dir -- powers the study-detail
    'N of M expected samples present' readiness banner."""
    expected = sorted(
        (await session.execute(select(Sample.sample_id).where(Sample.experiment_id == experiment_id)))
        .scalars().all()
    )
    present = set(scan_raw_dir(study_id).sample_ids)
    return SampleReadiness(
        study_id=study_id,
        expected=expected,
        present=sorted(present),
        missing=sorted(set(expected) - present),
    )


class StudyCreateError(ValueError):
    """Raised for any intake validation failure -- config, missing raw
    files, or a study_id that already exists. Carries a flat list of
    human-readable messages for the wizard's top-level error summary."""
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def create_study_files_and_ingest(config_dict: dict, sample_rows: list[dict]) -> StudyCreateResult:
    """The intake wizard's single atomic submit: validate config, pre-flight
    check raw files, write the real YAML + CSV to disk, create the Experiment
    row, and ingest samples. Runs sync (matches the rest of the ingestion
    code path, e.g. ingest_samples_from_csv/get_experiment_pk_sync) -- callers
    from async endpoints should wrap this in asyncio.to_thread.
    """
    errors: list[str] = []

    try:
        config = ExperimentConfig(**config_dict)
    except Exception as exc:
        raise StudyCreateError([f"config validation failed: {exc}"]) from exc

    if not sample_rows:
        errors.append("no sample rows submitted")
    sample_ids = [row.get("sample_id") for row in sample_rows]
    if any(sid in (None, "") for sid in sample_ids):
        errors.append("every sample row needs a non-empty sample_id")

    study_id = config.study.id
    raw_dir = settings.lcms_raw_data_dir / study_id
    missing_files = [
        sid for sid in sample_ids
        if sid and find_raw_file(raw_dir, sid) is None
    ]
    if missing_files:
        errors.append(
            f"no raw file found for sample_id(s) in {raw_dir}: {', '.join(missing_files)}"
        )

    from core.db import SyncSessionLocal
    with SyncSessionLocal() as session:
        existing = session.query(Experiment).filter(Experiment.study_id == study_id).first()
    if existing is not None:
        errors.append(f"study_id {study_id!r} already exists")

    if errors:
        raise StudyCreateError(errors)

    csv_path = raw_dir / config.files.sample_metadata
    raw_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sample_rows).to_csv(csv_path, index=False)

    yaml_path = settings.yaml_dir / f"{study_id}.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    with open(yaml_path, "w") as f:
        yaml.safe_dump(config_dict, f, sort_keys=False)

    with SyncSessionLocal() as session:
        experiment = Experiment(
            study_id=study_id,
            config_path=str(yaml_path),
            status=STATUS.PENDING,
        )
        session.add(experiment)
        session.commit()
        session.refresh(experiment)
        experiment_id = experiment.id

    ingestion_result = ingest_samples_from_csv(experiment_id, csv_path, raw_dir)

    return StudyCreateResult(
        study_id=study_id,
        experiment_id=experiment_id,
        yaml_path=str(yaml_path),
        csv_path=str(csv_path),
        ingestion=ingestion_result,
    )
