from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

T = TypeVar("T", bound="ReadyOut")


@_attrs_define
class ReadyOut:
    """
    Attributes:
        database (bool):
        embedder (bool):
        qdrant (bool):
        ready (bool):
    """

    database: bool
    embedder: bool
    qdrant: bool
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        database = self.database

        embedder = self.embedder

        qdrant = self.qdrant

        ready = self.ready

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "database": database,
                "embedder": embedder,
                "qdrant": qdrant,
                "ready": ready,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        database = d.pop("database")

        embedder = d.pop("embedder")

        qdrant = d.pop("qdrant")

        ready = d.pop("ready")

        ready_out = cls(
            database=database,
            embedder=embedder,
            qdrant=qdrant,
            ready=ready,
        )

        return ready_out
