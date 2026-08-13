from enum import Enum


class EvaluationReviewInCurrentVsV7(str, Enum):
    CURRENT_WIN = "current_win"
    TIE = "tie"
    V7_WIN = "v7_win"

    def __str__(self) -> str:
        return str(self.value)
