from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_async_session
from core.models import Experiment

SessionDep = Annotated[AsyncSession, Depends(get_async_session)]


async def get_experiment_or_404(study_id: str, session: SessionDep) -> Experiment:
    result = await session.execute(select(Experiment).where(Experiment.study_id == study_id))
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail=f"unknown study_id: {study_id}")
    return experiment


ExperimentDep = Annotated[Experiment, Depends(get_experiment_or_404)]
