"""Upload strategy for external destinations (NotebookLM, etc.).

Handles file-size limits and source-count limits via configurable strategies:
- individual: upload each report as-is
- combined: merge all into one file
- smart: bin-pack reports into bundles respecting limits
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from streamdoc.config import settings

logger = logging.getLogger(__name__)


@dataclass
class UploadBundle:
    """A group of report files that will be uploaded together."""

    paths: list[Path] = field(default_factory=list)
    total_size: int = 0

    def add(self, path: Path, size: int) -> None:
        self.paths.append(path)
        self.total_size += size


def _collect_report_files(artifacts_dir: Path) -> list[tuple[Path, int]]:
    """Gather report files (.md, .pdf) with their sizes."""
    files: list[tuple[Path, int]] = []
    text_only = settings.notebooklm_upload_text_only

    for f in artifacts_dir.iterdir():
        if not f.is_file():
            continue
        if text_only and f.suffix.lower() != ".md":
            continue
        if f.suffix.lower() not in (".md", ".pdf"):
            continue
        files.append((f, f.stat().st_size))

    return files


def _combine_md_files(paths: list[Path], out_path: Path) -> Path:
    """Merge multiple markdown files into one with section separators."""
    lines: list[str] = []
    for p in paths:
        lines.append(f"\n\n---\n\n# Bundle section: {p.stem}\n\n")
        try:
            lines.append(p.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Could not read %s for bundling: %s", p, exc)
            lines.append(f"\n[Error reading {p.name}: {exc}]\n")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _bundle_individual(files: list[tuple[Path, int]]) -> list[UploadBundle]:
    """Each file becomes its own bundle."""
    return [UploadBundle(paths=[p], total_size=s) for p, s in files]


def _bundle_combined(files: list[tuple[Path, int]], out_dir: Path) -> list[UploadBundle]:
    """All files merged into a single combined markdown bundle."""
    md_files = [p for p, _ in files if p.suffix.lower() == ".md"]
    if not md_files:
        # Fallback to individual if no markdown files
        return _bundle_individual(files)

    combined_path = out_dir / "combined_upload.md"
    _combine_md_files(md_files, combined_path)
    size = combined_path.stat().st_size
    return [UploadBundle(paths=[combined_path], total_size=size)]


def _bundle_smart(files: list[tuple[Path, int]], out_dir: Path) -> list[UploadBundle]:
    """Bin-pack files into bundles using first-fit-decreasing.

    Algorithm:
    1. Sort files by size descending.
    2. Try to place each file into an existing bundle that has room.
    3. If no bundle has room, create a new bundle.
    4. If we exceed max_bundle_files, merge the smallest bundles together.
    5. Convert each bundle's files into a combined markdown file.
    """
    max_size = settings.notebooklm_max_bundle_size_mb * 1024 * 1024
    max_files = settings.notebooklm_max_bundle_files

    # If everything fits individually, return as-is
    if len(files) <= max_files and all(s <= max_size for _, s in files):
        return _bundle_individual(files)

    # First-fit-decreasing bin packing
    files_sorted = sorted(files, key=lambda x: -x[1])
    bundles: list[UploadBundle] = []

    for path, size in files_sorted:
        placed = False
        for bundle in bundles:
            if bundle.total_size + size <= max_size:
                bundle.add(path, size)
                placed = True
                break
        if not placed:
            bundles.append(UploadBundle(paths=[path], total_size=size))

    # If too many bundles, merge small ones
    while len(bundles) > max_files:
        # Sort by size ascending, merge two smallest
        bundles.sort(key=lambda b: b.total_size)
        if len(bundles) < 2:
            break
        a, b = bundles[0], bundles[1]
        # Only merge if combined size fits; if not, we are over-constrained
        if a.total_size + b.total_size <= max_size:
            merged = UploadBundle(
                paths=a.paths + b.paths,
                total_size=a.total_size + b.total_size,
            )
            bundles = [merged] + bundles[2:]
        else:
            # Can't merge without exceeding limit — we have to combine into
            # markdown bundles regardless (which will be smaller)
            break

    # Convert each bundle into a combined markdown file
    # (except single-file bundles that are already markdown)
    final_bundles: list[UploadBundle] = []
    for i, bundle in enumerate(bundles, start=1):
        md_files = [p for p in bundle.paths if p.suffix.lower() == ".md"]
        if len(md_files) <= 1 and len(bundle.paths) == 1:
            # Single file, keep as-is
            final_bundles.append(bundle)
        else:
            combined_path = out_dir / f"bundle_{i:02d}.md"
            _combine_md_files(md_files if md_files else bundle.paths, combined_path)
            final_bundles.append(
                UploadBundle(paths=[combined_path], total_size=combined_path.stat().st_size)
            )

    return final_bundles


def build_bundles(artifacts_dir: Path) -> list[UploadBundle]:
    """Build upload bundles from a preset's output directory.

    Args:
        artifacts_dir: Path to the preset output directory (e.g. data/Outputs/my_preset).

    Returns:
        List of UploadBundle objects ready for upload.
    """
    mode = settings.notebooklm_upload_mode
    files = _collect_report_files(artifacts_dir)

    if not files:
        logger.warning("No report files found in %s", artifacts_dir)
        return []

    if mode == "individual":
        return _bundle_individual(files)
    if mode == "combined":
        return _bundle_combined(files, artifacts_dir)
    return _bundle_smart(files, artifacts_dir)


def upload_to_notebooklm(paths: list[Path]) -> None:
    """Placeholder for NotebookLM upload.

    Args:
        paths: Files to upload.

    Raises:
        RuntimeError: If upload fails.
    """
    # Reason: actual NotebookLM integration will be built later.
    # For now this is a no-op that simulates success.
    logger.info("NotebookLM upload placeholder: would upload %s files", len(paths))
