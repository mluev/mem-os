from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define

if TYPE_CHECKING:
    from ..models.admin_health_out_database import AdminHealthOutDatabase
    from ..models.admin_health_out_embedder import AdminHealthOutEmbedder
    from ..models.admin_health_out_jobs import AdminHealthOutJobs
    from ..models.admin_health_out_outbox import AdminHealthOutOutbox
    from ..models.admin_health_out_qdrant import AdminHealthOutQdrant


T = TypeVar("T", bound="AdminHealthOut")


@_attrs_define
class AdminHealthOut:
    """
    Attributes:
        database (AdminHealthOutDatabase):
        embedder (AdminHealthOutEmbedder):
        jobs (AdminHealthOutJobs):
        outbox (AdminHealthOutOutbox):
        qdrant (AdminHealthOutQdrant):
    """

    database: AdminHealthOutDatabase
    embedder: AdminHealthOutEmbedder
    jobs: AdminHealthOutJobs
    outbox: AdminHealthOutOutbox
    qdrant: AdminHealthOutQdrant

    def to_dict(self) -> dict[str, Any]:
        database = self.database.to_dict()

        embedder = self.embedder.to_dict()

        jobs = self.jobs.to_dict()

        outbox = self.outbox.to_dict()

        qdrant = self.qdrant.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
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
        from ..models.admin_health_out_database import AdminHealthOutDatabase
        from ..models.admin_health_out_embedder import AdminHealthOutEmbedder
        from ..models.admin_health_out_jobs import AdminHealthOutJobs
        from ..models.admin_health_out_outbox import AdminHealthOutOutbox
        from ..models.admin_health_out_qdrant import AdminHealthOutQdrant

        d = dict(src_dict)
        database = AdminHealthOutDatabase.from_dict(d.pop("database"))

        embedder = AdminHealthOutEmbedder.from_dict(d.pop("embedder"))

        jobs = AdminHealthOutJobs.from_dict(d.pop("jobs"))

        outbox = AdminHealthOutOutbox.from_dict(d.pop("outbox"))

        qdrant = AdminHealthOutQdrant.from_dict(d.pop("qdrant"))

        admin_health_out = cls(
            database=database,
            embedder=embedder,
            jobs=jobs,
            outbox=outbox,
            qdrant=qdrant,
        )

        return admin_health_out
