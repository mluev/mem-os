from enum import Enum


class UserInRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"

    def __str__(self) -> str:
        return str(self.value)
