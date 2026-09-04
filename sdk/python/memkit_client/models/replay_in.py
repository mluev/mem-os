from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ReplayIn")


@_attrs_define
class ReplayIn:
    """
    Attributes:
        confirm (Literal['REPLAY'] | None | Unset):
    """

    confirm: Literal["REPLAY"] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        confirm: Literal["REPLAY"] | None | Unset
        if isinstance(self.confirm, Unset):
            confirm = UNSET
        else:
            confirm = self.confirm

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if confirm is not UNSET:
            field_dict["confirm"] = confirm

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_confirm(data: object) -> Literal["REPLAY"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            confirm_type_0 = cast(Literal["REPLAY"], data)
            if confirm_type_0 != "REPLAY":
                raise ValueError(f"confirm_type_0 must match const 'REPLAY', got '{confirm_type_0}'")
            return confirm_type_0
            return cast(Literal["REPLAY"] | None | Unset, data)

        confirm = _parse_confirm(d.pop("confirm", UNSET))

        replay_in = cls(
            confirm=confirm,
        )

        return replay_in
