import asyncio

from fastapi import APIRouter
from sqlalchemy import select

from api.deps import ExperimentDep, SessionDep
from api.schemas.sample import SampleOut
from core.ingestion import ingest_samples_from_csv
from core.models import Sample
from core.settings import settings

router = APIRouter(prefix="/studies/{study_id}", tags=["samples"])


def _to_sample_out(s: Sample) -> SampleOut:
    return SampleOut(
        sample_id=s.sample_id,
        description=s.description,
        status=s.status.value,
        checksum=s.checksum,
        ingested_at=s.ingested_at,
    )


@router.post("/ingest-samples")
async def ingest_samples(experiment: ExperimentDep):
    csv_path = settings.lcms_raw_data_dir / experiment.study_id / f"{experiment.study_id}_sample_metadata.csv"
    mzml_dir = settings.lcms_raw_data_dir / experiment.study_id
    return await asyncio.to_thread(ingest_samples_from_csv, experiment.id, csv_path, mzml_dir)


@router.get("/samples", response_model=list[SampleOut])
async def list_samples(experiment: ExperimentDep, session: SessionDep):
    result = await session.execute(select(Sample).where(Sample.experiment_id == experiment.id))
    return [_to_sample_out(s) for s in result.scalars().all()]
