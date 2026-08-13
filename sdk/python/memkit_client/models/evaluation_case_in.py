from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.evaluation_arms_in import EvaluationArmsIn


T = TypeVar("T", bound="EvaluationCaseIn")


@_attrs_define
class EvaluationCaseIn:
    """
    Attributes:
        arms (EvaluationArmsIn):
        case_key (str):
        prompt (str):
    """

    arms: EvaluationArmsIn
    case_key: str
    prompt: str

    def to_dict(self) -> dict[str, Any]:
        arms = self.arms.to_dict()

        case_key = self.case_key

        prompt = self.prompt

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "arms": arms,
                "case_key": case_key,
                "prompt": prompt,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.evaluation_arms_in import EvaluationArmsIn

        d = dict(src_dict)
        arms = EvaluationArmsIn.from_dict(d.pop("arms"))

        case_key = d.pop("case_key")

        prompt = d.pop("prompt")

        evaluation_case_in = cls(
            arms=arms,
            case_key=case_key,
            prompt=prompt,
        )

        return evaluation_case_in
