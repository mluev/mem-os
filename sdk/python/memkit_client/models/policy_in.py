from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.policy_in_kind import PolicyInKind
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.policy_in_config import PolicyInConfig


T = TypeVar("T", bound="PolicyIn")


@_attrs_define
class PolicyIn:
    """
    Attributes:
        config (PolicyInConfig):
        kind (PolicyInKind):
        name (str):
        version (int):
        scope (None | str | Unset):
    """

    config: PolicyInConfig
    kind: PolicyInKind
    name: str
    version: int
    scope: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        kind = self.kind.value

        name = self.name

        version = self.version

        scope: None | str | Unset
        if isinstance(self.scope, Unset):
            scope = UNSET
        else:
            scope = self.scope

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "config": config,
                "kind": kind,
                "name": name,
                "version": version,
            }
        )
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.policy_in_config import PolicyInConfig

        d = dict(src_dict)
        config = PolicyInConfig.from_dict(d.pop("config"))

        kind = PolicyInKind(d.pop("kind"))

        name = d.pop("name")

        version = d.pop("version")

        def _parse_scope(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope = _parse_scope(d.pop("scope", UNSET))

        policy_in = cls(
            config=config,
            kind=kind,
            name=name,
            version=version,
            scope=scope,
        )

        return policy_in
