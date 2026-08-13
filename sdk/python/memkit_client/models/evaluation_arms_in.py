from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="EvaluationArmsIn")


@_attrs_define
class EvaluationArmsIn:
    """
    Attributes:
        current_memory (str):
        no_memory (str):
        oracle_memory (str):
        reviewed_v7 (str):
    """

    current_memory: str
    no_memory: str
    oracle_memory: str
    reviewed_v7: str

    def to_dict(self) -> dict[str, Any]:
        current_memory = self.current_memory

        no_memory = self.no_memory

        oracle_memory = self.oracle_memory

        reviewed_v7 = self.reviewed_v7

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "current_memory": current_memory,
                "no_memory": no_memory,
                "oracle_memory": oracle_memory,
                "reviewed_v7": reviewed_v7,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        current_memory = d.pop("current_memory")

        no_memory = d.pop("no_memory")

        oracle_memory = d.pop("oracle_memory")

        reviewed_v7 = d.pop("reviewed_v7")

        evaluation_arms_in = cls(
            current_memory=current_memory,
            no_memory=no_memory,
            oracle_memory=oracle_memory,
            reviewed_v7=reviewed_v7,
        )

        return evaluation_arms_in
