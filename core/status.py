from enum import Enum

class STATUS(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    DONE = "DONE"
    FAILED = "FAILED"