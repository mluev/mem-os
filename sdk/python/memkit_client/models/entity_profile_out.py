from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.entity_view import EntityView
    from ..models.memory_summary import MemorySummary


T = TypeVar("T", bound="EntityProfileOut")


@_attrs_define
class EntityProfileOut:
    """
    Attributes:
        about (list[MemorySummary]):
        budget_tokens (int):
        entity (EntityView):
        in_scope (list[MemorySummary]):
    """

    about: list[MemorySummary]
    budget_tokens: int
    entity: EntityView
    in_scope: list[MemorySummary]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        about = []
        for about_item_data in self.about:
            about_item = about_item_data.to_dict()
            about.append(about_item)

        budget_tokens = self.budget_tokens

        entity = self.entity.to_dict()

        in_scope = []
        for in_scope_item_data in self.in_scope:
            in_scope_item = in_scope_item_data.to_dict()
            in_scope.append(in_scope_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "about": about,
                "budget_tokens": budget_tokens,
                "entity": entity,
                "in_scope": in_scope,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.entity_view import EntityView
        from ..models.memory_summary import MemorySummary

        d = dict(src_dict)
        about = []
        _about = d.pop("about")
        for about_item_data in _about:
            about_item = MemorySummary.from_dict(about_item_data)

            about.append(about_item)

        budget_tokens = d.pop("budget_tokens")

        entity = EntityView.from_dict(d.pop("entity"))

        in_scope = []
        _in_scope = d.pop("in_scope")
        for in_scope_item_data in _in_scope:
            in_scope_item = MemorySummary.from_dict(in_scope_item_data)

            in_scope.append(in_scope_item)

        entity_profile_out = cls(
            about=about,
            budget_tokens=budget_tokens,
            entity=entity,
            in_scope=in_scope,
        )

        entity_profile_out.additional_properties = d
        return entity_profile_out

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
