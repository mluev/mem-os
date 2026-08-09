from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.record_patch_context_type_0 import RecordPatchContextType0
    from ..models.record_patch_metadata_type_0 import RecordPatchMetadataType0
    from ..models.record_patch_value import RecordPatchValue


T = TypeVar("T", bound="RecordPatch")


@_attrs_define
class RecordPatch:
    """
    Attributes:
        expected_revision (int):
        value (RecordPatchValue):
        context (None | RecordPatchContextType0 | Unset):
        metadata (None | RecordPatchMetadataType0 | Unset):
    """

    expected_revision: int
    value: RecordPatchValue
    context: None | RecordPatchContextType0 | Unset = UNSET
    metadata: None | RecordPatchMetadataType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.record_patch_context_type_0 import RecordPatchContextType0
        from ..models.record_patch_metadata_type_0 import RecordPatchMetadataType0

        expected_revision = self.expected_revision

        value = self.value.to_dict()

        context: dict[str, Any] | None | Unset
        if isinstance(self.context, Unset):
            context = UNSET
        elif isinstance(self.context, RecordPatchContextType0):
            context = self.context.to_dict()
        else:
            context = self.context

        metadata: dict[str, Any] | None | Unset
        if isinstance(self.metadata, Unset):
            metadata = UNSET
        elif isinstance(self.metadata, RecordPatchMetadataType0):
            metadata = self.metadata.to_dict()
        else:
            metadata = self.metadata

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "expected_revision": expected_revision,
                "value": value,
            }
        )
        if context is not UNSET:
            field_dict["context"] = context
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.record_patch_context_type_0 import RecordPatchContextType0
        from ..models.record_patch_metadata_type_0 import RecordPatchMetadataType0
        from ..models.record_patch_value import RecordPatchValue

        d = dict(src_dict)
        expected_revision = d.pop("expected_revision")

        value = RecordPatchValue.from_dict(d.pop("value"))

        def _parse_context(data: object) -> None | RecordPatchContextType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                context_type_0 = RecordPatchContextType0.from_dict(data)

                return context_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RecordPatchContextType0 | Unset, data)

        context = _parse_context(d.pop("context", UNSET))

        def _parse_metadata(data: object) -> None | RecordPatchMetadataType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                metadata_type_0 = RecordPatchMetadataType0.from_dict(data)

                return metadata_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RecordPatchMetadataType0 | Unset, data)

        metadata = _parse_metadata(d.pop("metadata", UNSET))

        record_patch = cls(
            expected_revision=expected_revision,
            value=value,
            context=context,
            metadata=metadata,
        )

        return record_patch
