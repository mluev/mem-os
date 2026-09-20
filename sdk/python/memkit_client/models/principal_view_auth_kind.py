from enum import Enum


class PrincipalViewAuthKind(str, Enum):
    API_KEY = "api_key"
    SESSION = "session"

    def __str__(self) -> str:
        return str(self.value)
