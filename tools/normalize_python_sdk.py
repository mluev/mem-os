"""Apply Memkit's API-key contract to openapi-python-client output."""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "sdk" / "python" / "memkit_client" / "client.py"
MODELS = CLIENT.parent / "models"
README = ROOT / "sdk" / "python" / "README.md"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"generator output changed; expected text absent from {path}")
    path.write_text(text.replace(old, new, 1))


# Published 0.3 dictionary wrappers retain their module paths and constructors.
# New responses use named views, while these aliases still accept arbitrary JSON.
LEGACY_DICTIONARIES = {
    "memory_history_out_memory": "MemoryHistoryOutMemory",
    "memory_history_out_predecessors_item": "MemoryHistoryOutPredecessorsItem",
    "memory_history_out_revisions_item": "MemoryHistoryOutRevisionsItem",
    "memory_history_out_successor_type_0": "MemoryHistoryOutSuccessorType0",
    "memory_out_memory": "MemoryOutMemory",
    "memory_search_out_memories_item": "MemorySearchOutMemoriesItem",
    "memory_sources_out_evidence_item": "MemorySourcesOutEvidenceItem",
    "memory_sources_out_memory": "MemorySourcesOutMemory",
    "offset_page_out_items_item": "OffsetPageOutItemsItem",
    "profile_out_blocks_additional_property_item": "ProfileOutBlocksAdditionalPropertyItem",
    "session_messages_out_items_item": "SessionMessagesOutItemsItem",
    "session_messages_out_session": "SessionMessagesOutSession",
    "session_out_user": "SessionOutUser",
}


def preserve_model_compatibility() -> None:
    document = json.loads((ROOT / "openapi.json").read_text())
    response_names: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/components/schemas/"):
                name = ref.rsplit("/", 1)[-1]
                if name not in response_names:
                    response_names.add(name)
                    visit(document["components"]["schemas"][name])
            for item in value.values():
                visit(item)

    for methods in document["paths"].values():
        for operation in methods.values():
            visit(operation.get("responses", {}))
    for path in MODELS.glob("*.py"):
        source = path.read_text()
        classes = {n.name for n in ast.parse(source).body if isinstance(n, ast.ClassDef)}
        if not classes & response_names:
            continue
        # Typed attributes now hold keys that used to live in additional_properties.
        # Retain JSON dictionary reads, including nested objects, for old clients.
        source = source.replace(
            "return self.additional_properties[key]", "return self.to_dict()[key]"
        )
        source = source.replace(
            "return key in self.additional_properties", "return key in self.to_dict()"
        )
        path.write_text(source)

    index = MODELS / "__init__.py"
    source = index.read_text()
    exports = dict(LEGACY_DICTIONARIES)
    for module, name in LEGACY_DICTIONARIES.items():
        (MODELS / f"{module}.py").write_text(
            f'"""Compatibility alias for the original dictionary response."""\n\n'
            f"from .flexible_out import FlexibleOut as {name}\n\n"
            f'__all__ = ["{name}"]\n'
        )
    (MODELS / "offset_page_out.py").write_text(
        (ROOT / "tools" / "python_sdk_compat" / "offset_page_out.py").read_text()
    )
    exports["offset_page_out"] = "OffsetPageOut"
    imports = "".join(f"from .{module} import {name}\n" for module, name in sorted(exports.items()))
    source = source.replace("__all__ = (", imports + "\n__all__ = (")
    source = (
        source.rstrip().removesuffix(")")
        + "".join(f'    "{name}",\n' for name in sorted(exports.values()))
        + ")\n"
    )
    index.write_text(source)


def main() -> int:
    replace_once(CLIENT, 'prefix: str = "Bearer"', 'prefix: str = ""')
    replace_once(
        CLIENT,
        'auth_header_name: str = "Authorization"',
        'auth_header_name: str = "X-API-Key"',
    )
    marker = "`AuthenticatedClient` sends the token in Memkit's required `X-API-Key` header."
    readme = README.read_text()
    if marker not in readme:
        needle = 'client = AuthenticatedClient(base_url="https://api.example.com", token="SuperSecretToken")\n```'
        if needle not in readme:
            raise RuntimeError("generator README template changed")
        README.write_text(readme.replace(needle, f"{needle}\n\n{marker}", 1))
    preserve_model_compatibility()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
