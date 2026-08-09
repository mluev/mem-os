from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ProfileIn")


@_attrs_define
class ProfileIn:
    """
    Attributes:
        budget_tokens (int | Unset):  Default: 800.
        dynamic_days (int | Unset):  Default: 30.
        include_untrusted (bool | Unset):  Default: False.
        stable_kinds (list[str] | Unset):
    """

    budget_tokens: int | Unset = 800
    dynamic_days: int | Unset = 30
    include_untrusted: bool | Unset = False
    stable_kinds: list[str] | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        budget_tokens = self.budget_tokens

        dynamic_days = self.dynamic_days

        include_untrusted = self.include_untrusted

        stable_kinds: list[str] | Unset = UNSET
        if not isinstance(self.stable_kinds, Unset):
            stable_kinds = self.stable_kinds

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if budget_tokens is not UNSET:
            field_dict["budget_tokens"] = budget_tokens
        if dynamic_days is not UNSET:
            field_dict["dynamic_days"] = dynamic_days
        if include_untrusted is not UNSET:
            field_dict["include_untrusted"] = include_untrusted
        if stable_kinds is not UNSET:
            field_dict["stable_kinds"] = stable_kinds

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        budget_tokens = d.pop("budget_tokens", UNSET)

        dynamic_days = d.pop("dynamic_days", UNSET)

        include_untrusted = d.pop("include_untrusted", UNSET)

        stable_kinds = cast(list[str], d.pop("stable_kinds", UNSET))

        profile_in = cls(
            budget_tokens=budget_tokens,
            dynamic_days=dynamic_days,
            include_untrusted=include_untrusted,
            stable_kinds=stable_kinds,
        )

        return profile_in
