from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="JobQueuedOut")


@_attrs_define
class JobQueuedOut:
    """
    Attributes:
        job_id (None | str):
        status (str):
        reason (None | str | Unset):
    """

    job_id: None | str
    status: str
    reason: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        job_id: None | str
        job_id = self.job_id

        status = self.status

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "job_id": job_id,
                "status": status,
            }
        )
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_job_id(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        job_id = _parse_job_id(d.pop("job_id"))

        status = d.pop("status")

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        job_queued_out = cls(
            job_id=job_id,
            status=status,
            reason=reason,
        )

        return job_queued_out
