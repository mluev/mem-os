from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.review_totals_attention_by_kind import ReviewTotalsAttentionByKind
    from ..models.review_totals_pending_by_source import ReviewTotalsPendingBySource


T = TypeVar("T", bound="ReviewTotals")


@_attrs_define
class ReviewTotals:
    """
    Attributes:
        attention_by_kind (ReviewTotalsAttentionByKind):
        oldest_pending (None | str):
        pending (int):
        pending_by_source (ReviewTotalsPendingBySource):
    """

    attention_by_kind: ReviewTotalsAttentionByKind
    oldest_pending: None | str
    pending: int
    pending_by_source: ReviewTotalsPendingBySource
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        attention_by_kind = self.attention_by_kind.to_dict()

        oldest_pending: None | str
        oldest_pending = self.oldest_pending

        pending = self.pending

        pending_by_source = self.pending_by_source.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "attention_by_kind": attention_by_kind,
                "oldest_pending": oldest_pending,
                "pending": pending,
                "pending_by_source": pending_by_source,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.review_totals_attention_by_kind import ReviewTotalsAttentionByKind
        from ..models.review_totals_pending_by_source import ReviewTotalsPendingBySource

        d = dict(src_dict)
        attention_by_kind = ReviewTotalsAttentionByKind.from_dict(d.pop("attention_by_kind"))

        def _parse_oldest_pending(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        oldest_pending = _parse_oldest_pending(d.pop("oldest_pending"))

        pending = d.pop("pending")

        pending_by_source = ReviewTotalsPendingBySource.from_dict(d.pop("pending_by_source"))

        review_totals = cls(
            attention_by_kind=attention_by_kind,
            oldest_pending=oldest_pending,
            pending=pending,
            pending_by_source=pending_by_source,
        )

        review_totals.additional_properties = d
        return review_totals

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()
