from enum import Enum


class ProfileMemorySourceRole(str, Enum):
    AGENT = "agent"
    ASSISTANT = "assistant"
    MANUAL = "manual"
    TOOL = "tool"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
