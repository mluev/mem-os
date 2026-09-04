from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.attention_resolve_in_action import AttentionResolveInAction
from ..types import UNSET, Unset

T = TypeVar("T", bound="AttentionResolveIn")


@_attrs_define
class AttentionResolveIn:
    """
    Attributes:
        action (AttentionResolveInAction):
        entity (None | str | Unset):
    """

    action: AttentionResolveInAction
    entity: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        action = self.action.value

        entity: None | str | Unset
        if isinstance(self.entity, Unset):
            entity = UNSET
        else:
            entity = self.entity

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "action": action,
            }
        )
        if entity is not UNSET:
            field_dict["entity"] = entity

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        action = AttentionResolveInAction(d.pop("action"))

        def _parse_entity(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        entity = _parse_entity(d.pop("entity", UNSET))

        attention_resolve_in = cls(
            action=action,
            entity=entity,
        )

        return attention_resolve_in
