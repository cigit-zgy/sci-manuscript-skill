"""Real release gates for compilation, provenance rendering, and lifecycle ancestry."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, doctor, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.workspace import (
    ensure_submission_workspace,
    load_project,
    source_digest,
)

pytestmark = pytest.mark.integration

REQUIRED_TOOLS = ("tectonic", "latexdiff", "pdftotext", "pdftoppm")


def _require_toolchain() -> None:
    missing = [name for name in REQUIRED_TOOLS if shutil.which(name) is None]
    if missing:
        pytest.skip("release toolchain is missing: " + ", ".join(missing))


def _author_library(path: Path) -> Path:
    path.write_text(
        """affiliations:
  institute:
    name_en: Anonymous Research Institute
    address: Example City
authors:
  author_one:
    name_en: Anonymous One
    name_zh: 匿名甲
    email: one@example.invalid
    affiliations: [institute]
  author_two:
    name_en: Anonymous Two
    name_zh: 匿名乙
    email: two@example.invalid
    affiliations: [institute]
""",
        encoding="utf-8",
    )
    return path


def _review_file(path: Path, round_number: int) -> Path:
    if round_number == 1:
        text = """# Editor

## E-1 | response_only

Please clarify the scope.

# Reviewer #1

## 1-1 | manuscript_revised

Please revise the example sentence.

# Reviewer #2

## 2-1 | manuscript_revised

Please make the same sentence more precise.
"""
    else:
        text = """# Reviewer #1

## 1-1 | manuscript_revised

Please refine the explicitly approved example once more.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _complete_responses(source: Path, review_ids: tuple[str, ...]) -> None:
    text = source.read_text(encoding="utf-8")
    for review_id in review_ids:
        text = text.replace(
            f"\\ResponsePending{{{review_id}}}",
            f"Anonymous response for {review_id}.",
        )
    source.write_text(text, encoding="utf-8")


def _complete_cover(manuscript: Path, round_number: int) -> Path:
    config = load_project(manuscript, round_number)
    source = ensure_submission_workspace(config, round_number) / "cover_letter.tex"
    text = re.sub(
        r"\\guidance\{.*?\}",
        "Approved anonymous cover-letter statement.",
        source.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert "\\guidance{" not in text
    source.write_text(text, encoding="utf-8")
    return source


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")


def _pdf_text(path: Path) -> str:
    result = subprocess.run(
        [shutil.which("pdftotext") or "pdftotext", str(path), "-"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    assert result.stdout.strip(), path
    return result.stdout


def _marked_words(text: str) -> str:
    """Normalize wave-underline extraction artifacts without hiding content loss."""
    return " ".join(re.sub(r":+", "", text).split())


def _ppm_pixels(path: Path) -> bytes:
    content = path.read_bytes()
    magic, dimensions, maximum, pixels = content.split(b"\n", 3)
    assert magic == b"P6"
    width, height = (int(value) for value in dimensions.split())
    assert maximum == b"255"
    assert len(pixels) == width * height * 3
    return pixels


def _count_color(pixels: bytes, target: tuple[int, int, int]) -> int:
    tolerance = 35
    return sum(
        1
        for index in range(0, len(pixels), 3)
        if all(
            abs(pixels[index + channel] - target[channel]) <= tolerance
            for channel in range(3)
        )
    )


def _assert_provenance_colors(pdf: Path, render_dir: Path) -> None:
    render_dir.mkdir()
    prefix = render_dir / "marked"
    subprocess.run(
        [
            shutil.which("pdftoppm") or "pdftoppm",
            "-r",
            "144",
            str(pdf),
            str(prefix),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    pixels = b"".join(
        _ppm_pixels(path) for path in sorted(render_dir.glob("marked-*.ppm"))
    )
    assert _count_color(pixels, (0, 92, 153)) > 20, "blue review markup missing"
    assert _count_color(pixels, (0, 135, 90)) > 20, "green user markup missing"
    assert _count_color(pixels, (220, 45, 45)) > 20, "red deletion markup missing"


def _assert_artifacts(result: LifecycleResult, version: Path) -> None:
    labels = {artifact.label for artifact in result.artifacts}
    assert labels == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
        "Cover letter",
        "Highlights",
        "Graphical abstract",
        "Submission checklist",
        "Submission package",
    }
    package = version / "submission" / "package"
    assert {path.name for path in package.iterdir()} == {
        "checklist.md",
        "cover_letter.pdf",
        "graphical_abstract.pdf",
        "highlights.pdf",
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
    }


def test_target_aware_chinese_doctor_runs_real_probe() -> None:
    _require_toolchain()
    result = doctor(language="zh", engine="tectonic")
    cjk = next(
        check for check in result.checks if check.name == "CJK compilation probe"
    )
    assert result.ready
    assert cjk.available
    assert "preserved Chinese glyphs" in cjk.detail


def test_release_lifecycle_and_marked_pdf_quality(tmp_path: Path) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Release Project 中文"
    initialize_manuscript(
        project_dir,
        title="Anonymous Release Validation",
        journal="Example Journal",
        publisher="acs",
        language="en",
        article_type="Research Article",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        other_authors=("author_two",),
        authors_path=_author_library(tmp_path / "authors.yaml"),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)

    project.start_revision(
        reviews=_review_file(tmp_path / "reviews_r01.md", 1), confirmed=True
    )
    r01 = manuscript / "revision_01"
    introduction = r01 / "sections" / "01_introduction.tex"
    _replace_once(
        introduction,
        "Replace this placeholder and its example citation~\\cite{replace_me} with the\n"
        "introduction.",
        "\\review{1-1,2-1}{Reviewed wording.}\n\n"
        "\\user{User-approved addition.}\n\n"
        "An example citation~\\cite{replace_me} remains.",
    )
    _complete_responses(r01 / "response" / "response_letter.tex", ("E-1", "1-1", "2-1"))
    cover_source = _complete_cover(manuscript, 1)
    before = source_digest(r01, scientific_only=True)
    r01_result = project.build_all(engine="tectonic", keep_temp=True)
    assert source_digest(r01, scientific_only=True) == before
    _assert_artifacts(r01_result, r01)
    marked = r01 / "output" / "manuscript_marked.pdf"
    response = r01 / "output" / "response_letter.pdf"
    marked_text = _pdf_text(marked)
    response_text = _pdf_text(response)
    cover_text = _pdf_text(r01 / "submission" / "package" / "cover_letter.pdf")
    marked_words = _marked_words(marked_text)
    assert "Reviewed wording" in marked_words
    assert "Replace this placeholder" in marked_words
    assert "Lines" in response_text or "Line" in response_text
    assert "E-1" in response_text
    assert "Location unavailable" not in response_text
    assert "Anonymous Release Validation" in cover_text
    assert "Anonymous One" in cover_text
    assert "guidance" not in cover_text.lower()
    assert "Approved anonymous cover-letter statement" in cover_source.read_text()
    _assert_provenance_colors(marked, tmp_path / "rendered_marked")
    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    logs = list(retained_runs[0].rglob("*.compiler.log"))
    assert logs
    diagnostics = "\n".join(path.read_text(errors="replace") for path in logs)
    assert "Overfull \\hbox" not in diagnostics
    assert "Overfull \\vbox" not in diagnostics
    shutil.rmtree(manuscript / "tmp")

    project.start_revision(
        reviews=_review_file(tmp_path / "reviews_r02.md", 2), confirmed=True
    )
    r02 = manuscript / "revision_02"
    introduction = r02 / "sections" / "01_introduction.tex"
    _replace_once(
        introduction,
        "Reviewed wording.",
        "\\review{1-1}{Refined wording.}",
    )
    _complete_responses(r02 / "response" / "response_letter.tex", ("1-1",))
    _complete_cover(manuscript, 2)
    before = source_digest(r02, scientific_only=True)
    r02_result = project.build_all(engine="tectonic")
    assert source_digest(r02, scientific_only=True) == before
    _assert_artifacts(r02_result, r02)
    r02_marked_text = _pdf_text(r02 / "output" / "manuscript_marked.pdf")
    r02_marked_words = _marked_words(r02_marked_text)
    assert "Reviewed wording" in r02_marked_words
    assert "Refined wording" in r02_marked_words
    assert "Replace this placeholder and its example citation" not in r02_marked_words
    assert not (manuscript / "tmp").exists()


def test_chinese_cover_and_response_compile_with_runtime_metadata(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / "中文 Correspondence Project"
    initialize_manuscript(
        project_dir,
        title="匿名中文通讯模板验证",
        journal="示例中文期刊",
        publisher="chinese",
        language="zh",
        article_type="研究论文",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        authors_path=_author_library(tmp_path / "authors_zh.yaml"),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(
        reviews=_review_file(tmp_path / "reviews_zh.md", 1), confirmed=True
    )
    revision = manuscript / "revision_01"
    introduction = revision / "sections" / "01_introduction.tex"
    _replace_once(
        introduction,
        "Replace this placeholder and its example citation~\\cite{replace_me} with the\n"
        "introduction.",
        "\\review{1-1,2-1}{已按用户确认修改示例文本。}",
    )
    response_source = revision / "response" / "response_letter.tex"
    _complete_responses(response_source, ("E-1", "1-1", "2-1"))
    _complete_cover(manuscript, 1)
    result = project.build_all(engine="tectonic", keep_temp=True)
    _assert_artifacts(result, revision)
    cover_text = "".join(
        _pdf_text(revision / "submission" / "package" / "cover_letter.pdf").split()
    )
    response_text = "".join(
        _pdf_text(revision / "output" / "response_letter.pdf").split()
    )
    assert "匿名中文通讯模板验证" in cover_text
    assert "匿名甲" in cover_text
    assert "意见1-1" in response_text
    assert "第" in response_text and "行" in response_text
    response_source_text = response_source.read_text(encoding="utf-8")
    assert "\\ReviewLocation{E-1}" not in response_source_text
    logs = list((manuscript / "tmp").rglob("*.compiler.log"))
    diagnostics = "\n".join(path.read_text(errors="replace") for path in logs)
    assert "Overfull \\hbox" not in diagnostics
    assert "Overfull \\vbox" not in diagnostics
    shutil.rmtree(manuscript / "tmp")
