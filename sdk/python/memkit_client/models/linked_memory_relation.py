from enum import Enum


class LinkedMemoryRelation(str, Enum):
    DERIVED_FROM = "derived_from"
    EXTENDED_BY = "extended_by"
    EXTENDS = "extends"
    PREMISE_OF = "premise_of"
    REPLACED_BY = "replaced_by"
    REPLACES = "replaces"

    def __str__(self) -> str:
        return str(self.value)
