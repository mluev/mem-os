from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

T = TypeVar("T", bound="ForgetIn")


@_attrs_define
class ForgetIn:
    """Forget matching memories: by a request searched semantically, or by ids.

    Forgetting archives: a forgotten memory leaves search and profiles, keeps
    its history and reason, and a reviewer can bring it back. A dry run is the
    default, because the match is semantic and a broad request selects more
    than intended.

        Attributes:
            dry_run (bool | Unset):  Default: True.
            ids (list[str] | None | Unset):
            max_forget (int | Unset):  Default: 100.
            query (None | str | Unset):
            reason (None | str | Unset):
            scope (None | str | Unset):
            threshold (float | Unset):  Default: 0.3.
            verify (bool | Unset):  Default: True.
    """

    dry_run: bool | Unset = True
    ids: list[str] | None | Unset = UNSET
    max_forget: int | Unset = 100
    query: None | str | Unset = UNSET
    reason: None | str | Unset = UNSET
    scope: None | str | Unset = UNSET
    threshold: float | Unset = 0.3
    verify: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        dry_run = self.dry_run

        ids: list[str] | None | Unset
        if isinstance(self.ids, Unset):
            ids = UNSET
        elif isinstance(self.ids, list):
            ids = self.ids

        else:
            ids = self.ids

        max_forget = self.max_forget

        query: None | str | Unset
        if isinstance(self.query, Unset):
            query = UNSET
        else:
            query = self.query

        reason: None | str | Unset
        if isinstance(self.reason, Unset):
            reason = UNSET
        else:
            reason = self.reason

        scope: None | str | Unset
        if isinstance(self.scope, Unset):
            scope = UNSET
        else:
            scope = self.scope

        threshold = self.threshold

        verify = self.verify

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if ids is not UNSET:
            field_dict["ids"] = ids
        if max_forget is not UNSET:
            field_dict["max_forget"] = max_forget
        if query is not UNSET:
            field_dict["query"] = query
        if reason is not UNSET:
            field_dict["reason"] = reason
        if scope is not UNSET:
            field_dict["scope"] = scope
        if threshold is not UNSET:
            field_dict["threshold"] = threshold
        if verify is not UNSET:
            field_dict["verify"] = verify

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dry_run = d.pop("dry_run", UNSET)

        def _parse_ids(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                ids_type_0 = cast(list[str], data)

                return ids_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        ids = _parse_ids(d.pop("ids", UNSET))

        max_forget = d.pop("max_forget", UNSET)

        def _parse_query(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        query = _parse_query(d.pop("query", UNSET))

        def _parse_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        reason = _parse_reason(d.pop("reason", UNSET))

        def _parse_scope(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        scope = _parse_scope(d.pop("scope", UNSET))

        threshold = d.pop("threshold", UNSET)

        verify = d.pop("verify", UNSET)

        forget_in = cls(
            dry_run=dry_run,
            ids=ids,
            max_forget=max_forget,
            query=query,
            reason=reason,
            scope=scope,
            threshold=threshold,
            verify=verify,
        )

        return forget_in
