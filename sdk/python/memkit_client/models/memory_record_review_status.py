from enum import Enum


class MemoryRecordReviewStatus(str, Enum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    PENDING = "pending"

    def __str__(self) -> str:
        return str(self.value)
