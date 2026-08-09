from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.record_in_context import RecordInContext
    from ..models.record_in_metadata import RecordInMetadata
    from ..models.record_in_value import RecordInValue


T = TypeVar("T", bound="RecordIn")


@_attrs_define
class RecordIn:
    """
    Attributes:
        value (RecordInValue):
        context (RecordInContext | Unset):
        idempotency_key (None | str | Unset):
        metadata (RecordInMetadata | Unset):
    """

    value: RecordInValue
    context: RecordInContext | Unset = UNSET
    idempotency_key: None | str | Unset = UNSET
    metadata: RecordInMetadata | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        value = self.value.to_dict()

        context: dict[str, Any] | Unset = UNSET
        if not isinstance(self.context, Unset):
            context = self.context.to_dict()

        idempotency_key: None | str | Unset
        if isinstance(self.idempotency_key, Unset):
            idempotency_key = UNSET
        else:
            idempotency_key = self.idempotency_key

        metadata: dict[str, Any] | Unset = UNSET
        if not isinstance(self.metadata, Unset):
            metadata = self.metadata.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "value": value,
            }
        )
        if context is not UNSET:
            field_dict["context"] = context
        if idempotency_key is not UNSET:
            field_dict["idempotency_key"] = idempotency_key
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.record_in_context import RecordInContext
        from ..models.record_in_metadata import RecordInMetadata
        from ..models.record_in_value import RecordInValue

        d = dict(src_dict)
        value = RecordInValue.from_dict(d.pop("value"))

        _context = d.pop("context", UNSET)
        context: RecordInContext | Unset
        if isinstance(_context, Unset):
            context = UNSET
        else:
            context = RecordInContext.from_dict(_context)

        def _parse_idempotency_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        idempotency_key = _parse_idempotency_key(d.pop("idempotency_key", UNSET))

        _metadata = d.pop("metadata", UNSET)
        metadata: RecordInMetadata | Unset
        if isinstance(_metadata, Unset):
            metadata = UNSET
        else:
            metadata = RecordInMetadata.from_dict(_metadata)

        record_in = cls(
            value=value,
            context=context,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

        return record_in
