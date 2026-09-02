from datetime import datetime
from pydantic import BaseModel


class RunStepOut(BaseModel):
    step_name: str
    status: str
    error_msg: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunStartResult(BaseModel):
    study_id: str
    run_id: str
    status: str
