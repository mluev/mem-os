from enum import Enum


class SearchMemoryReviewStatus(str, Enum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    PENDING = "pending"

    def __str__(self) -> str:
        return str(self.value)
