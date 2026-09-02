import os
from pathlib import Path
from core.settings import settings

PROJECT_PATH = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = Path(os.environ.get("LCMS_RAW_DATA_DIR", PROJECT_PATH / "raw_data"))
RESULTS_DIR = Path(os.environ.get("LCMS_RESULTS_DIR", PROJECT_PATH / "results"))
RESULT_SUBDIRS = ["features", "logs", "plots", "library", "qc_reports", "cache"]

def experiment_dir(study_id: str, subdir:str | None = None) -> Path:
    d = settings.lcms_results_dir / study_id
    d = d / subdir if subdir else d
    d.mkdir(parents=True, exist_ok=True)
    return d