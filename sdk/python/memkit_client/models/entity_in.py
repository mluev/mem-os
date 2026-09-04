from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.entity_in_kind import EntityInKind
from ..models.entity_in_visibility import EntityInVisibility
from ..types import UNSET, Unset

T = TypeVar("T", bound="EntityIn")


@_attrs_define
class EntityIn:
    """
    Attributes:
        kind (EntityInKind):
        name (str):
        aliases (list[str] | Unset):
        description (str | Unset):  Default: ''.
        slug (None | str | Unset):
        visibility (EntityInVisibility | Unset):  Default: EntityInVisibility.MEMBERS.
    """

    kind: EntityInKind
    name: str
    aliases: list[str] | Unset = UNSET
    description: str | Unset = ""
    slug: None | str | Unset = UNSET
    visibility: EntityInVisibility | Unset = EntityInVisibility.MEMBERS

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind.value

        name = self.name

        aliases: list[str] | Unset = UNSET
        if not isinstance(self.aliases, Unset):
            aliases = self.aliases

        description = self.description

        slug: None | str | Unset
        if isinstance(self.slug, Unset):
            slug = UNSET
        else:
            slug = self.slug

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "name": name,
            }
        )
        if aliases is not UNSET:
            field_dict["aliases"] = aliases
        if description is not UNSET:
            field_dict["description"] = description
        if slug is not UNSET:
            field_dict["slug"] = slug
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        kind = EntityInKind(d.pop("kind"))

        name = d.pop("name")

        aliases = cast(list[str], d.pop("aliases", UNSET))

        description = d.pop("description", UNSET)

        def _parse_slug(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        slug = _parse_slug(d.pop("slug", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: EntityInVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = EntityInVisibility(_visibility)

        entity_in = cls(
            kind=kind,
            name=name,
            aliases=aliases,
            description=description,
            slug=slug,
            visibility=visibility,
        )

        return entity_in
