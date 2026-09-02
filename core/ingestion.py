# core/ingestion.py
import hashlib
from pathlib import Path

import pandas as pd

from core.db import SyncSessionLocal
from core.models import Sample, Experiment
from core.status import STATUS


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_samples_from_csv(experiment_pk: int, csv_path: Path, mzml_dir: Path) -> dict:
    df = pd.read_csv(csv_path)
    if "sample_id" not in df.columns:
        raise ValueError(f"sample_metadata csv missing 'sample_id' column: {csv_path}")

    created, skipped_existing, skipped_missing_file = [], [], []

    with SyncSessionLocal() as session:
        for _, row_data in df.iterrows():
            sample_id = row_data["sample_id"]

            existing = (
                session.query(Sample)
                .filter(Sample.experiment_id == experiment_pk, Sample.sample_id == sample_id)
                .first()
            )
            if existing is not None:
                skipped_existing.append(sample_id)
                continue

            # raw_file = mzml_dir / f"{sample_id}.mzML"
            raw_file = find_raw_file(mzml_dir, sample_id)
            if raw_file is None:
                skipped_missing_file.append(sample_id)
                continue

            session.add(Sample(
                experiment_id=experiment_pk,
                sample_id=sample_id,
                description=row_data.get("sample_role"),
                raw_file_path=str(raw_file),
                checksum=_sha256_of_file(raw_file),
                status=STATUS.PENDING,
            ))
            created.append(sample_id)

        session.commit()

    return {
        "n_created": len(created), "created": created,
        "n_skipped_existing": len(skipped_existing),
        "n_skipped_missing_file": len(skipped_missing_file),
        "skipped_missing_file": skipped_missing_file,
    }

def find_raw_file(mzml_dir: Path, sample_id: str) -> Path | None:
    """
    Checks for a sample's raw file under either supported extension.
    Returns the path found, or None if neither exists.
    Checks .mzML first (existing dataset convention), then .mzXML.
    """
    for suffix in (".mzML", ".mzXML"):
        candidate = mzml_dir / f"{sample_id}{suffix}"
        if candidate.exists():
            return candidate
    return None

def get_experiment_pk_sync(study_id: str) -> int:
    """
    Resolves a study's string slug (config.study.id) to its integer
    Experiment PK, using the sync session -- mirrors what
    _get_or_create_experiment does async-side, but read-only:
    assumes the Experiment row already exists (ingestion/experiment
    creation must have already happened via the API route).
    """
    with SyncSessionLocal() as session:
        experiment = session.query(Experiment).filter(
            Experiment.study_id == study_id
        ).one_or_none()
        if experiment is None:
            raise ValueError(
                f"No Experiment found for study_id={study_id!r} -- "
                f"has /studies/{study_id}/ingest-samples been called yet?"
            )
        return experiment.id