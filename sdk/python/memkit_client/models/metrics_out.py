from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.metrics_out_index_parity_type_0 import MetricsOutIndexParityType0
    from ..models.metrics_out_search_latency_ms_type_0 import MetricsOutSearchLatencyMsType0


T = TypeVar("T", bound="MetricsOut")


@_attrs_define
class MetricsOut:
    """
    Attributes:
        month_reserved_usd (float):
        month_spend_usd (float):
        oldest_unprocessed_message (None | str):
        outbox_pending (int):
        provider_errors (int):
        abstention_rate (float | None | Unset):
        backup_freshness_seconds (float | None | Unset):
        correct_rate (float | None | Unset):
        feedback_labels (int | None | Unset):
        feedback_runs (int | None | Unset):
        index_parity (MetricsOutIndexParityType0 | None | Unset):
        outbox_oldest_age_seconds (float | None | Unset):
        outbox_retries (int | None | Unset):
        retrieval_runs (int | None | Unset):
        search_latency_ms (MetricsOutSearchLatencyMsType0 | None | Unset):
        useful_rate (float | None | Unset):
    """

    month_reserved_usd: float
    month_spend_usd: float
    oldest_unprocessed_message: None | str
    outbox_pending: int
    provider_errors: int
    abstention_rate: float | None | Unset = UNSET
    backup_freshness_seconds: float | None | Unset = UNSET
    correct_rate: float | None | Unset = UNSET
    feedback_labels: int | None | Unset = UNSET
    feedback_runs: int | None | Unset = UNSET
    index_parity: MetricsOutIndexParityType0 | None | Unset = UNSET
    outbox_oldest_age_seconds: float | None | Unset = UNSET
    outbox_retries: int | None | Unset = UNSET
    retrieval_runs: int | None | Unset = UNSET
    search_latency_ms: MetricsOutSearchLatencyMsType0 | None | Unset = UNSET
    useful_rate: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.metrics_out_index_parity_type_0 import MetricsOutIndexParityType0
        from ..models.metrics_out_search_latency_ms_type_0 import MetricsOutSearchLatencyMsType0

        month_reserved_usd = self.month_reserved_usd

        month_spend_usd = self.month_spend_usd

        oldest_unprocessed_message: None | str
        oldest_unprocessed_message = self.oldest_unprocessed_message

        outbox_pending = self.outbox_pending

        provider_errors = self.provider_errors

        abstention_rate: float | None | Unset
        if isinstance(self.abstention_rate, Unset):
            abstention_rate = UNSET
        else:
            abstention_rate = self.abstention_rate

        backup_freshness_seconds: float | None | Unset
        if isinstance(self.backup_freshness_seconds, Unset):
            backup_freshness_seconds = UNSET
        else:
            backup_freshness_seconds = self.backup_freshness_seconds

        correct_rate: float | None | Unset
        if isinstance(self.correct_rate, Unset):
            correct_rate = UNSET
        else:
            correct_rate = self.correct_rate

        feedback_labels: int | None | Unset
        if isinstance(self.feedback_labels, Unset):
            feedback_labels = UNSET
        else:
            feedback_labels = self.feedback_labels

        feedback_runs: int | None | Unset
        if isinstance(self.feedback_runs, Unset):
            feedback_runs = UNSET
        else:
            feedback_runs = self.feedback_runs

        index_parity: dict[str, Any] | None | Unset
        if isinstance(self.index_parity, Unset):
            index_parity = UNSET
        elif isinstance(self.index_parity, MetricsOutIndexParityType0):
            index_parity = self.index_parity.to_dict()
        else:
            index_parity = self.index_parity

        outbox_oldest_age_seconds: float | None | Unset
        if isinstance(self.outbox_oldest_age_seconds, Unset):
            outbox_oldest_age_seconds = UNSET
        else:
            outbox_oldest_age_seconds = self.outbox_oldest_age_seconds

        outbox_retries: int | None | Unset
        if isinstance(self.outbox_retries, Unset):
            outbox_retries = UNSET
        else:
            outbox_retries = self.outbox_retries

        retrieval_runs: int | None | Unset
        if isinstance(self.retrieval_runs, Unset):
            retrieval_runs = UNSET
        else:
            retrieval_runs = self.retrieval_runs

        search_latency_ms: dict[str, Any] | None | Unset
        if isinstance(self.search_latency_ms, Unset):
            search_latency_ms = UNSET
        elif isinstance(self.search_latency_ms, MetricsOutSearchLatencyMsType0):
            search_latency_ms = self.search_latency_ms.to_dict()
        else:
            search_latency_ms = self.search_latency_ms

        useful_rate: float | None | Unset
        if isinstance(self.useful_rate, Unset):
            useful_rate = UNSET
        else:
            useful_rate = self.useful_rate

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "month_reserved_usd": month_reserved_usd,
                "month_spend_usd": month_spend_usd,
                "oldest_unprocessed_message": oldest_unprocessed_message,
                "outbox_pending": outbox_pending,
                "provider_errors": provider_errors,
            }
        )
        if abstention_rate is not UNSET:
            field_dict["abstention_rate"] = abstention_rate
        if backup_freshness_seconds is not UNSET:
            field_dict["backup_freshness_seconds"] = backup_freshness_seconds
        if correct_rate is not UNSET:
            field_dict["correct_rate"] = correct_rate
        if feedback_labels is not UNSET:
            field_dict["feedback_labels"] = feedback_labels
        if feedback_runs is not UNSET:
            field_dict["feedback_runs"] = feedback_runs
        if index_parity is not UNSET:
            field_dict["index_parity"] = index_parity
        if outbox_oldest_age_seconds is not UNSET:
            field_dict["outbox_oldest_age_seconds"] = outbox_oldest_age_seconds
        if outbox_retries is not UNSET:
            field_dict["outbox_retries"] = outbox_retries
        if retrieval_runs is not UNSET:
            field_dict["retrieval_runs"] = retrieval_runs
        if search_latency_ms is not UNSET:
            field_dict["search_latency_ms"] = search_latency_ms
        if useful_rate is not UNSET:
            field_dict["useful_rate"] = useful_rate

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.metrics_out_index_parity_type_0 import MetricsOutIndexParityType0
        from ..models.metrics_out_search_latency_ms_type_0 import MetricsOutSearchLatencyMsType0

        d = dict(src_dict)
        month_reserved_usd = d.pop("month_reserved_usd")

        month_spend_usd = d.pop("month_spend_usd")

        def _parse_oldest_unprocessed_message(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        oldest_unprocessed_message = _parse_oldest_unprocessed_message(d.pop("oldest_unprocessed_message"))

        outbox_pending = d.pop("outbox_pending")

        provider_errors = d.pop("provider_errors")

        def _parse_abstention_rate(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        abstention_rate = _parse_abstention_rate(d.pop("abstention_rate", UNSET))

        def _parse_backup_freshness_seconds(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        backup_freshness_seconds = _parse_backup_freshness_seconds(d.pop("backup_freshness_seconds", UNSET))

        def _parse_correct_rate(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        correct_rate = _parse_correct_rate(d.pop("correct_rate", UNSET))

        def _parse_feedback_labels(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feedback_labels = _parse_feedback_labels(d.pop("feedback_labels", UNSET))

        def _parse_feedback_runs(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feedback_runs = _parse_feedback_runs(d.pop("feedback_runs", UNSET))

        def _parse_index_parity(data: object) -> MetricsOutIndexParityType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                index_parity_type_0 = MetricsOutIndexParityType0.from_dict(data)

                return index_parity_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MetricsOutIndexParityType0 | None | Unset, data)

        index_parity = _parse_index_parity(d.pop("index_parity", UNSET))

        def _parse_outbox_oldest_age_seconds(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        outbox_oldest_age_seconds = _parse_outbox_oldest_age_seconds(d.pop("outbox_oldest_age_seconds", UNSET))

        def _parse_outbox_retries(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        outbox_retries = _parse_outbox_retries(d.pop("outbox_retries", UNSET))

        def _parse_retrieval_runs(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        retrieval_runs = _parse_retrieval_runs(d.pop("retrieval_runs", UNSET))

        def _parse_search_latency_ms(data: object) -> MetricsOutSearchLatencyMsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                search_latency_ms_type_0 = MetricsOutSearchLatencyMsType0.from_dict(data)

                return search_latency_ms_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MetricsOutSearchLatencyMsType0 | None | Unset, data)

        search_latency_ms = _parse_search_latency_ms(d.pop("search_latency_ms", UNSET))

        def _parse_useful_rate(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        useful_rate = _parse_useful_rate(d.pop("useful_rate", UNSET))

        metrics_out = cls(
            month_reserved_usd=month_reserved_usd,
            month_spend_usd=month_spend_usd,
            oldest_unprocessed_message=oldest_unprocessed_message,
            outbox_pending=outbox_pending,
            provider_errors=provider_errors,
            abstention_rate=abstention_rate,
            backup_freshness_seconds=backup_freshness_seconds,
            correct_rate=correct_rate,
            feedback_labels=feedback_labels,
            feedback_runs=feedback_runs,
            index_parity=index_parity,
            outbox_oldest_age_seconds=outbox_oldest_age_seconds,
            outbox_retries=outbox_retries,
            retrieval_runs=retrieval_runs,
            search_latency_ms=search_latency_ms,
            useful_rate=useful_rate,
        )

        return metrics_out
