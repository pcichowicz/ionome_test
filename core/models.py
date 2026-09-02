from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Enum as SQLEnum
from sqlalchemy.orm import relationship
from datetime import datetime, UTC
from core.status import STATUS
from core.declarative_base import Base

class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(Integer, primary_key = True)
    study_id = Column(String,unique = True , nullable = False)
    created_at = Column(DateTime, default = lambda: datetime.now(UTC))
    config_path = Column(String,nullable = False)
    status = Column(SQLEnum(STATUS), default=STATUS.PENDING)

    samples = relationship("Sample", back_populates="experiment")

class Sample(Base):
    __tablename__ = "samples"

    id = Column(Integer, primary_key = True, index = True)

    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable = False)
    sample_id = Column(String, index = True, nullable = False)
    description = Column(String)

    status = Column(SQLEnum(STATUS), default=STATUS.PENDING, nullable = False, index=True)

    raw_file_path = Column(String, nullable = False)
    checksum = Column(String, nullable = False)

    ingested_at = Column(DateTime, default = lambda: datetime.now(UTC))

    experiment = relationship("Experiment", back_populates="samples")

    @property
    def label(self) -> str:
        return f"Add in later, might be useful for something"

    __table_args__ = (
        UniqueConstraint(
            "experiment_id",
            "sample_id",
            name="study_id_sample_id"
        ),
    )

class Pipeline(Base):
    __tablename__ = "pipeline_runs"
    id = Column(Integer, primary_key = True, index = True)

    run_id = Column(String, index = True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable = False)
    step_name = Column(String, nullable = False)
    status = Column(SQLEnum(STATUS), default=STATUS.PENDING, nullable = False)
    started_at = Column(DateTime, default = lambda: datetime.now(UTC))
    finished_at = Column(DateTime)
    error_msg = Column(String)