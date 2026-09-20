from enum import Enum


class ProfileMemoryReviewStatus(str, Enum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    PENDING = "pending"

    def __str__(self) -> str:
        return str(self.value)
