from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="ForgetCandidate")


@_attrs_define
class ForgetCandidate:
    """
    Attributes:
        id (str):
        scope (None | str):
        score (float):
        text (str):
    """

    id: str
    scope: None | str
    score: float
    text: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        scope: None | str
        scope = self.scope

        score = self.score

        text = self.text

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "scope": scope,
                "score": score,
                "text": text,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        def _parse_scope(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        scope = _parse_scope(d.pop("scope"))

        score = d.pop("score")

        text = d.pop("text")

        forget_candidate = cls(
            id=id,
            scope=scope,
            score=score,
            text=text,
        )

        forget_candidate.additional_properties = d
        return forget_candidate

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
