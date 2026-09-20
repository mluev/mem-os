from enum import Enum


class EntityInKind(str, Enum):
    COMPANY = "company"
    CUSTOM = "custom"
    PERSON = "person"
    PRODUCT = "product"
    PROJECT = "project"

    def __str__(self) -> str:
        return str(self.value)
