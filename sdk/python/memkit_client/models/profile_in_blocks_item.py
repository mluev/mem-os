from enum import Enum


class ProfileInBlocksItem(str, Enum):
    ABOUT = "about"
    PROJECT = "project"
    RECENT = "recent"
    STYLE = "style"
    TEAM = "team"

    def __str__(self) -> str:
        return str(self.value)
