from datetime import datetime
from pydantic import BaseModel


class SampleOut(BaseModel):
    sample_id: str
    description: str | None
    status: str
    checksum: str
    ingested_at: datetime | None
