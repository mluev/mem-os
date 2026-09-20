from enum import Enum


class EvidenceSpanEvidenceStatus(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    LEGACY_UNVERSIONED = "legacy_unversioned"

    def __str__(self) -> str:
        return str(self.value)
