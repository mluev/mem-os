from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.index_counts import IndexCounts
    from ..models.metrics_out_spend_by_user_item import MetricsOutSpendByUserItem
    from ..models.search_latency import SearchLatency


T = TypeVar("T", bound="MetricsOut")


@_attrs_define
class MetricsOut:
    """
    Attributes:
        abstention_rate (float | None):
        backup_freshness_seconds (float | None):
        correct_rate (float | None):
        feedback_labels (int):
        feedback_runs (int):
        index_parity (IndexCounts):
        month_limit_usd (float | None):
        month_reserved_usd (float):
        month_spend_usd (float):
        oldest_unprocessed_message (None | str):
        outbox_oldest_age_seconds (float | None):
        outbox_pending (int | None):
        outbox_retries (int | None):
        pending_review (int):
        provider_errors (int):
        retrieval_runs (int):
        search_latency_ms (SearchLatency):
        spend_by_user (list[MetricsOutSpendByUserItem]):
        useful_rate (float | None):
    """

    abstention_rate: float | None
    backup_freshness_seconds: float | None
    correct_rate: float | None
    feedback_labels: int
    feedback_runs: int
    index_parity: IndexCounts
    month_limit_usd: float | None
    month_reserved_usd: float
    month_spend_usd: float
    oldest_unprocessed_message: None | str
    outbox_oldest_age_seconds: float | None
    outbox_pending: int | None
    outbox_retries: int | None
    pending_review: int
    provider_errors: int
    retrieval_runs: int
    search_latency_ms: SearchLatency
    spend_by_user: list[MetricsOutSpendByUserItem]
    useful_rate: float | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        abstention_rate: float | None
        abstention_rate = self.abstention_rate

        backup_freshness_seconds: float | None
        backup_freshness_seconds = self.backup_freshness_seconds

        correct_rate: float | None
        correct_rate = self.correct_rate

        feedback_labels = self.feedback_labels

        feedback_runs = self.feedback_runs

        index_parity = self.index_parity.to_dict()

        month_limit_usd: float | None
        month_limit_usd = self.month_limit_usd

        month_reserved_usd = self.month_reserved_usd

        month_spend_usd = self.month_spend_usd

        oldest_unprocessed_message: None | str
        oldest_unprocessed_message = self.oldest_unprocessed_message

        outbox_oldest_age_seconds: float | None
        outbox_oldest_age_seconds = self.outbox_oldest_age_seconds

        outbox_pending: int | None
        outbox_pending = self.outbox_pending

        outbox_retries: int | None
        outbox_retries = self.outbox_retries

        pending_review = self.pending_review

        provider_errors = self.provider_errors

        retrieval_runs = self.retrieval_runs

        search_latency_ms = self.search_latency_ms.to_dict()

        spend_by_user = []
        for spend_by_user_item_data in self.spend_by_user:
            spend_by_user_item = spend_by_user_item_data.to_dict()
            spend_by_user.append(spend_by_user_item)

        useful_rate: float | None
        useful_rate = self.useful_rate

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "abstention_rate": abstention_rate,
                "backup_freshness_seconds": backup_freshness_seconds,
                "correct_rate": correct_rate,
                "feedback_labels": feedback_labels,
                "feedback_runs": feedback_runs,
                "index_parity": index_parity,
                "month_limit_usd": month_limit_usd,
                "month_reserved_usd": month_reserved_usd,
                "month_spend_usd": month_spend_usd,
                "oldest_unprocessed_message": oldest_unprocessed_message,
                "outbox_oldest_age_seconds": outbox_oldest_age_seconds,
                "outbox_pending": outbox_pending,
                "outbox_retries": outbox_retries,
                "pending_review": pending_review,
                "provider_errors": provider_errors,
                "retrieval_runs": retrieval_runs,
                "search_latency_ms": search_latency_ms,
                "spend_by_user": spend_by_user,
                "useful_rate": useful_rate,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.index_counts import IndexCounts
        from ..models.metrics_out_spend_by_user_item import MetricsOutSpendByUserItem
        from ..models.search_latency import SearchLatency

        d = dict(src_dict)

        def _parse_abstention_rate(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        abstention_rate = _parse_abstention_rate(d.pop("abstention_rate"))

        def _parse_backup_freshness_seconds(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        backup_freshness_seconds = _parse_backup_freshness_seconds(d.pop("backup_freshness_seconds"))

        def _parse_correct_rate(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        correct_rate = _parse_correct_rate(d.pop("correct_rate"))

        feedback_labels = d.pop("feedback_labels")

        feedback_runs = d.pop("feedback_runs")

        index_parity = IndexCounts.from_dict(d.pop("index_parity"))

        def _parse_month_limit_usd(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        month_limit_usd = _parse_month_limit_usd(d.pop("month_limit_usd"))

        month_reserved_usd = d.pop("month_reserved_usd")

        month_spend_usd = d.pop("month_spend_usd")

        def _parse_oldest_unprocessed_message(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        oldest_unprocessed_message = _parse_oldest_unprocessed_message(d.pop("oldest_unprocessed_message"))

        def _parse_outbox_oldest_age_seconds(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        outbox_oldest_age_seconds = _parse_outbox_oldest_age_seconds(d.pop("outbox_oldest_age_seconds"))

        def _parse_outbox_pending(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        outbox_pending = _parse_outbox_pending(d.pop("outbox_pending"))

        def _parse_outbox_retries(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        outbox_retries = _parse_outbox_retries(d.pop("outbox_retries"))

        pending_review = d.pop("pending_review")

        provider_errors = d.pop("provider_errors")

        retrieval_runs = d.pop("retrieval_runs")

        search_latency_ms = SearchLatency.from_dict(d.pop("search_latency_ms"))

        spend_by_user = []
        _spend_by_user = d.pop("spend_by_user")
        for spend_by_user_item_data in _spend_by_user:
            spend_by_user_item = MetricsOutSpendByUserItem.from_dict(spend_by_user_item_data)

            spend_by_user.append(spend_by_user_item)

        def _parse_useful_rate(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        useful_rate = _parse_useful_rate(d.pop("useful_rate"))

        metrics_out = cls(
            abstention_rate=abstention_rate,
            backup_freshness_seconds=backup_freshness_seconds,
            correct_rate=correct_rate,
            feedback_labels=feedback_labels,
            feedback_runs=feedback_runs,
            index_parity=index_parity,
            month_limit_usd=month_limit_usd,
            month_reserved_usd=month_reserved_usd,
            month_spend_usd=month_spend_usd,
            oldest_unprocessed_message=oldest_unprocessed_message,
            outbox_oldest_age_seconds=outbox_oldest_age_seconds,
            outbox_pending=outbox_pending,
            outbox_retries=outbox_retries,
            pending_review=pending_review,
            provider_errors=provider_errors,
            retrieval_runs=retrieval_runs,
            search_latency_ms=search_latency_ms,
            spend_by_user=spend_by_user,
            useful_rate=useful_rate,
        )

        metrics_out.additional_properties = d
        return metrics_out

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
