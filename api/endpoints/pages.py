import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from api.deps import ExperimentDep, SessionDep
from api.endpoints.samples import _to_sample_out
from api.services.studies import _read_dataset_profile, list_study_summaries
from core.models import Sample

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")


@router.get("/")
async def dashboard(request: Request, session: SessionDep):
    studies = await list_study_summaries(session)
    studies_dump = [s.model_dump(mode="json") for s in studies]
    return templates.TemplateResponse(request, "dashboard.html", {
        "studies": studies_dump,
        "studies_json": json.dumps(studies_dump),
    })


@router.get("/studies/new")
async def new_study_page(request: Request):
    return templates.TemplateResponse(request, "new_study.html", {})


@router.get("/studies/{study_id}")
async def study_detail_page(request: Request, experiment: ExperimentDep):
    return templates.TemplateResponse(request, "study_detail.html", {
        "study": {
            "study_id": experiment.study_id,
            "status": experiment.status.value,
            "dataset_profile": _read_dataset_profile(experiment.config_path),
        },
    })


@router.get("/studies/{study_id}/samples/{sample_id}")
async def sample_detail_page(request: Request, experiment: ExperimentDep, sample_id: str, session: SessionDep):
    result = await session.execute(
        select(Sample).where(Sample.experiment_id == experiment.id, Sample.sample_id == sample_id)
    )
    sample = result.scalar_one_or_none()
    if sample is None:
        raise HTTPException(status_code=404, detail=f"unknown sample_id: {sample_id}")
    return templates.TemplateResponse(request, "sample_detail.html", {
        "study_id": experiment.study_id,
        "sample": _to_sample_out(sample).model_dump(mode="json"),
    })
