from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file = PROJECT_ROOT / ".env",
        env_file_encoding = "utf-8",
        populate_by_name = True,
        )

    env: str = "development"
    pipeline_name: str = Field(..., alias="PIPELINE_NAME")

    storage_backend: str = Field("local", alias="STORAGE_BACKEND")

    lcms_raw_data_dir: Path = Field(..., alias="LCMS_RAW_DATA_DIR")
    lcms_results_dir: Path = Field(..., alias="LCMS_RESULTS_DIR")
    lcms_reference_library_dir: Path = Field(..., alias="LCMS_REFERENCE_LIBRARY_DIR")
    yaml_dir: Path = Field(..., alias="YAML_DIR")
    output_dirs: list[str] = Field(..., alias="OUTPUT_DIRS")

    aws_s3_bucket: str | None = Field(None, alias="AWS_S3_BUCKET")
    aws_region: str | None = Field(None, alias="AWS_REGION")

    lcms_db_name:str = Field(..., alias="LCMS_DB_NAME")
    lcms_db_path: Path = Field(..., alias="LCMS_DB_PATH")
    lcms_db_echo: bool = Field(False, alias="LCMS_DB_ECHO")

    api_host: str = Field("0.0.0.0", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")
    api_reload: bool = Field(..., alias="API_RELOAD")

    lcms_max_workers: int = Field(4, alias="LCMS_MAX_WORKERS")
    lcms_cache_enabled:bool = Field(True, alias="LCMS_CACHE_ENABLED")

    log_level: str = Field("INFO", alias="LOG_LEVEL")
    api_log_info: str = "info"
    log_format: str = "json"

    @property
    def db_url(self):
        return f"sqlite+aiosqlite:///{self.lcms_db_path}"

    # class ConfigDict:
    #     env_file = PROJECT_ROOT / ".env"
    #     env_file_encoding = "utf-8"
    #     populate_by_name = True

    def model_post_init(self, __context) -> None:
        #cross validation, things that depend on more than one var
        if self.storage_backend == "s3" and not self.aws_s3_bucket:
            raise ValueError("AWS_S3_BUCKET is required when STORAGE_BACKEND=s3")

settings = Settings()