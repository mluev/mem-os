"""Immutable, provider-neutral experiment archives and integrity-checked comparisons."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def code_identity() -> dict[str, Any]:
    """Include working-copy hashes: HEAD alone cannot identify uncommitted experiments."""
    root = Path(__file__).resolve().parents[1]
    files = [p for folder in ("src/memkit", "eval") for p in (root / folder).rglob("*.py")]
    hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)
    }
    head = subprocess.run(  # noqa: S603
        [shutil.which("git") or "/usr/bin/git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    return {"git_head": head or None, "source_sha256": sha(hashes), "files": hashes}


def _models(value: Any) -> list[str]:
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "model" and isinstance(item, str):
                found.add(item)
            else:
                found.update(_models(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_models(item))
    return sorted(found)


def archive(
    artifact: dict[str, Any],
    *,
    root: Path,
    name: str,
    hypothesis: str,
    decision: str,
    limitations: list[str],
    data_class: str,
    label_source: str,
    technology: str = "Jev",
    source_name: str = "",
    compress: bool = False,
) -> Path:
    """Save exact results plus a manifest/report; never overwrite a previous run.

    The caller classifies the data. Public repository archives accept synthetic
    fixtures only. Private results default to local ignored storage; redaction
    alone does not make a user's text public or authorize publication.
    """
    if decision not in {"adopt", "observe", "reject", "inconclusive"}:
        raise ValueError("invalid experiment decision")
    if data_class not in {"synthetic", "private"}:
        raise ValueError("data_class must be synthetic or private")
    if not hypothesis.strip() or not label_source.strip() or not limitations:
        raise ValueError("hypothesis, label source and limitations are required")
    repository = Path(__file__).resolve().parents[1]
    if (
        data_class != "synthetic"
        and root.resolve().is_relative_to(repository)
        and not root.resolve().is_relative_to(repository / "data")
    ):
        raise ValueError("private results must stay outside tracked repository paths")
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64]
    if not slug:
        raise ValueError("experiment needs a name")
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%dT%H%M%S%fZ}-{slug}-{uuid.uuid4().hex[:8]}"
    payload = json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    metrics = artifact.get("metrics") or {
        k: artifact[k] for k in ("baseline", "filtered", "errors", "jev_usage") if k in artifact
    }
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "name": name,
        "archived_at": now.isoformat(),
        "source_name": source_name,
        "technology": technology,
        "models": _models(artifact),
        "hypothesis": hypothesis,
        "decision": decision,
        "limitations": limitations,
        "data_class": data_class,
        "label_source": label_source,
        "dataset_sha256": artifact.get("corpus_sha256") or artifact.get("signature"),
        "split": artifact.get("split", "diagnostic"),
        "questions_sha256": artifact.get("questions_sha256", artifact.get("question_sha256")),
        "thresholds": artifact.get("thresholds", {"support_floor": artifact.get("support_floor")}),
        "repeat": artifact.get("repeat", 1),
        "metrics": metrics,
        "slices": {
            k: artifact[k] for k in ("by_language", "by_scenario", "by_cohort") if k in artifact
        },
        "execution_provenance": artifact.get("provenance"),
        "archive_provenance": code_identity(),
        "artifact_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "artifact_file": "artifact.json.gz" if compress else "artifact.json",
    }
    folder = root / run_id
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    artifact_path = folder / manifest["artifact_file"]
    if compress:
        artifact_path.write_bytes(gzip.compress(payload.encode(), mtime=0))
    else:
        artifact_path.write_text(payload)
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    report = (
        f"# {name}\n\nDecision: **{decision}**. Technology: {technology}. "
        f"Models: {', '.join(manifest['models']) or 'not recorded'}.\n\n"
        f"{hypothesis}\n\nLabels: {label_source}. Data: {data_class}. "
        f"Split: {manifest['split']}; repeats: {manifest['repeat']} (not independent examples).\n\n"
        f"## Results\n\n```json\n{json.dumps(metrics, ensure_ascii=False, indent=2)}\n```\n\n"
        "## Limits and decision context\n\n"
        + "\n".join(f"- {s}" for s in limitations)
        + f"\n\n[Exact results]({manifest['artifact_file']}) · [Provenance and slices](manifest.json)\n"
    )
    (folder / "report.md").write_text(report)
    return folder


def read_run(folder: Path) -> dict[str, Any]:
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["schema_version"] != 1:
        raise ValueError("unsupported report schema")
    name = manifest.get("artifact_file", "artifact.json")
    if name not in {"artifact.json", "artifact.json.gz"}:
        raise ValueError("invalid artifact filename")
    payload = (folder / name).read_bytes()
    if name.endswith(".gz"):
        payload = gzip.decompress(payload)
    if hashlib.sha256(payload).hexdigest() != manifest["artifact_sha256"]:
        raise ValueError("experiment artifact integrity failure")
    return manifest


def compare(left: Path, right: Path) -> dict[str, Any]:
    a, b = read_run(left), read_run(right)
    mismatches = [
        key for key in ("dataset_sha256", "split", "thresholds", "label_source") if a[key] != b[key]
    ]
    if a["dataset_sha256"] is None or b["dataset_sha256"] is None:
        mismatches.append("missing dataset identity")
    return {
        "comparable": not mismatches,
        "mismatches": mismatches,
        "note": "Compare rates and denominators; repeated runs are not independent samples.",
        "left": {"run_id": a["run_id"], "metrics": a["metrics"], "slices": a["slices"]},
        "right": {"run_id": b["run_id"], "metrics": b["metrics"], "slices": b["slices"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    save = sub.add_parser("archive")
    save.add_argument("input", type=Path)
    save.add_argument("--root", type=Path, default=Path("data/experiments"))
    save.add_argument("--name", required=True)
    save.add_argument("--hypothesis", required=True)
    save.add_argument(
        "--decision", choices=["adopt", "observe", "reject", "inconclusive"], required=True
    )
    save.add_argument("--limitation", action="append", required=True)
    save.add_argument("--data-class", choices=["synthetic", "private"], required=True)
    save.add_argument("--label-source", required=True)
    save.add_argument("--technology", default="Jev")
    save.add_argument("--compress", action="store_true")
    diff = sub.add_parser("compare")
    diff.add_argument("left", type=Path)
    diff.add_argument("right", type=Path)
    check = sub.add_parser("check")
    check.add_argument("root", type=Path)
    args = parser.parse_args()
    if args.command == "compare":
        result = compare(args.left, args.right)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(not result["comparable"])
    if args.command == "check":
        runs = list(args.root.rglob("manifest.json"))
        for manifest in runs:
            read_run(manifest.parent)
        print(f"Validated {len(runs)} archived experiments")
        return 0
    folder = archive(
        json.loads(args.input.read_text()),
        root=args.root,
        name=args.name,
        hypothesis=args.hypothesis,
        decision=args.decision,
        limitations=args.limitation,
        data_class=args.data_class,
        label_source=args.label_source,
        technology=args.technology,
        source_name=args.input.name,
        compress=args.compress,
    )
    print(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
