from enum import Enum


class PolicyInKind(str, Enum):
    CONSOLIDATION = "consolidation"
    EXTRACTION = "extraction"
    RETENTION = "retention"
    RETRIEVAL = "retrieval"

    def __str__(self) -> str:
        return str(self.value)
