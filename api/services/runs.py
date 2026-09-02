import asyncio
from datetime import datetime, UTC

from sqlalchemy import select

from core.db import async_session_maker, SyncSessionLocal
from core.models import Experiment, Pipeline, Sample
from core.status import STATUS
from analysis.pipeline_orchestrator import run_pipeline_for_study


def make_stage_event_recorder(run_id: str, experiment_pk: int):
    def _on_stage_event(stage_name: str, status: str, error_msg: str | None):
        with SyncSessionLocal() as session:
            row = Pipeline(
                run_id=run_id,
                experiment_id=experiment_pk,
                step_name=stage_name,
                status=STATUS[status],
                error_msg=error_msg,
            )
            if status in ("SUCCESS", "FAILED"):
                row.finished_at = datetime.now(UTC)
            session.add(row)
            session.commit()
    return _on_stage_event


async def set_experiment_status(study_id: str, status: STATUS) -> None:
    async with async_session_maker() as session:
        result = await session.execute(select(Experiment).where(Experiment.study_id == study_id))
        experiment = result.scalar_one_or_none()
        if experiment is not None:
            experiment.status = status
            await session.commit()


def mark_samples(experiment_pk: int, status: STATUS, sample_ids: list[str] | None = None) -> None:
    with SyncSessionLocal() as session:
        query = session.query(Sample).filter(Sample.experiment_id == experiment_pk)
        if sample_ids is not None:
            query = query.filter(Sample.sample_id.in_(sample_ids))
        query.update({Sample.status: status}, synchronize_session=False)
        session.commit()


def execute_pipeline_run(study_id: str, experiment_pk: int, run_id: str) -> None:
    """The BackgroundTasks target for POST /studies/{id}/run. Always runs
    the full dataset-profile batch for the study (cohort-wide stages like
    alignment/stats aren't per-sample, so there's no partial-rerun mode --
    see project notes); every sample gets re-marked RUNNING regardless of
    its prior status."""
    asyncio.run(set_experiment_status(study_id, STATUS.RUNNING))
    mark_samples(experiment_pk, STATUS.RUNNING)

    on_event = make_stage_event_recorder(run_id, experiment_pk)
    try:
        context = run_pipeline_for_study(study_id, on_stage_event=on_event)
    except Exception:
        asyncio.run(set_experiment_status(study_id, STATUS.FAILED))
        mark_samples(experiment_pk, STATUS.FAILED)
        return

    asyncio.run(set_experiment_status(study_id, STATUS.SUCCESS))

    missing = context.qc_metrics.get("ingestion", {}).get("missing_sample_ids", [])
    all_ids = list(context.sample_metadata["sample_id"])
    found_ids = [sid for sid in all_ids if sid not in missing]

    if missing:
        mark_samples(experiment_pk, STATUS.FAILED, sample_ids=missing)
    mark_samples(experiment_pk, STATUS.SUCCESS, sample_ids=found_ids)
