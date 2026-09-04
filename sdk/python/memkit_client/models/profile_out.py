from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.profile_out_blocks import ProfileOutBlocks


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
    """

    blocks: ProfileOutBlocks
    budget_tokens: int
    generated_at: str
    policy_id: str
    used_tokens: int

    def to_dict(self) -> dict[str, Any]:
        blocks = self.blocks.to_dict()

        budget_tokens = self.budget_tokens

        generated_at = self.generated_at

        policy_id = self.policy_id

        used_tokens = self.used_tokens

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

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.profile_out_blocks import ProfileOutBlocks

        d = dict(src_dict)
        blocks = ProfileOutBlocks.from_dict(d.pop("blocks"))

        budget_tokens = d.pop("budget_tokens")

        generated_at = d.pop("generated_at")

        policy_id = d.pop("policy_id")

        used_tokens = d.pop("used_tokens")

        profile_out = cls(
            blocks=blocks,
            budget_tokens=budget_tokens,
            generated_at=generated_at,
            policy_id=policy_id,
            used_tokens=used_tokens,
        )

        return profile_out
