from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.admin_health_out_jobs import AdminHealthOutJobs
    from ..models.database_health import DatabaseHealth
    from ..models.embedder_health import EmbedderHealth
    from ..models.outbox_health import OutboxHealth
    from ..models.runtime_config import RuntimeConfig
    from ..models.vector_health import VectorHealth


T = TypeVar("T", bound="AdminHealthOut")


@_attrs_define
class AdminHealthOut:
    """
    Attributes:
        config (RuntimeConfig): The non-secret settings that decide what extraction and search do.

            A benchmark run records this block, so a number can always be traced to
            the prompt, policy and dreaming mode that produced it.
        database (DatabaseHealth):
        embedder (EmbedderHealth):
        jobs (AdminHealthOutJobs):
        outbox (OutboxHealth):
        qdrant (VectorHealth):
    """

    config: RuntimeConfig
    database: DatabaseHealth
    embedder: EmbedderHealth
    jobs: AdminHealthOutJobs
    outbox: OutboxHealth
    qdrant: VectorHealth
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        database = self.database.to_dict()

        embedder = self.embedder.to_dict()

        jobs = self.jobs.to_dict()

        outbox = self.outbox.to_dict()

        qdrant = self.qdrant.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "config": config,
                "database": database,
                "embedder": embedder,
                "jobs": jobs,
                "outbox": outbox,
                "qdrant": qdrant,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.admin_health_out_jobs import AdminHealthOutJobs
        from ..models.database_health import DatabaseHealth
        from ..models.embedder_health import EmbedderHealth
        from ..models.outbox_health import OutboxHealth
        from ..models.runtime_config import RuntimeConfig
        from ..models.vector_health import VectorHealth

        d = dict(src_dict)
        config = RuntimeConfig.from_dict(d.pop("config"))

        database = DatabaseHealth.from_dict(d.pop("database"))

        embedder = EmbedderHealth.from_dict(d.pop("embedder"))

        jobs = AdminHealthOutJobs.from_dict(d.pop("jobs"))

        outbox = OutboxHealth.from_dict(d.pop("outbox"))

        qdrant = VectorHealth.from_dict(d.pop("qdrant"))

        admin_health_out = cls(
            config=config,
            database=database,
            embedder=embedder,
            jobs=jobs,
            outbox=outbox,
            qdrant=qdrant,
        )

        admin_health_out.additional_properties = d
        return admin_health_out

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
