import asyncio

from fastapi import APIRouter, HTTPException

from api.deps import ExperimentDep, SessionDep
from api.schemas.study import (
    RawFileScanResult,
    SampleReadiness,
    StudyCreateRequest,
    StudyCreateResult,
    StudySummary,
)
from api.services.studies import (
    StudyCreateError,
    create_study_files_and_ingest,
    get_sample_readiness,
    list_study_summaries,
    load_config_defaults,
    scan_raw_dir,
)

router = APIRouter(prefix="/studies", tags=["studies"])


@router.get("", response_model=list[StudySummary])
async def list_studies(session: SessionDep):
    return await list_study_summaries(session)


@router.get("/config-defaults")
async def get_config_defaults():
    """Lab-standard stage parameters the intake wizard's config step
    pre-fills from -- everything except study.id/polarity/instrument/
    dataset_profile/files.sample_metadata, which are per-experiment."""
    return load_config_defaults()


@router.get("/{study_id}/raw-files", response_model=RawFileScanResult)
async def get_raw_files(study_id: str):
    """Step 1 of the intake wizard: scan raw_data/{study_id}/ for
    .mzML/.mzXML files and return candidate sample_ids. Deliberately
    doesn't require the study to exist yet."""
    return scan_raw_dir(study_id)


@router.post("", response_model=StudyCreateResult)
async def create_study(payload: StudyCreateRequest):
    try:
        return await asyncio.to_thread(
            create_study_files_and_ingest, payload.config, payload.sample_rows
        )
    except StudyCreateError as exc:
        raise HTTPException(status_code=400, detail=exc.errors) from exc


@router.get("/{study_id}/sample-readiness", response_model=SampleReadiness)
async def get_sample_readiness_route(experiment: ExperimentDep, session: SessionDep):
    return await get_sample_readiness(experiment.study_id, experiment.id, session)
