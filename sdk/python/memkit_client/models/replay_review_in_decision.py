from enum import Enum


class ReplayReviewInDecision(str, Enum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"

    def __str__(self) -> str:
        return str(self.value)
