from enum import Enum


class ReviewInDecision(str, Enum):
    CONFIRM = "confirm"
    DECLINE = "decline"
    UNDO = "undo"

    def __str__(self) -> str:
        return str(self.value)
