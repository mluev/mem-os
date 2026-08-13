from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.profile_out_dynamic_item import ProfileOutDynamicItem
    from ..models.profile_out_stable_item import ProfileOutStableItem


T = TypeVar("T", bound="ProfileOut")


@_attrs_define
class ProfileOut:
    """
    Attributes:
        dynamic (list[ProfileOutDynamicItem]):
        generated_at (str):
        policy_id (str):
        stable (list[ProfileOutStableItem]):
        used_tokens (int):
    """

    dynamic: list[ProfileOutDynamicItem]
    generated_at: str
    policy_id: str
    stable: list[ProfileOutStableItem]
    used_tokens: int

    def to_dict(self) -> dict[str, Any]:
        dynamic = []
        for dynamic_item_data in self.dynamic:
            dynamic_item = dynamic_item_data.to_dict()
            dynamic.append(dynamic_item)

        generated_at = self.generated_at

        policy_id = self.policy_id

        stable = []
        for stable_item_data in self.stable:
            stable_item = stable_item_data.to_dict()
            stable.append(stable_item)

        used_tokens = self.used_tokens

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "dynamic": dynamic,
                "generated_at": generated_at,
                "policy_id": policy_id,
                "stable": stable,
                "used_tokens": used_tokens,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.profile_out_dynamic_item import ProfileOutDynamicItem
        from ..models.profile_out_stable_item import ProfileOutStableItem

        d = dict(src_dict)
        dynamic = []
        _dynamic = d.pop("dynamic")
        for dynamic_item_data in _dynamic:
            dynamic_item = ProfileOutDynamicItem.from_dict(dynamic_item_data)

            dynamic.append(dynamic_item)

        generated_at = d.pop("generated_at")

        policy_id = d.pop("policy_id")

        stable = []
        _stable = d.pop("stable")
        for stable_item_data in _stable:
            stable_item = ProfileOutStableItem.from_dict(stable_item_data)

            stable.append(stable_item)

        used_tokens = d.pop("used_tokens")

        profile_out = cls(
            dynamic=dynamic,
            generated_at=generated_at,
            policy_id=policy_id,
            stable=stable,
            used_tokens=used_tokens,
        )

        return profile_out
