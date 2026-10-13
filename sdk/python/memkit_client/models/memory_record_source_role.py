from enum import Enum


class MemoryRecordSourceRole(str, Enum):
    AGENT = "agent"
    ASSISTANT = "assistant"
    INFERENCE = "inference"
    MANUAL = "manual"
    TOOL = "tool"
    USER = "user"

    def __str__(self) -> str:
        return str(self.value)
