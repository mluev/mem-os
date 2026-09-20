from enum import Enum


class EntityPatchVisibilityType0(str, Enum):
    MEMBERS = "members"
    TEAM = "team"

    def __str__(self) -> str:
        return str(self.value)
