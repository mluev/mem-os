from enum import Enum


class SearchEvidenceEvidenceStatus(str, Enum):
    CURRENT = "current"
    LEGACY_UNVERSIONED = "legacy_unversioned"

    def __str__(self) -> str:
        return str(self.value)
