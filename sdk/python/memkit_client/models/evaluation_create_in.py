from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.evaluation_case_in import EvaluationCaseIn
    from ..models.evaluation_create_in_rubric_type_0 import EvaluationCreateInRubricType0


T = TypeVar("T", bound="EvaluationCreateIn")


@_attrs_define
class EvaluationCreateIn:
    """
    Attributes:
        cases (list[EvaluationCaseIn]):
        model (Literal['gpt-5.6-sol'] | Unset):  Default: 'gpt-5.6-sol'.
        rubric (EvaluationCreateInRubricType0 | None | Unset):
    """

    cases: list[EvaluationCaseIn]
    model: Literal["gpt-5.6-sol"] | Unset = "gpt-5.6-sol"
    rubric: EvaluationCreateInRubricType0 | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.evaluation_create_in_rubric_type_0 import EvaluationCreateInRubricType0

        cases = []
        for cases_item_data in self.cases:
            cases_item = cases_item_data.to_dict()
            cases.append(cases_item)

        model = self.model

        rubric: dict[str, Any] | None | Unset
        if isinstance(self.rubric, Unset):
            rubric = UNSET
        elif isinstance(self.rubric, EvaluationCreateInRubricType0):
            rubric = self.rubric.to_dict()
        else:
            rubric = self.rubric

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "cases": cases,
            }
        )
        if model is not UNSET:
            field_dict["model"] = model
        if rubric is not UNSET:
            field_dict["rubric"] = rubric

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.evaluation_case_in import EvaluationCaseIn
        from ..models.evaluation_create_in_rubric_type_0 import EvaluationCreateInRubricType0

        d = dict(src_dict)
        cases = []
        _cases = d.pop("cases")
        for cases_item_data in _cases:
            cases_item = EvaluationCaseIn.from_dict(cases_item_data)

            cases.append(cases_item)

        model = cast(Literal["gpt-5.6-sol"] | Unset, d.pop("model", UNSET))
        if model != "gpt-5.6-sol" and not isinstance(model, Unset):
            raise ValueError(f"model must match const 'gpt-5.6-sol', got '{model}'")

        def _parse_rubric(data: object) -> EvaluationCreateInRubricType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                rubric_type_0 = EvaluationCreateInRubricType0.from_dict(data)

                return rubric_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(EvaluationCreateInRubricType0 | None | Unset, data)

        rubric = _parse_rubric(d.pop("rubric", UNSET))

        evaluation_create_in = cls(
            cases=cases,
            model=model,
            rubric=rubric,
        )

        return evaluation_create_in
