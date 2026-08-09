from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

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
        embedding_fields (list[str] | Unset):
        indexed_fields (list[str] | Unset):
        policy (CollectionInPolicy | Unset):
    """

    name: str
    schema: CollectionInSchema
    embedding_fields: list[str] | Unset = UNSET
    indexed_fields: list[str] | Unset = UNSET
    policy: CollectionInPolicy | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        schema = self.schema.to_dict()

        embedding_fields: list[str] | Unset = UNSET
        if not isinstance(self.embedding_fields, Unset):
            embedding_fields = self.embedding_fields

        indexed_fields: list[str] | Unset = UNSET
        if not isinstance(self.indexed_fields, Unset):
            indexed_fields = self.indexed_fields

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
        if embedding_fields is not UNSET:
            field_dict["embedding_fields"] = embedding_fields
        if indexed_fields is not UNSET:
            field_dict["indexed_fields"] = indexed_fields
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

        embedding_fields = cast(list[str], d.pop("embedding_fields", UNSET))

        indexed_fields = cast(list[str], d.pop("indexed_fields", UNSET))

        _policy = d.pop("policy", UNSET)
        policy: CollectionInPolicy | Unset
        if isinstance(_policy, Unset):
            policy = UNSET
        else:
            policy = CollectionInPolicy.from_dict(_policy)

        collection_in = cls(
            name=name,
            schema=schema,
            embedding_fields=embedding_fields,
            indexed_fields=indexed_fields,
            policy=policy,
        )

        return collection_in
