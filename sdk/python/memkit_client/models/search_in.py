from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.search_in_filter_type_0 import SearchInFilterType0


T = TypeVar("T", bound="SearchIn")


@_attrs_define
class SearchIn:
    """
    Attributes:
        query (str):
        as_of (datetime.datetime | None | Unset):
        budget_tokens (int | Unset):  Default: 800.
        filter_ (None | SearchInFilterType0 | Unset):
        include_history (bool | Unset):  Default: False.
        include_raw (bool | Unset):  Default: False.
        include_related (bool | Unset):  Default: False.
        include_sources (bool | Unset):  Default: False.
        include_untrusted (bool | Unset):  Default: False.
        kinds (list[str] | None | Unset):
        limit (int | Unset):  Default: 30.
        policy_id (str | Unset):  Default: 'core-retrieval-v2'.
        rewrite_query (bool | Unset):  Default: False.
        scopes (list[str] | None | Unset):
        since (datetime.datetime | None | Unset):
        source_context_chars (int | Unset):  Default: 0.
        subject (None | str | Unset):
        until (datetime.datetime | None | Unset):
    """

    query: str
    as_of: datetime.datetime | None | Unset = UNSET
    budget_tokens: int | Unset = 800
    filter_: None | SearchInFilterType0 | Unset = UNSET
    include_history: bool | Unset = False
    include_raw: bool | Unset = False
    include_related: bool | Unset = False
    include_sources: bool | Unset = False
    include_untrusted: bool | Unset = False
    kinds: list[str] | None | Unset = UNSET
    limit: int | Unset = 30
    policy_id: str | Unset = "core-retrieval-v2"
    rewrite_query: bool | Unset = False
    scopes: list[str] | None | Unset = UNSET
    since: datetime.datetime | None | Unset = UNSET
    source_context_chars: int | Unset = 0
    subject: None | str | Unset = UNSET
    until: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.search_in_filter_type_0 import SearchInFilterType0

        query = self.query

        as_of: None | str | Unset
        if isinstance(self.as_of, Unset):
            as_of = UNSET
        elif isinstance(self.as_of, datetime.datetime):
            as_of = self.as_of.isoformat()
        else:
            as_of = self.as_of

        budget_tokens = self.budget_tokens

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, SearchInFilterType0):
            filter_ = self.filter_.to_dict()
        else:
            filter_ = self.filter_

        include_history = self.include_history

        include_raw = self.include_raw

        include_related = self.include_related

        include_sources = self.include_sources

        include_untrusted = self.include_untrusted

        kinds: list[str] | None | Unset
        if isinstance(self.kinds, Unset):
            kinds = UNSET
        elif isinstance(self.kinds, list):
            kinds = self.kinds

        else:
            kinds = self.kinds

        limit = self.limit

        policy_id = self.policy_id

        rewrite_query = self.rewrite_query

        scopes: list[str] | None | Unset
        if isinstance(self.scopes, Unset):
            scopes = UNSET
        elif isinstance(self.scopes, list):
            scopes = self.scopes

        else:
            scopes = self.scopes

        since: None | str | Unset
        if isinstance(self.since, Unset):
            since = UNSET
        elif isinstance(self.since, datetime.datetime):
            since = self.since.isoformat()
        else:
            since = self.since

        source_context_chars = self.source_context_chars

        subject: None | str | Unset
        if isinstance(self.subject, Unset):
            subject = UNSET
        else:
            subject = self.subject

        until: None | str | Unset
        if isinstance(self.until, Unset):
            until = UNSET
        elif isinstance(self.until, datetime.datetime):
            until = self.until.isoformat()
        else:
            until = self.until

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "query": query,
            }
        )
        if as_of is not UNSET:
            field_dict["as_of"] = as_of
        if budget_tokens is not UNSET:
            field_dict["budget_tokens"] = budget_tokens
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if include_history is not UNSET:
            field_dict["include_history"] = include_history
        if include_raw is not UNSET:
            field_dict["include_raw"] = include_raw
        if include_related is not UNSET:
            field_dict["include_related"] = include_related
        if include_sources is not UNSET:
            field_dict["include_sources"] = include_sources
        if include_untrusted is not UNSET:
            field_dict["include_untrusted"] = include_untrusted
        if kinds is not UNSET:
            field_dict["kinds"] = kinds
        if limit is not UNSET:
            field_dict["limit"] = limit
        if policy_id is not UNSET:
            field_dict["policy_id"] = policy_id
        if rewrite_query is not UNSET:
            field_dict["rewrite_query"] = rewrite_query
        if scopes is not UNSET:
            field_dict["scopes"] = scopes
        if since is not UNSET:
            field_dict["since"] = since
        if source_context_chars is not UNSET:
            field_dict["source_context_chars"] = source_context_chars
        if subject is not UNSET:
            field_dict["subject"] = subject
        if until is not UNSET:
            field_dict["until"] = until

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.search_in_filter_type_0 import SearchInFilterType0

        d = dict(src_dict)
        query = d.pop("query")

        def _parse_as_of(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                as_of_type_0 = datetime.datetime.fromisoformat(data)

                return as_of_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        as_of = _parse_as_of(d.pop("as_of", UNSET))

        budget_tokens = d.pop("budget_tokens", UNSET)

        def _parse_filter_(data: object) -> None | SearchInFilterType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_0 = SearchInFilterType0.from_dict(data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SearchInFilterType0 | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        include_history = d.pop("include_history", UNSET)

        include_raw = d.pop("include_raw", UNSET)

        include_related = d.pop("include_related", UNSET)

        include_sources = d.pop("include_sources", UNSET)

        include_untrusted = d.pop("include_untrusted", UNSET)

        def _parse_kinds(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                kinds_type_0 = cast(list[str], data)

                return kinds_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        kinds = _parse_kinds(d.pop("kinds", UNSET))

        limit = d.pop("limit", UNSET)

        policy_id = d.pop("policy_id", UNSET)

        rewrite_query = d.pop("rewrite_query", UNSET)

        def _parse_scopes(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                scopes_type_0 = cast(list[str], data)

                return scopes_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        scopes = _parse_scopes(d.pop("scopes", UNSET))

        def _parse_since(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                since_type_0 = datetime.datetime.fromisoformat(data)

                return since_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        since = _parse_since(d.pop("since", UNSET))

        source_context_chars = d.pop("source_context_chars", UNSET)

        def _parse_subject(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subject = _parse_subject(d.pop("subject", UNSET))

        def _parse_until(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                until_type_0 = datetime.datetime.fromisoformat(data)

                return until_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        until = _parse_until(d.pop("until", UNSET))

        search_in = cls(
            query=query,
            as_of=as_of,
            budget_tokens=budget_tokens,
            filter_=filter_,
            include_history=include_history,
            include_raw=include_raw,
            include_related=include_related,
            include_sources=include_sources,
            include_untrusted=include_untrusted,
            kinds=kinds,
            limit=limit,
            policy_id=policy_id,
            rewrite_query=rewrite_query,
            scopes=scopes,
            since=since,
            source_context_chars=source_context_chars,
            subject=subject,
            until=until,
        )

        return search_in
