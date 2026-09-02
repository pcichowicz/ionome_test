import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.deps import ExperimentDep
from api.schemas.run import RunStartResult, RunStepOut
from api.services.runs import execute_pipeline_run
from core.db import SyncSessionLocal
from core.models import Pipeline

router = APIRouter(prefix="/studies/{study_id}", tags=["runs"])


@router.post("/run", response_model=RunStartResult)
async def run_study(experiment: ExperimentDep, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    background_tasks.add_task(execute_pipeline_run, experiment.study_id, experiment.id, run_id)
    return RunStartResult(study_id=experiment.study_id, run_id=run_id, status="PENDING")


@router.get("/status")
async def get_status(experiment: ExperimentDep):
    return {
        "study_id": experiment.study_id,
        "status": experiment.status.value,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
    }


@router.get("/runs/{run_id}", response_model=list[RunStepOut])
async def get_run_status(experiment: ExperimentDep, run_id: str):
    with SyncSessionLocal() as session:
        rows = (
            session.query(Pipeline)
            .filter(Pipeline.run_id == run_id, Pipeline.experiment_id == experiment.id)
            .order_by(Pipeline.started_at)
            .all()
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"unknown run_id: {run_id}")
    return [
        RunStepOut(
            step_name=r.step_name,
            status=r.status.value,
            error_msg=r.error_msg,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in rows
    ]
