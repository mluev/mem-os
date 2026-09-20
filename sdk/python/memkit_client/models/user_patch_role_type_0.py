from enum import Enum


class UserPatchRoleType0(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

    def __str__(self) -> str:
        return str(self.value)
