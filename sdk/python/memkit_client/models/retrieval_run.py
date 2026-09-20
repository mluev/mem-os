from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.retrieval_result import RetrievalResult
    from ..models.retrieval_run_timings import RetrievalRunTimings


T = TypeVar("T", bound="RetrievalRun")


@_attrs_define
class RetrievalRun:
    """
    Attributes:
        abstained (bool):
        created_at (None | str):
        id (str):
        policy_id (str):
        results (list[RetrievalResult]):
        timings (RetrievalRunTimings):
        used_tokens (int):
    """

    abstained: bool
    created_at: None | str
    id: str
    policy_id: str
    results: list[RetrievalResult]
    timings: RetrievalRunTimings
    used_tokens: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        abstained = self.abstained

        created_at: None | str
        created_at = self.created_at

        id = self.id

        policy_id = self.policy_id

        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        timings = self.timings.to_dict()

        used_tokens = self.used_tokens

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "abstained": abstained,
                "created_at": created_at,
                "id": id,
                "policy_id": policy_id,
                "results": results,
                "timings": timings,
                "used_tokens": used_tokens,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.retrieval_result import RetrievalResult
        from ..models.retrieval_run_timings import RetrievalRunTimings

        d = dict(src_dict)
        abstained = d.pop("abstained")

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        id = d.pop("id")

        policy_id = d.pop("policy_id")

        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = RetrievalResult.from_dict(results_item_data)

            results.append(results_item)

        timings = RetrievalRunTimings.from_dict(d.pop("timings"))

        used_tokens = d.pop("used_tokens")

        retrieval_run = cls(
            abstained=abstained,
            created_at=created_at,
            id=id,
            policy_id=policy_id,
            results=results,
            timings=timings,
            used_tokens=used_tokens,
        )

        retrieval_run.additional_properties = d
        return retrieval_run

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
