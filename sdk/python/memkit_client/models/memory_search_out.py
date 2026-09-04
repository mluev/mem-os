from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.memory_search_out_memories_item import MemorySearchOutMemoriesItem
    from ..models.memory_search_out_raw_item import MemorySearchOutRawItem
    from ..models.memory_search_out_timings import MemorySearchOutTimings


T = TypeVar("T", bound="MemorySearchOut")


@_attrs_define
class MemorySearchOut:
    """
    Attributes:
        dropped_filter (list[str]):
        dropped_relevance (list[str]):
        dropped_trust (list[str]):
        dropped_validity (list[str]):
        embed_ms (float):
        memories (list[MemorySearchOutMemoriesItem]):
        policy_id (str):
        timings (MemorySearchOutTimings):
        used_tokens (int):
        raw (list[MemorySearchOutRawItem] | Unset):
        retrieval_id (None | str | Unset):
    """

    dropped_filter: list[str]
    dropped_relevance: list[str]
    dropped_trust: list[str]
    dropped_validity: list[str]
    embed_ms: float
    memories: list[MemorySearchOutMemoriesItem]
    policy_id: str
    timings: MemorySearchOutTimings
    used_tokens: int
    raw: list[MemorySearchOutRawItem] | Unset = UNSET
    retrieval_id: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        dropped_filter = self.dropped_filter

        dropped_relevance = self.dropped_relevance

        dropped_trust = self.dropped_trust

        dropped_validity = self.dropped_validity

        embed_ms = self.embed_ms

        memories = []
        for memories_item_data in self.memories:
            memories_item = memories_item_data.to_dict()
            memories.append(memories_item)

        policy_id = self.policy_id

        timings = self.timings.to_dict()

        used_tokens = self.used_tokens

        raw: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.raw, Unset):
            raw = []
            for raw_item_data in self.raw:
                raw_item = raw_item_data.to_dict()
                raw.append(raw_item)

        retrieval_id: None | str | Unset
        if isinstance(self.retrieval_id, Unset):
            retrieval_id = UNSET
        else:
            retrieval_id = self.retrieval_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "dropped_filter": dropped_filter,
                "dropped_relevance": dropped_relevance,
                "dropped_trust": dropped_trust,
                "dropped_validity": dropped_validity,
                "embed_ms": embed_ms,
                "memories": memories,
                "policy_id": policy_id,
                "timings": timings,
                "used_tokens": used_tokens,
            }
        )
        if raw is not UNSET:
            field_dict["raw"] = raw
        if retrieval_id is not UNSET:
            field_dict["retrieval_id"] = retrieval_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.memory_search_out_memories_item import MemorySearchOutMemoriesItem
        from ..models.memory_search_out_raw_item import MemorySearchOutRawItem
        from ..models.memory_search_out_timings import MemorySearchOutTimings

        d = dict(src_dict)
        dropped_filter = cast(list[str], d.pop("dropped_filter"))

        dropped_relevance = cast(list[str], d.pop("dropped_relevance"))

        dropped_trust = cast(list[str], d.pop("dropped_trust"))

        dropped_validity = cast(list[str], d.pop("dropped_validity"))

        embed_ms = d.pop("embed_ms")

        memories = []
        _memories = d.pop("memories")
        for memories_item_data in _memories:
            memories_item = MemorySearchOutMemoriesItem.from_dict(memories_item_data)

            memories.append(memories_item)

        policy_id = d.pop("policy_id")

        timings = MemorySearchOutTimings.from_dict(d.pop("timings"))

        used_tokens = d.pop("used_tokens")

        _raw = d.pop("raw", UNSET)
        raw: list[MemorySearchOutRawItem] | Unset = UNSET
        if _raw is not UNSET:
            raw = []
            for raw_item_data in _raw:
                raw_item = MemorySearchOutRawItem.from_dict(raw_item_data)

                raw.append(raw_item)

        def _parse_retrieval_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        retrieval_id = _parse_retrieval_id(d.pop("retrieval_id", UNSET))

        memory_search_out = cls(
            dropped_filter=dropped_filter,
            dropped_relevance=dropped_relevance,
            dropped_trust=dropped_trust,
            dropped_validity=dropped_validity,
            embed_ms=embed_ms,
            memories=memories,
            policy_id=policy_id,
            timings=timings,
            used_tokens=used_tokens,
            raw=raw,
            retrieval_id=retrieval_id,
        )

        return memory_search_out
