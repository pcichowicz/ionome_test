import os
from abc import ABC, abstractmethod
from pathlib import Path

class StorageBackend(ABC):
    @abstractmethod
    def get_path(self, key: str) -> Path:
        ...
    @abstractmethod
    def put(self, local_path: Path, key: str) -> None:
        ...
    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

class LocalStorage(StorageBackend):
    def __init__(self, root: Path):
        self._root = root
    def get_path(self, key: str) -> Path:
        return self._root / key
    def put(self, local_path, key):
        destination = self.get_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(local_path.read_bytes())
    def exists(self, key: str) -> bool:
        return self.get_path(key).exists()

class S3Storage(StorageBackend):
    def __init__(self, bucket, region):
        self._bucket = bucket
        self._region = region
    def get_path(self, key: str) -> Path:
        return self._bucket
    def put(self, local_path, key):
        destination = self.get_path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(local_path.read_bytes())
    def exists(self, key: str) -> bool:
        return self.get_path(key).exists()


def get_storage() -> StorageBackend:
    backend = os.environ.get("STORAGE_BACKEND", "local")
    if backend == "s3":
        return S3Storage(bucket = os.environ["AWS_S3_BUCKET"], region = os.environ["AWS_S3_REGION"])
    return LocalStorage(root = os.environ["LCMS_RAW_DATA_DIR"])