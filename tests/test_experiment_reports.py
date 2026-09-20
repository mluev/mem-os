"""Experiment history survives reruns, checks integrity and refuses invalid comparisons."""

import gzip
import json

import pytest

from eval.reports import archive, compare, read_run


@pytest.fixture(autouse=True)
def clean_database():
    yield


def save(tmp_path, **overrides):
    artifact = {
        "corpus_sha256": "frozen-corpus",
        "split": "heldout",
        "thresholds": {"duplicate_floor": 0.9},
        "metrics": {"errors": 0},
        **overrides,
    }
    return archive(
        artifact,
        root=tmp_path,
        name="new-model",
        hypothesis="Improve precision",
        decision="observe",
        limitations=["Small synthetic corpus"],
        data_class="synthetic",
        label_source="author",
    )


def test_history_and_integrity(tmp_path):
    first, second = save(tmp_path), save(tmp_path)
    assert first != second
    assert read_run(first)["execution_provenance"] is None  # do not invent historical provenance
    assert compare(first, second)["comparable"]
    (first / "artifact.json").write_text("{}")
    with pytest.raises(ValueError, match="integrity"):
        read_run(first)


def test_comparison_rejects_dataset_or_policy_drift(tmp_path):
    first = save(tmp_path)
    changed = save(tmp_path, corpus_sha256="other-corpus", thresholds={"duplicate_floor": 0.5})
    result = compare(first, changed)
    assert not result["comparable"]
    assert result["mismatches"] == ["dataset_sha256", "thresholds"]


def test_private_report_cannot_be_saved_under_docs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "docs" / "experiments"
    with pytest.raises(ValueError, match="private"):
        archive(
            {},
            root=root,
            name="private",
            hypothesis="h",
            decision="observe",
            limitations=["l"],
            data_class="private",
            label_source="user",
        )


def test_provider_and_execution_provenance_are_retained(tmp_path):
    run = save(
        tmp_path,
        provenance={"source_sha256": "execution-code"},
        records=[{"judgment": {"model": "other-model"}}],
    )
    manifest = read_run(run)
    assert manifest["models"] == ["other-model"]
    assert manifest["execution_provenance"]["source_sha256"] == "execution-code"
    assert "other-model" in (run / "report.md").read_text()
    assert json.loads((run / "artifact.json").read_text())["records"]


def test_compressed_archive_verifies_original_json_and_detects_tampering(tmp_path):
    artifact = {"metrics": {"correct": 7}, "records": [{"text": "verbatim evidence"}]}
    folder = archive(
        artifact,
        root=tmp_path,
        name="compressed",
        hypothesis="Preserve exact results",
        decision="observe",
        limitations=["Synthetic"],
        data_class="synthetic",
        label_source="author",
        compress=True,
    )
    assert read_run(folder)["metrics"] == {"correct": 7}
    path = folder / "artifact.json.gz"
    assert json.loads(gzip.decompress(path.read_bytes())) == artifact
    path.write_bytes(gzip.compress(b"{}"))
    with pytest.raises(ValueError, match="integrity"):
        read_run(folder)
