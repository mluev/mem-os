from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

T = TypeVar("T", bound="RuntimeConfig")


@_attrs_define
class RuntimeConfig:
    """The non-secret settings that decide what extraction and search do.

    A benchmark run records this block, so a number can always be traced to
    the prompt, policy and dreaming mode that produced it.

        Attributes:
            dedup_cosine (float):
            default_policy (str):
            dreaming (str):
            index_assistant_turns (bool):
            judge_model (str):
            maintenance (str):
            prompt_version (str):
            rerank_model (str):
    """

    dedup_cosine: float
    default_policy: str
    dreaming: str
    index_assistant_turns: bool
    judge_model: str
    maintenance: str
    prompt_version: str
    rerank_model: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dedup_cosine = self.dedup_cosine

        default_policy = self.default_policy

        dreaming = self.dreaming

        index_assistant_turns = self.index_assistant_turns

        judge_model = self.judge_model

        maintenance = self.maintenance

        prompt_version = self.prompt_version

        rerank_model = self.rerank_model

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dedup_cosine": dedup_cosine,
                "default_policy": default_policy,
                "dreaming": dreaming,
                "index_assistant_turns": index_assistant_turns,
                "judge_model": judge_model,
                "maintenance": maintenance,
                "prompt_version": prompt_version,
                "rerank_model": rerank_model,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dedup_cosine = d.pop("dedup_cosine")

        default_policy = d.pop("default_policy")

        dreaming = d.pop("dreaming")

        index_assistant_turns = d.pop("index_assistant_turns")

        judge_model = d.pop("judge_model")

        maintenance = d.pop("maintenance")

        prompt_version = d.pop("prompt_version")

        rerank_model = d.pop("rerank_model")

        runtime_config = cls(
            dedup_cosine=dedup_cosine,
            default_policy=default_policy,
            dreaming=dreaming,
            index_assistant_turns=index_assistant_turns,
            judge_model=judge_model,
            maintenance=maintenance,
            prompt_version=prompt_version,
            rerank_model=rerank_model,
        )

        runtime_config.additional_properties = d
        return runtime_config

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
