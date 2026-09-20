from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.principal_view_auth_kind import PrincipalViewAuthKind
from ..models.principal_view_role import PrincipalViewRole

if TYPE_CHECKING:
    from ..models.scope_view import ScopeView


T = TypeVar("T", bound="PrincipalView")


@_attrs_define
class PrincipalView:
    """
    Attributes:
        auth_kind (PrincipalViewAuthKind):
        display_name (str):
        handle (str):
        id (str):
        own_entity_id (str):
        role (PrincipalViewRole):
        scopes (list[ScopeView]):
        team_entity_id (None | str):
    """

    auth_kind: PrincipalViewAuthKind
    display_name: str
    handle: str
    id: str
    own_entity_id: str
    role: PrincipalViewRole
    scopes: list[ScopeView]
    team_entity_id: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        auth_kind = self.auth_kind.value

        display_name = self.display_name

        handle = self.handle

        id = self.id

        own_entity_id = self.own_entity_id

        role = self.role.value

        scopes = []
        for scopes_item_data in self.scopes:
            scopes_item = scopes_item_data.to_dict()
            scopes.append(scopes_item)

        team_entity_id: None | str
        team_entity_id = self.team_entity_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "auth_kind": auth_kind,
                "display_name": display_name,
                "handle": handle,
                "id": id,
                "own_entity_id": own_entity_id,
                "role": role,
                "scopes": scopes,
                "team_entity_id": team_entity_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.scope_view import ScopeView

        d = dict(src_dict)
        auth_kind = PrincipalViewAuthKind(d.pop("auth_kind"))

        display_name = d.pop("display_name")

        handle = d.pop("handle")

        id = d.pop("id")

        own_entity_id = d.pop("own_entity_id")

        role = PrincipalViewRole(d.pop("role"))

        scopes = []
        _scopes = d.pop("scopes")
        for scopes_item_data in _scopes:
            scopes_item = ScopeView.from_dict(scopes_item_data)

            scopes.append(scopes_item)

        def _parse_team_entity_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        team_entity_id = _parse_team_entity_id(d.pop("team_entity_id"))

        principal_view = cls(
            auth_kind=auth_kind,
            display_name=display_name,
            handle=handle,
            id=id,
            own_entity_id=own_entity_id,
            role=role,
            scopes=scopes,
            team_entity_id=team_entity_id,
        )

        principal_view.additional_properties = d
        return principal_view

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
