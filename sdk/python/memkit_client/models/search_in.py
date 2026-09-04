from __future__ import annotations

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
        budget_tokens (int | Unset):  Default: 800.
        filter_ (None | SearchInFilterType0 | Unset):
        include_raw (bool | Unset):  Default: False.
        include_sources (bool | Unset):  Default: False.
        include_untrusted (bool | Unset):  Default: False.
        kinds (list[str] | None | Unset):
        limit (int | Unset):  Default: 30.
        policy_id (str | Unset):  Default: 'neutral-v1'.
        scopes (list[str] | None | Unset):
        subject (None | str | Unset):
    """

    query: str
    budget_tokens: int | Unset = 800
    filter_: None | SearchInFilterType0 | Unset = UNSET
    include_raw: bool | Unset = False
    include_sources: bool | Unset = False
    include_untrusted: bool | Unset = False
    kinds: list[str] | None | Unset = UNSET
    limit: int | Unset = 30
    policy_id: str | Unset = "neutral-v1"
    scopes: list[str] | None | Unset = UNSET
    subject: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.search_in_filter_type_0 import SearchInFilterType0

        query = self.query

        budget_tokens = self.budget_tokens

        filter_: dict[str, Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, SearchInFilterType0):
            filter_ = self.filter_.to_dict()
        else:
            filter_ = self.filter_

        include_raw = self.include_raw

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

        scopes: list[str] | None | Unset
        if isinstance(self.scopes, Unset):
            scopes = UNSET
        elif isinstance(self.scopes, list):
            scopes = self.scopes

        else:
            scopes = self.scopes

        subject: None | str | Unset
        if isinstance(self.subject, Unset):
            subject = UNSET
        else:
            subject = self.subject

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "query": query,
            }
        )
        if budget_tokens is not UNSET:
            field_dict["budget_tokens"] = budget_tokens
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if include_raw is not UNSET:
            field_dict["include_raw"] = include_raw
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
        if scopes is not UNSET:
            field_dict["scopes"] = scopes
        if subject is not UNSET:
            field_dict["subject"] = subject

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.search_in_filter_type_0 import SearchInFilterType0

        d = dict(src_dict)
        query = d.pop("query")

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

        include_raw = d.pop("include_raw", UNSET)

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

        def _parse_subject(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        subject = _parse_subject(d.pop("subject", UNSET))

        search_in = cls(
            query=query,
            budget_tokens=budget_tokens,
            filter_=filter_,
            include_raw=include_raw,
            include_sources=include_sources,
            include_untrusted=include_untrusted,
            kinds=kinds,
            limit=limit,
            policy_id=policy_id,
            scopes=scopes,
            subject=subject,
        )

        return search_in
