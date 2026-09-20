from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.review_in_decision import ReviewInDecision
from ..types import UNSET, Unset

T = TypeVar("T", bound="ReviewIn")


@_attrs_define
class ReviewIn:
    """
    Attributes:
        decision (ReviewInDecision):
        expected_revision (int | None | Unset):
    """

    decision: ReviewInDecision
    expected_revision: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        decision = self.decision.value

        expected_revision: int | None | Unset
        if isinstance(self.expected_revision, Unset):
            expected_revision = UNSET
        else:
            expected_revision = self.expected_revision

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "decision": decision,
            }
        )
        if expected_revision is not UNSET:
            field_dict["expected_revision"] = expected_revision

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        decision = ReviewInDecision(d.pop("decision"))

        def _parse_expected_revision(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        expected_revision = _parse_expected_revision(d.pop("expected_revision", UNSET))

        review_in = cls(
            decision=decision,
            expected_revision=expected_revision,
        )

        return review_in
