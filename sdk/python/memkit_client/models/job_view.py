from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.job_view_events_item import JobViewEventsItem


T = TypeVar("T", bound="JobView")


@_attrs_define
class JobView:
    """
    Attributes:
        created_at (None | str):
        error (None | str):
        error_code (None | str):
        finished_at (None | str):
        id (str):
        kind (str):
        result (Any):
        status (str):
        events (list[JobViewEventsItem] | Unset):
        user (None | str | Unset):
    """

    created_at: None | str
    error: None | str
    error_code: None | str
    finished_at: None | str
    id: str
    kind: str
    result: Any
    status: str
    events: list[JobViewEventsItem] | Unset = UNSET
    user: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        created_at: None | str
        created_at = self.created_at

        error: None | str
        error = self.error

        error_code: None | str
        error_code = self.error_code

        finished_at: None | str
        finished_at = self.finished_at

        id = self.id

        kind = self.kind

        result = self.result

        status = self.status

        events: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.events, Unset):
            events = []
            for events_item_data in self.events:
                events_item = events_item_data.to_dict()
                events.append(events_item)

        user: None | str | Unset
        if isinstance(self.user, Unset):
            user = UNSET
        else:
            user = self.user

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "error": error,
                "error_code": error_code,
                "finished_at": finished_at,
                "id": id,
                "kind": kind,
                "result": result,
                "status": status,
            }
        )
        if events is not UNSET:
            field_dict["events"] = events
        if user is not UNSET:
            field_dict["user"] = user

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.job_view_events_item import JobViewEventsItem

        d = dict(src_dict)

        def _parse_created_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        created_at = _parse_created_at(d.pop("created_at"))

        def _parse_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error = _parse_error(d.pop("error"))

        def _parse_error_code(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_code = _parse_error_code(d.pop("error_code"))

        def _parse_finished_at(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        finished_at = _parse_finished_at(d.pop("finished_at"))

        id = d.pop("id")

        kind = d.pop("kind")

        result = d.pop("result")

        status = d.pop("status")

        _events = d.pop("events", UNSET)
        events: list[JobViewEventsItem] | Unset = UNSET
        if _events is not UNSET:
            events = []
            for events_item_data in _events:
                events_item = JobViewEventsItem.from_dict(events_item_data)

                events.append(events_item)

        def _parse_user(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        user = _parse_user(d.pop("user", UNSET))

        job_view = cls(
            created_at=created_at,
            error=error,
            error_code=error_code,
            finished_at=finished_at,
            id=id,
            kind=kind,
            result=result,
            status=status,
            events=events,
            user=user,
        )

        job_view.additional_properties = d
        return job_view

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
