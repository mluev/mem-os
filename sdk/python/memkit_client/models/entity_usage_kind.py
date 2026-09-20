from enum import Enum


class EntityUsageKind(str, Enum):
    COMPANY = "company"
    CUSTOM = "custom"
    PERSON = "person"
    PRODUCT = "product"
    PROJECT = "project"
    TEAM = "team"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
