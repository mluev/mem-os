from enum import Enum


class EntityViewVisibility(str, Enum):
    MEMBERS = "members"
    TEAM = "team"

    def __str__(self) -> str:
        return str(self.value)
