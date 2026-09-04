from enum import Enum


class AttentionResolveInAction(str, Enum):
    DISMISS = "dismiss"
    LINK_ENTITY = "link_entity"

    def __str__(self) -> str:
        return str(self.value)
