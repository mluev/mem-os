from enum import Enum


class MessageOutIndexStatus(str, Enum):
    COMPLETE = "complete"
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"

    def __str__(self) -> str:
        return str(self.value)
