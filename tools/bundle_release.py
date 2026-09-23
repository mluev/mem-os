"""Gather built distributions, committed source and recovery docs with checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

from memkit.db import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git")
if GIT is None:
    raise SystemExit("Git is required to bundle committed source.")


def git(*args: str) -> str:
    return subprocess.check_output([GIT, *args], cwd=ROOT, text=True).strip()  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-bundle")
    args = parser.parse_args()
    target = args.output.resolve()
    archive = target.with_name(target.name + ".tar.gz")
    checksum_path = archive.with_name(archive.name + ".sha256")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Commit tracked changes before bundling; source provenance must be exact.")
    if any(path.exists() or path.is_symlink() for path in (target, archive, checksum_path)):
        raise SystemExit(f"Output already exists: {target}; choose a fresh output directory.")
    packages = []
    for pattern in (
        "dist/memkit-*.whl",
        "cli/dist/memos_cli-*.whl",
        "sdk/python/dist/memkit_client-*.whl",
        "dist/memkit-sdk-*.tgz",
    ):
        matches = list(ROOT.glob(pattern))
        if len(matches) != 1:
            raise SystemExit(f"Expected exactly one package matching {pattern}; build it first.")
        packages.extend(matches)
    requirements = ROOT / "dist/requirements.txt"
    if not requirements.is_file():
        raise SystemExit("Export locked production requirements to dist/requirements.txt first.")
    revision = git("rev-parse", "HEAD")
    target.mkdir(parents=True)
    (target / "packages").mkdir()
    for package in packages:
        shutil.copy2(package, target / "packages" / package.name)
    for path in (requirements, ROOT / "uv.lock", ROOT / "openapi.json"):
        shutil.copy2(path, target / path.name)
    for relative in git("ls-files", "-z", "--", "docs").split("\0"):
        if not relative:
            continue
        source = ROOT / relative
        if source.is_symlink():
            raise SystemExit(f"Documentation symlinks are not supported: {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    guide = Path("skills/mem-os")
    shutil.copytree(ROOT / guide, target / guide, ignore=shutil.ignore_patterns("__pycache__"))
    references = sorted((ROOT / guide / "references").glob("*.md"))
    (target / "AGENT-GUIDE.md").write_text(
        f"# Agent guide\n\n[Memkit skill: capabilities and commands]({guide}/SKILL.md)\n\n"
        + "".join(
            f"- [{path.stem.replace('-', ' ').capitalize()}]({guide}/references/{path.name})\n"
            for path in references
        )
    )
    subprocess.run(  # noqa: S603 -- committed repository archive only
        [GIT, "archive", "--format=tar.gz", f"--output={target / 'source.tar.gz'}", revision],
        cwd=ROOT,
        check=True,
    )
    (target / "README.md").write_text(
        f"# Mem OS release candidate\n\nSource commit: `{revision}`.\n\n"
        "Contains the server wheel, standalone CLI, Python and TypeScript SDKs, "
        "committed source, dependency lock, OpenAPI, agent guide, and all review/recovery docs.\n\n"
        "Verify SHA256SUMS before installation. See docs/09-operations.md for upgrade, "
        "erasure replay and offline recovery. The schema-v2 server wheel can be retained "
        "as an application rollback checkpoint; pre-v2 binaries are not compatible.\n\n"
        "See docs/releases/2026-09-20-handoff.md and the readiness review for validation "
        "and remaining retrieval-quality limits. Packaging does not deploy the service.\n"
    )
    manifest = {
        "source_commit": revision,
        "schema_version": SCHEMA_VERSION,
        "package_provenance": (
            "Packages are prebuilt inputs. CI rebuilds them at this checkout; "
            "local callers must do the same. The bundler verifies committed source "
            "and file checksums, not package build provenance."
        ),
        "files": [
            {
                "path": str(path.relative_to(target)),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in sorted(target.rglob("*"))
            if path.is_file()
        ],
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (target / "SHA256SUMS").write_text(
        "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(target)}\n"
            for path in sorted(target.rglob("*"))
            if path.is_file()
        )
    )
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(target, arcname="mem-os-release")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum_path.write_text(f"{checksum}  {archive.name}\n")
    print(json.dumps({"archive": str(archive), "sha256": checksum, "source_commit": revision}))


if __name__ == "__main__":
    main()
