from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..models.replay_review_in_decision import ReplayReviewInDecision
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.replay_review_in_edits_type_0 import ReplayReviewInEditsType0


T = TypeVar("T", bound="ReplayReviewIn")


@_attrs_define
class ReplayReviewIn:
    """
    Attributes:
        decision (ReplayReviewInDecision):
        edits (None | ReplayReviewInEditsType0 | Unset):
    """

    decision: ReplayReviewInDecision
    edits: None | ReplayReviewInEditsType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.replay_review_in_edits_type_0 import ReplayReviewInEditsType0

        decision = self.decision.value

        edits: dict[str, Any] | None | Unset
        if isinstance(self.edits, Unset):
            edits = UNSET
        elif isinstance(self.edits, ReplayReviewInEditsType0):
            edits = self.edits.to_dict()
        else:
            edits = self.edits

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "decision": decision,
            }
        )
        if edits is not UNSET:
            field_dict["edits"] = edits

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.replay_review_in_edits_type_0 import ReplayReviewInEditsType0

        d = dict(src_dict)
        decision = ReplayReviewInDecision(d.pop("decision"))

        def _parse_edits(data: object) -> None | ReplayReviewInEditsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                edits_type_0 = ReplayReviewInEditsType0.from_dict(data)

                return edits_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | ReplayReviewInEditsType0 | Unset, data)

        edits = _parse_edits(d.pop("edits", UNSET))

        replay_review_in = cls(
            decision=decision,
            edits=edits,
        )

        return replay_review_in
