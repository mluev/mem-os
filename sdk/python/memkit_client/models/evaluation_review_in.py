from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..models.evaluation_review_in_current_vs_v7 import EvaluationReviewInCurrentVsV7
from ..models.evaluation_review_in_harmful_item import EvaluationReviewInHarmfulItem
from ..models.evaluation_review_in_ranking_item import EvaluationReviewInRankingItem
from ..types import UNSET, Unset

T = TypeVar("T", bound="EvaluationReviewIn")


@_attrs_define
class EvaluationReviewIn:
    """
    Attributes:
        current_vs_v7 (EvaluationReviewInCurrentVsV7):
        ranking (list[EvaluationReviewInRankingItem]):
        harmful (list[EvaluationReviewInHarmfulItem] | Unset):
        notes (str | Unset):  Default: ''.
    """

    current_vs_v7: EvaluationReviewInCurrentVsV7
    ranking: list[EvaluationReviewInRankingItem]
    harmful: list[EvaluationReviewInHarmfulItem] | Unset = UNSET
    notes: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        current_vs_v7 = self.current_vs_v7.value

        ranking = []
        for ranking_item_data in self.ranking:
            ranking_item = ranking_item_data.value
            ranking.append(ranking_item)

        harmful: list[str] | Unset = UNSET
        if not isinstance(self.harmful, Unset):
            harmful = []
            for harmful_item_data in self.harmful:
                harmful_item = harmful_item_data.value
                harmful.append(harmful_item)

        notes = self.notes

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "current_vs_v7": current_vs_v7,
                "ranking": ranking,
            }
        )
        if harmful is not UNSET:
            field_dict["harmful"] = harmful
        if notes is not UNSET:
            field_dict["notes"] = notes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        current_vs_v7 = EvaluationReviewInCurrentVsV7(d.pop("current_vs_v7"))

        ranking = []
        _ranking = d.pop("ranking")
        for ranking_item_data in _ranking:
            ranking_item = EvaluationReviewInRankingItem(ranking_item_data)

            ranking.append(ranking_item)

        _harmful = d.pop("harmful", UNSET)
        harmful: list[EvaluationReviewInHarmfulItem] | Unset = UNSET
        if _harmful is not UNSET:
            harmful = []
            for harmful_item_data in _harmful:
                harmful_item = EvaluationReviewInHarmfulItem(harmful_item_data)

                harmful.append(harmful_item)

        notes = d.pop("notes", UNSET)

        evaluation_review_in = cls(
            current_vs_v7=current_vs_v7,
            ranking=ranking,
            harmful=harmful,
            notes=notes,
        )

        return evaluation_review_in
