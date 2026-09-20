from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.memory_out_memory import MemoryOutMemory


T = TypeVar("T", bound="MemoryOut")


@_attrs_define
class MemoryOut:
    """
    Attributes:
        memory (MemoryOutMemory):
    """

    memory: MemoryOutMemory

    def to_dict(self) -> dict[str, Any]:
        memory = self.memory.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "memory": memory,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_out_memory import MemoryOutMemory

        d = dict(src_dict)
        memory = MemoryOutMemory.from_dict(d.pop("memory"))

        memory_out = cls(
            memory=memory,
        )

        return memory_out
