from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="JudgeRunView")


@_attrs_define
class JudgeRunView:
    """
    Attributes:
        cost_usd (float | None):
        created_at (None | str):
        error (None | str):
        id (int):
        input_tokens (int | None):
        kind (str):
        latency_ms (float | None):
        model (str):
        output_tokens (int | None):
        prompt_version (str):
        user (None | str | Unset):
    """

    cost_usd: float | None
    created_at: None | str
    error: None | str
    id: int
    input_tokens: int | None
    kind: str
    latency_ms: float | None
    model: str
    output_tokens: int | None
    prompt_version: str
    user: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cost_usd: float | None
        cost_usd = self.cost_usd

        created_at: None | str
        created_at = self.created_at

        error: None | str
        error = self.error

        id = self.id

        input_tokens: int | None
        input_tokens = self.input_tokens

        kind = self.kind

        latency_ms: float | None
        latency_ms = self.latency_ms

        model = self.model

        output_tokens: int | None
        output_tokens = self.output_tokens

        prompt_version = self.prompt_version

        user: None | str | Unset
        if isinstance(self.user, Unset):
            user = UNSET
        else:
            user = self.user

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cost_usd": cost_usd,
                "created_at": created_at,
                "error": error,
                "id": id,
                "input_tokens": input_tokens,
                "kind": kind,
                "latency_ms": latency_ms,
                "model": model,
                "output_tokens": output_tokens,
                "prompt_version": prompt_version,
            }
        )
        if user is not UNSET:
            field_dict["user"] = user

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_cost_usd(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        cost_usd = _parse_cost_usd(d.pop("cost_usd"))

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

        id = d.pop("id")

        def _parse_input_tokens(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        input_tokens = _parse_input_tokens(d.pop("input_tokens"))

        kind = d.pop("kind")

        def _parse_latency_ms(data: object) -> float | None:
            if data is None:
                return data
            return cast(float | None, data)

        latency_ms = _parse_latency_ms(d.pop("latency_ms"))

        model = d.pop("model")

        def _parse_output_tokens(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        output_tokens = _parse_output_tokens(d.pop("output_tokens"))

        prompt_version = d.pop("prompt_version")

        def _parse_user(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        user = _parse_user(d.pop("user", UNSET))

        judge_run_view = cls(
            cost_usd=cost_usd,
            created_at=created_at,
            error=error,
            id=id,
            input_tokens=input_tokens,
            kind=kind,
            latency_ms=latency_ms,
            model=model,
            output_tokens=output_tokens,
            prompt_version=prompt_version,
            user=user,
        )

        judge_run_view.additional_properties = d
        return judge_run_view

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
