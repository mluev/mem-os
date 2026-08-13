from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="FeedbackOut")


@_attrs_define
class FeedbackOut:
    """
    Attributes:
        recorded (bool):
    """

    recorded: bool

    def to_dict(self) -> dict[str, Any]:
        recorded = self.recorded

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "recorded": recorded,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        recorded = d.pop("recorded")

        feedback_out = cls(
            recorded=recorded,
        )

        return feedback_out
