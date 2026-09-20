from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.entity_view_kind import EntityViewKind
from ..models.entity_view_visibility import EntityViewVisibility
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.entity_member_view import EntityMemberView


T = TypeVar("T", bound="EntityView")


@_attrs_define
class EntityView:
    """
    Attributes:
        aliases (list[str]):
        archived_at (None | str):
        created_at (None | str):
        description (str):
        id (str):
        kind (EntityViewKind):
        name (str):
        slug (str):
        visibility (EntityViewVisibility):
        writable (bool):
        members (list[EntityMemberView] | Unset):
    """

    aliases: list[str]
    archived_at: None | str
    created_at: None | str
    description: str
    id: str
    kind: EntityViewKind
    name: str
    slug: str
    visibility: EntityViewVisibility
    writable: bool
    members: list[EntityMemberView] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        aliases = self.aliases

        archived_at: None | str
        archived_at = self.archived_at

        created_at: None | str
        created_at = self.created_at

        description = self.description

        id = self.id

        kind = self.kind.value

        name = self.name

        slug = self.slug

        visibility = self.visibility.value

        writable = self.writable

        members: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.members, Unset):
            members = []
            for members_item_data in self.members:
                members_item = members_item_data.to_dict()
                members.append(members_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "aliases": aliases,
                "archived_at": archived_at,
                "created_at": created_at,
                "description": description,
                "id": id,
                "kind": kind,
                "name": name,
                "slug": slug,
                "visibility": visibility,
                "writable": writable,
            }
        )
        if members is not UNSET:
            field_dict["members"] = members

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.entity_member_view import EntityMemberView

        d = dict(src_dict)
        aliases = cast(list[str], d.pop("aliases"))

        def _parse_archived_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        archived_at = _parse_archived_at(d.pop("archived_at"))

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        description = d.pop("description")

        id = d.pop("id")

        kind = EntityViewKind(d.pop("kind"))

        name = d.pop("name")

        slug = d.pop("slug")

        visibility = EntityViewVisibility(d.pop("visibility"))

        writable = d.pop("writable")

        _members = d.pop("members", UNSET)
        members: list[EntityMemberView] | Unset = UNSET
        if _members is not UNSET:
            members = []
            for members_item_data in _members:
                members_item = EntityMemberView.from_dict(members_item_data)

                members.append(members_item)

        entity_view = cls(
            aliases=aliases,
            archived_at=archived_at,
            created_at=created_at,
            description=description,
            id=id,
            kind=kind,
            name=name,
            slug=slug,
            visibility=visibility,
            writable=writable,
            members=members,
        )

        entity_view.additional_properties = d
        return entity_view

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
