from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.profile_out_blocks import ProfileOutBlocks
    from ..models.profile_out_scope_type_0 import ProfileOutScopeType0


T = TypeVar("T", bound="ProfileOut")


@_attrs_define
class ProfileOut:
    """
    Attributes:
        blocks (ProfileOutBlocks):
        budget_tokens (int):
        generated_at (str):
        policy_id (str):
        used_tokens (int):
        scope (None | ProfileOutScopeType0 | Unset):
    """

    blocks: ProfileOutBlocks
    budget_tokens: int
    generated_at: str
    policy_id: str
    used_tokens: int
    scope: None | ProfileOutScopeType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.profile_out_scope_type_0 import ProfileOutScopeType0

        blocks = self.blocks.to_dict()

        budget_tokens = self.budget_tokens

        generated_at = self.generated_at

        policy_id = self.policy_id

        used_tokens = self.used_tokens

        scope: dict[str, Any] | None | Unset
        if isinstance(self.scope, Unset):
            scope = UNSET
        elif isinstance(self.scope, ProfileOutScopeType0):
            scope = self.scope.to_dict()
        else:
            scope = self.scope

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "blocks": blocks,
                "budget_tokens": budget_tokens,
                "generated_at": generated_at,
                "policy_id": policy_id,
                "used_tokens": used_tokens,
            }
        )
        if scope is not UNSET:
            field_dict["scope"] = scope

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.profile_out_blocks import ProfileOutBlocks
        from ..models.profile_out_scope_type_0 import ProfileOutScopeType0

        d = dict(src_dict)
        blocks = ProfileOutBlocks.from_dict(d.pop("blocks"))

        budget_tokens = d.pop("budget_tokens")

        generated_at = d.pop("generated_at")

        policy_id = d.pop("policy_id")

        used_tokens = d.pop("used_tokens")

        def _parse_scope(data: object) -> None | ProfileOutScopeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                scope_type_0 = ProfileOutScopeType0.from_dict(data)

                return scope_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ProfileOutScopeType0 | Unset, data)

        scope = _parse_scope(d.pop("scope", UNSET))

        profile_out = cls(
            blocks=blocks,
            budget_tokens=budget_tokens,
            generated_at=generated_at,
            policy_id=policy_id,
            used_tokens=used_tokens,
            scope=scope,
        )

        return profile_out
