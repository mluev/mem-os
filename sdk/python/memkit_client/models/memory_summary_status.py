from enum import Enum


class MemorySummaryStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"

    def __str__(self) -> str:
        return str(self.value)
