from enum import Enum


class MessageInRole(str, Enum):
    ASSISTANT = "assistant"
    TOOL = "tool"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
