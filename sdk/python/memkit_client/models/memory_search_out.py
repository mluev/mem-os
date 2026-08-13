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
        raw (list[MemorySearchOutRawItem]):
        took_ms (float):
        used_tokens (int):
        retrieval_id (None | str | Unset):
        timings (MemorySearchOutTimings | Unset):
    """

    dropped_filter: list[str]
    dropped_relevance: list[str]
    dropped_trust: list[str]
    dropped_validity: list[str]
    embed_ms: float
    memories: list[MemorySearchOutMemoriesItem]
    policy_id: str
    raw: list[MemorySearchOutRawItem]
    took_ms: float
    used_tokens: int
    retrieval_id: None | str | Unset = UNSET
    timings: MemorySearchOutTimings | Unset = UNSET

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

        raw = []
        for raw_item_data in self.raw:
            raw_item = raw_item_data.to_dict()
            raw.append(raw_item)

        took_ms = self.took_ms

        used_tokens = self.used_tokens

        retrieval_id: None | str | Unset
        if isinstance(self.retrieval_id, Unset):
            retrieval_id = UNSET
        else:
            retrieval_id = self.retrieval_id

        timings: dict[str, Any] | Unset = UNSET
        if not isinstance(self.timings, Unset):
            timings = self.timings.to_dict()

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
                "raw": raw,
                "took_ms": took_ms,
                "used_tokens": used_tokens,
            }
        )
        if retrieval_id is not UNSET:
            field_dict["retrieval_id"] = retrieval_id
        if timings is not UNSET:
            field_dict["timings"] = timings

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

        raw = []
        _raw = d.pop("raw")
        for raw_item_data in _raw:
            raw_item = MemorySearchOutRawItem.from_dict(raw_item_data)

            raw.append(raw_item)

        took_ms = d.pop("took_ms")

        used_tokens = d.pop("used_tokens")

        def _parse_retrieval_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        retrieval_id = _parse_retrieval_id(d.pop("retrieval_id", UNSET))

        _timings = d.pop("timings", UNSET)
        timings: MemorySearchOutTimings | Unset
        if isinstance(_timings, Unset):
            timings = UNSET
        else:
            timings = MemorySearchOutTimings.from_dict(_timings)

        memory_search_out = cls(
            dropped_filter=dropped_filter,
            dropped_relevance=dropped_relevance,
            dropped_trust=dropped_trust,
            dropped_validity=dropped_validity,
            embed_ms=embed_ms,
            memories=memories,
            policy_id=policy_id,
            raw=raw,
            took_ms=took_ms,
            used_tokens=used_tokens,
            retrieval_id=retrieval_id,
            timings=timings,
        )

        return memory_search_out
