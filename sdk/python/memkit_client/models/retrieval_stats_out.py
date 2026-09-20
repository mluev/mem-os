from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.retrieval_totals import RetrievalTotals
    from ..models.series_point import SeriesPoint


T = TypeVar("T", bound="RetrievalStatsOut")


@_attrs_define
class RetrievalStatsOut:
    """
    Attributes:
        bucket (Literal['day']):
        from_ (None | str):
        series (list[SeriesPoint]):
        to (None | str):
        totals (RetrievalTotals):
    """

    bucket: Literal["day"]
    from_: None | str
    series: list[SeriesPoint]
    to: None | str
    totals: RetrievalTotals
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bucket = self.bucket

        from_: None | str
        from_ = self.from_

        series = []
        for series_item_data in self.series:
            series_item = series_item_data.to_dict()
            series.append(series_item)

        to: None | str
        to = self.to

        totals = self.totals.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bucket": bucket,
                "from": from_,
                "series": series,
                "to": to,
                "totals": totals,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.retrieval_totals import RetrievalTotals
        from ..models.series_point import SeriesPoint

        d = dict(src_dict)
        bucket = cast(Literal["day"], d.pop("bucket"))
        if bucket != "day":
            raise ValueError(f"bucket must match const 'day', got '{bucket}'")

        def _parse_from_(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        from_ = _parse_from_(d.pop("from"))

        series = []
        _series = d.pop("series")
        for series_item_data in _series:
            series_item = SeriesPoint.from_dict(series_item_data)

            series.append(series_item)

        def _parse_to(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        to = _parse_to(d.pop("to"))

        totals = RetrievalTotals.from_dict(d.pop("totals"))

        retrieval_stats_out = cls(
            bucket=bucket,
            from_=from_,
            series=series,
            to=to,
            totals=totals,
        )

        retrieval_stats_out.additional_properties = d
        return retrieval_stats_out

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
