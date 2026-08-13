from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="RetrievalRunFeedbackIn")


@_attrs_define
class RetrievalRunFeedbackIn:
    """
    Attributes:
        memory_id (str):
        correct (bool | None | Unset):
        useful (bool | None | Unset):
    """

    memory_id: str
    correct: bool | None | Unset = UNSET
    useful: bool | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        memory_id = self.memory_id

        correct: bool | None | Unset
        if isinstance(self.correct, Unset):
            correct = UNSET
        else:
            correct = self.correct

        useful: bool | None | Unset
        if isinstance(self.useful, Unset):
            useful = UNSET
        else:
            useful = self.useful

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "memory_id": memory_id,
            }
        )
        if correct is not UNSET:
            field_dict["correct"] = correct
        if useful is not UNSET:
            field_dict["useful"] = useful

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        memory_id = d.pop("memory_id")

        def _parse_correct(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        correct = _parse_correct(d.pop("correct", UNSET))

        def _parse_useful(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        useful = _parse_useful(d.pop("useful", UNSET))

        retrieval_run_feedback_in = cls(
            memory_id=memory_id,
            correct=correct,
            useful=useful,
        )

        return retrieval_run_feedback_in
