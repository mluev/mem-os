from enum import Enum


class MemberInRole(str, Enum):
    MEMBER = "member"
    OWNER = "owner"
    VIEWER = "viewer"

    def __str__(self) -> str:
        return str(self.value)
