from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="RetrievalFeedback")


@_attrs_define
class RetrievalFeedback:
    """
    Attributes:
        correct (bool | None):
        created_at (None | str):
        useful (bool | None):
    """

    correct: bool | None
    created_at: None | str
    useful: bool | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        correct: bool | None
        correct = self.correct

        created_at: None | str
        created_at = self.created_at

        useful: bool | None
        useful = self.useful

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "correct": correct,
                "created_at": created_at,
                "useful": useful,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_correct(data: object) -> bool | None:
            if data is None:
                return data
            return cast(bool | None, data)

        correct = _parse_correct(d.pop("correct"))

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        def _parse_useful(data: object) -> bool | None:
            if data is None:
                return data
            return cast(bool | None, data)

        useful = _parse_useful(d.pop("useful"))

        retrieval_feedback = cls(
            correct=correct,
            created_at=created_at,
            useful=useful,
        )

        retrieval_feedback.additional_properties = d
        return retrieval_feedback

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
