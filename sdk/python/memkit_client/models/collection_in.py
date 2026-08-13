from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.collection_in_policy import CollectionInPolicy
    from ..models.collection_in_schema import CollectionInSchema


T = TypeVar("T", bound="CollectionIn")


@_attrs_define
class CollectionIn:
    """
    Attributes:
        name (str):
        schema (CollectionInSchema):
        policy (CollectionInPolicy | Unset):
    """

    name: str
    schema: CollectionInSchema
    policy: CollectionInPolicy | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        schema = self.schema.to_dict()

        policy: dict[str, Any] | Unset = UNSET
        if not isinstance(self.policy, Unset):
            policy = self.policy.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "schema": schema,
            }
        )
        if policy is not UNSET:
            field_dict["policy"] = policy

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.collection_in_policy import CollectionInPolicy
        from ..models.collection_in_schema import CollectionInSchema

        d = dict(src_dict)
        name = d.pop("name")

        schema = CollectionInSchema.from_dict(d.pop("schema"))

        _policy = d.pop("policy", UNSET)
        policy: CollectionInPolicy | Unset
        if isinstance(_policy, Unset):
            policy = UNSET
        else:
            policy = CollectionInPolicy.from_dict(_policy)

        collection_in = cls(
            name=name,
            schema=schema,
            policy=policy,
        )

        return collection_in
