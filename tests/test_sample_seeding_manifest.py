"""Tests for POR-69 T4: additive manifest-based sample seeding.

Covers ``PromptManager._seed_from_samples`` manifest semantics:
- Fresh install (empty templates dir, no manifest) copies every sample
  and writes the ``.seeded_samples`` manifest.
- First run on an existing install (>=1 .yaml present, no manifest)
  copies nothing and records all shipped sample basenames as seen.
- A newly shipped sample is copied on the next run while already-seen
  samples are left alone.
- A user-deleted sample listed in the manifest is not resurrected.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from streamdoc.integrations.notebooklm.prompts import PromptManager

MANIFEST_NAME = ".seeded_samples"
SAMPLE_NAMES = ("alpha.yaml", "beta.yaml", "gamma.yaml")


def _write_template(path: Path, name: str | None = None) -> None:
    """Write a minimal valid template YAML file.

    Args:
        path: Destination file path.
        name: Template name embedded in the YAML; defaults to the file stem.
    """
    path.write_text(
        yaml.dump({"name": name or path.stem, "prompt": "do {content_type}"}),
        encoding="utf-8",
    )


def _make_samples(samples_dir: Path, names=SAMPLE_NAMES) -> None:
    """Create a sample-prompts dir populated with the given file names."""
    samples_dir.mkdir(parents=True, exist_ok=True)
    for sample_name in names:
        _write_template(samples_dir / sample_name)


def _yaml_basenames(directory: Path) -> set[str]:
    """Return the basenames of all .yaml files in a directory."""
    return {p.name for p in directory.glob("*.yaml")}


def _manifest_lines(templates_dir: Path) -> set[str]:
    """Return the non-empty stripped lines of the seeding manifest."""
    manifest = templates_dir / MANIFEST_NAME
    assert manifest.exists(), "manifest was not written"
    return {
        line.strip()
        for line in manifest.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def test_fresh_install_copies_all_samples(tmp_path):
    """Empty templates dir + no manifest -> every sample is copied."""
    templates_dir = tmp_path / "templates"
    samples_dir = tmp_path / "samples"
    _make_samples(samples_dir)
    templates_dir.mkdir()

    PromptManager(templates_dir, samples_dir)

    assert _yaml_basenames(templates_dir) == set(SAMPLE_NAMES)
    assert _manifest_lines(templates_dir) == set(SAMPLE_NAMES)


def test_existing_install_without_manifest_copies_nothing(tmp_path):
    """Upgrade case: .yaml files exist but no manifest -> seed nothing.

    All shipped sample basenames are recorded in the manifest so a
    user-deleted template is never resurrected.
    """
    templates_dir = tmp_path / "templates"
    samples_dir = tmp_path / "samples"
    _make_samples(samples_dir)
    templates_dir.mkdir()
    _write_template(templates_dir / "my_custom.yaml")

    PromptManager(templates_dir, samples_dir)

    assert _yaml_basenames(templates_dir) == {"my_custom.yaml"}
    assert _manifest_lines(templates_dir) == set(SAMPLE_NAMES)


def test_new_sample_added_later_is_copied(tmp_path):
    """Manifest present: only the newly shipped sample is copied."""
    templates_dir = tmp_path / "templates"
    samples_dir = tmp_path / "samples"
    _make_samples(samples_dir, names=("alpha.yaml", "beta.yaml"))
    templates_dir.mkdir()

    PromptManager(templates_dir, samples_dir)

    # A new sample ships after the first run.
    _write_template(samples_dir / "gamma.yaml")

    PromptManager(templates_dir, samples_dir)

    assert _yaml_basenames(templates_dir) == set(SAMPLE_NAMES)
    assert _manifest_lines(templates_dir) == set(SAMPLE_NAMES)


def test_user_deleted_sample_is_not_resurrected(tmp_path):
    """A sample deleted by the user but listed in the manifest stays gone."""
    templates_dir = tmp_path / "templates"
    samples_dir = tmp_path / "samples"
    _make_samples(samples_dir)
    templates_dir.mkdir()

    PromptManager(templates_dir, samples_dir)
    (templates_dir / "beta.yaml").unlink()

    PromptManager(templates_dir, samples_dir)

    assert _yaml_basenames(templates_dir) == {"alpha.yaml", "gamma.yaml"}
    assert "beta.yaml" in _manifest_lines(templates_dir)
