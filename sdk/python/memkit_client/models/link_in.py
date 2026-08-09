from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.link_in_metadata import LinkInMetadata


T = TypeVar("T", bound="LinkIn")


@_attrs_define
class LinkIn:
    """
    Attributes:
        from_ref (str):
        relation (str):
        to_ref (str):
        metadata (LinkInMetadata | Unset):
    """

    from_ref: str
    relation: str
    to_ref: str
    metadata: LinkInMetadata | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from_ref = self.from_ref

        relation = self.relation

        to_ref = self.to_ref

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "from_ref": from_ref,
                "relation": relation,
                "to_ref": to_ref,
            }
        )
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.link_in_metadata import LinkInMetadata

        d = dict(src_dict)
        from_ref = d.pop("from_ref")

        relation = d.pop("relation")

        to_ref = d.pop("to_ref")

        _metadata = d.pop("metadata", UNSET)
        metadata: LinkInMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = LinkInMetadata.from_dict(_metadata)

        link_in = cls(
            from_ref=from_ref,
            relation=relation,
            to_ref=to_ref,
            metadata=metadata,
        )

        return link_in
