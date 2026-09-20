from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.profile_in_blocks_item import ProfileInBlocksItem
from ..types import UNSET, Unset

T = TypeVar("T", bound="ProfileIn")


@_attrs_define
class ProfileIn:
    """
    Attributes:
        blocks (list[ProfileInBlocksItem] | Unset):
        budget_tokens (int | Unset):  Default: 800.
        dynamic_days (int | Unset):  Default: 30.
        include_untrusted (bool | Unset):  Default: False.
        workspace (None | str | Unset):
    """

    blocks: list[ProfileInBlocksItem] | Unset = UNSET
    budget_tokens: int | Unset = 800
    dynamic_days: int | Unset = 30
    include_untrusted: bool | Unset = False
    workspace: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        blocks: list[str] | Unset = UNSET
        if not isinstance(self.blocks, Unset):
            blocks = []
            for blocks_item_data in self.blocks:
                blocks_item = blocks_item_data.value
                blocks.append(blocks_item)

        budget_tokens = self.budget_tokens

        dynamic_days = self.dynamic_days

        include_untrusted = self.include_untrusted

        workspace: None | str | Unset
        if isinstance(self.workspace, Unset):
            workspace = UNSET
        else:
            workspace = self.workspace

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if blocks is not UNSET:
            field_dict["blocks"] = blocks
        if budget_tokens is not UNSET:
            field_dict["budget_tokens"] = budget_tokens
        if dynamic_days is not UNSET:
            field_dict["dynamic_days"] = dynamic_days
        if include_untrusted is not UNSET:
            field_dict["include_untrusted"] = include_untrusted
        if workspace is not UNSET:
            field_dict["workspace"] = workspace

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        _blocks = d.pop("blocks", UNSET)
        blocks: list[ProfileInBlocksItem] | Unset = UNSET
        if _blocks is not UNSET:
            blocks = []
            for blocks_item_data in _blocks:
                blocks_item = ProfileInBlocksItem(blocks_item_data)

                blocks.append(blocks_item)

        budget_tokens = d.pop("budget_tokens", UNSET)

        dynamic_days = d.pop("dynamic_days", UNSET)

        include_untrusted = d.pop("include_untrusted", UNSET)

        def _parse_workspace(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        workspace = _parse_workspace(d.pop("workspace", UNSET))

        profile_in = cls(
            blocks=blocks,
            budget_tokens=budget_tokens,
            dynamic_days=dynamic_days,
            include_untrusted=include_untrusted,
            workspace=workspace,
        )

        return profile_in
