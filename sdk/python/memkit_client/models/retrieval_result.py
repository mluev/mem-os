from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.retrieval_feedback import RetrievalFeedback


T = TypeVar("T", bound="RetrievalResult")


@_attrs_define
class RetrievalResult:
    """
    Attributes:
        feedback (None | RetrievalFeedback):
        memory_id (str):
        rank (int):
        kind (str | Unset):
        source_role (str | Unset):
        text (str | Unset):
    """

    feedback: None | RetrievalFeedback
    memory_id: str
    rank: int
    kind: str | Unset = UNSET
    source_role: str | Unset = UNSET
    text: str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.retrieval_feedback import RetrievalFeedback

        feedback: dict[str, Any] | None
        if isinstance(self.feedback, RetrievalFeedback):
            feedback = self.feedback.to_dict()
        else:
            feedback = self.feedback

        memory_id = self.memory_id

        rank = self.rank

        kind = self.kind

        source_role = self.source_role

        text = self.text

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "feedback": feedback,
                "memory_id": memory_id,
                "rank": rank,
            }
        )
        if kind is not UNSET:
            field_dict["kind"] = kind
        if source_role is not UNSET:
            field_dict["source_role"] = source_role
        if text is not UNSET:
            field_dict["text"] = text

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.retrieval_feedback import RetrievalFeedback

        d = dict(src_dict)

        def _parse_feedback(data: object) -> None | RetrievalFeedback:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                feedback_type_0 = RetrievalFeedback.from_dict(data)

                return feedback_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RetrievalFeedback, data)

        feedback = _parse_feedback(d.pop("feedback"))

        memory_id = d.pop("memory_id")

        rank = d.pop("rank")

        kind = d.pop("kind", UNSET)

        source_role = d.pop("source_role", UNSET)

        text = d.pop("text", UNSET)

        retrieval_result = cls(
            feedback=feedback,
            memory_id=memory_id,
            rank=rank,
            kind=kind,
            source_role=source_role,
            text=text,
        )

        retrieval_result.additional_properties = d
        return retrieval_result

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
