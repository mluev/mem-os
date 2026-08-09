from enum import Enum


class ListJobsV1JobsGetStatusType0(str, Enum):
    CANCELLED = "cancelled"
    COMPLETE = "complete"
    FAILED = "failed"
    QUEUED = "queued"
    RUNNING = "running"

    def __str__(self) -> str:
        return str(self.value)
