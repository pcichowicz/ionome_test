from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import json

from api.deps import ExperimentDep, SessionDep
from api.schemas.results import PlotInfo, RunSummary, TablePreview
from api.services.results import (
    get_table_preview,
    list_plots,
    list_runs,
    resolve_plot_file,
    resolve_qc_report_path,
    resolve_table_csv_path,
)

router = APIRouter(prefix="/studies/{study_id}/results", tags=["results"])


@router.get("/qc-report")
async def get_qc_report(experiment: ExperimentDep):
    path = resolve_qc_report_path(experiment.study_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no qc_report found for study_id: {experiment.study_id}")
    return json.loads(path.read_text())


@router.get("/table/preview", response_model=TablePreview)
async def get_table_preview_route(experiment: ExperimentDep):
    preview = get_table_preview(experiment.study_id)
    if preview is None:
        raise HTTPException(status_code=404, detail=f"no feature table / library found for study_id: {experiment.study_id}")
    return preview


@router.get("/table.csv")
async def get_table_csv(experiment: ExperimentDep):
    path = resolve_table_csv_path(experiment.study_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no feature table / library found for study_id: {experiment.study_id}")
    return FileResponse(path, media_type="text/csv", filename=f"{experiment.study_id}_{path.name}")


@router.get("/plots", response_model=list[PlotInfo])
async def get_plots(experiment: ExperimentDep):
    return list_plots(experiment.study_id)


@router.get("/plots/{category}/{filename}")
async def get_plot_file(experiment: ExperimentDep, category: str, filename: str):
    path = resolve_plot_file(experiment.study_id, category, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="plot not found")
    return FileResponse(path, media_type="image/png")


@router.get("/runs", response_model=list[RunSummary])
async def get_runs(experiment: ExperimentDep, session: SessionDep):
    return await list_runs(experiment.id, session)
