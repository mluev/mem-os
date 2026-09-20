from enum import Enum


class ReviewItemKind(str, Enum):
    BUDGET = "budget"
    CONFLICT = "conflict"
    FAILED_JOB = "failed_job"
    MEMORY = "memory"
    UNRESOLVED_MENTION = "unresolved_mention"

    def __str__(self) -> str:
        return str(self.value)
