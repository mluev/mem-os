from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.forget_candidate import ForgetCandidate


T = TypeVar("T", bound="ForgetOut")


@_attrs_define
class ForgetOut:
    """
    Attributes:
        candidates (list[ForgetCandidate]):
        dry_run (bool):
        forgotten (list[str]):
        verified (bool):
        reason (None | str | Unset):
    """

    candidates: list[ForgetCandidate]
    dry_run: bool
    forgotten: list[str]
    verified: bool
    reason: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        candidates = []
        for candidates_item_data in self.candidates:
            candidates_item = candidates_item_data.to_dict()
            candidates.append(candidates_item)

        dry_run = self.dry_run

        forgotten = self.forgotten

        verified = self.verified

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "candidates": candidates,
                "dry_run": dry_run,
                "forgotten": forgotten,
                "verified": verified,
            }
        )
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.forget_candidate import ForgetCandidate

        d = dict(src_dict)
        candidates = []
        _candidates = d.pop("candidates")
        for candidates_item_data in _candidates:
            candidates_item = ForgetCandidate.from_dict(candidates_item_data)

            candidates.append(candidates_item)

        dry_run = d.pop("dry_run")

        forgotten = cast(list[str], d.pop("forgotten"))

        verified = d.pop("verified")

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        forget_out = cls(
            candidates=candidates,
            dry_run=dry_run,
            forgotten=forgotten,
            verified=verified,
            reason=reason,
        )

        return forget_out
