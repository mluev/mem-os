from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.entity_patch_visibility_type_0 import EntityPatchVisibilityType0
from ..types import UNSET, Unset

T = TypeVar("T", bound="EntityPatch")


@_attrs_define
class EntityPatch:
    """
    Attributes:
        description (None | str | Unset):
        name (None | str | Unset):
        visibility (EntityPatchVisibilityType0 | None | Unset):
    """

    description: None | str | Unset = UNSET
    name: None | str | Unset = UNSET
    visibility: EntityPatchVisibilityType0 | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, EntityPatchVisibilityType0):
            visibility = self.visibility.value
        else:
            visibility = self.visibility

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if description is not UNSET:
            field_dict["description"] = description
        if name is not UNSET:
            field_dict["name"] = name
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_visibility(data: object) -> EntityPatchVisibilityType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = EntityPatchVisibilityType0(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EntityPatchVisibilityType0 | None | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        entity_patch = cls(
            description=description,
            name=name,
            visibility=visibility,
        )

        return entity_patch
