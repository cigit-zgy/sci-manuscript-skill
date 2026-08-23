"""Real release gates for compilation, provenance rendering, and lifecycle ancestry."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, doctor, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.diff import REVIEW_REGISTRY_HEADER, REVISION_RUNTIME
from sci_manuscript.workspace import (
    ensure_submission_workspace,
    load_project,
    source_digest,
)

pytestmark = pytest.mark.integration

REQUIRED_TOOLS = ("tectonic", "latexdiff", "pdftotext", "pdftoppm", "pdfinfo")


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
    source = ensure_submission_workspace(config, round_number) / "cover_letter_body.tex"
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


def _pdf_urls(path: Path) -> str:
    result = subprocess.run(
        [shutil.which("pdfinfo") or "pdfinfo", "-url", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
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
    assert _count_color(pixels, (0, 92, 153)) > 20, "blue automatic addition missing"
    assert _count_color(pixels, (0, 135, 90)) > 20, "green reviewer markup missing"
    assert _count_color(pixels, (220, 45, 45)) > 20, "red deletion markup missing"


def _assert_artifacts(result: LifecycleResult, version: Path) -> None:
    labels = {artifact.label for artifact in result.artifacts}
    assert labels == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
        "Revision layout QA",
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


def test_tectonic_materializes_empty_review_registry(tmp_path: Path) -> None:
    _require_toolchain()
    source = tmp_path / "empty_registry.tex"
    build = tmp_path / "build"
    build.mkdir()
    source.write_text(
        "\\documentclass{article}\n"
        f"{REVISION_RUNTIME}\n"
        "\\begin{document}\n"
        "No reviewer provenance in this document.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            shutil.which("tectonic") or "tectonic",
            "-X",
            "compile",
            f"--outdir={build}",
            "--keep-intermediates",
            str(source),
        ],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    registry = build / "empty_registry.reviewloc"
    assert registry.read_text(encoding="utf-8").splitlines() == [REVIEW_REGISTRY_HEADER]


def test_fresh_chinese_initial_workflow_compiles(tmp_path: Path) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Fresh Chinese Project"
    initialize_manuscript(
        project_dir,
        title="中文模板测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_two",),
        authors_path=_author_library(tmp_path / "fresh_authors.yaml"),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    assert {path.name for path in (initial / "sections").iterdir()} == {
        "00_frontmatter.tex",
        "01_manuscript.tex",
    }
    body = initial / "sections" / "01_manuscript.tex"
    _replace_once(
        body,
        "Replace this placeholder with the manuscript body.",
        "DOI \\nolinkurl{10.1000/example-doi}.\n\n"
        "URL \\nolinkurl{https://example.org/resource}.\n\n"
        "Plain \\nolinkurl{ordinary-token}.\n\n"
        "Citation~\\cite{replace_me}.",
    )
    result = ManuscriptProject(manuscript).build(engine="tectonic", keep_temp=True)
    pdf = result.artifacts[0].path
    text = _pdf_text(pdf)
    urls = _pdf_urls(pdf)
    assert "ordinary-token" in text
    assert "https://doi.org/10.1000/example-doi" in urls
    assert "https://example.org/resource" in urls
    assert "ordinary-token" not in urls
    logs = list((manuscript / "tmp").rglob("*.compiler.log"))
    diagnostics = "\n".join(path.read_text(errors="replace") for path in logs)
    assert "Option clash" not in diagnostics
    assert "Overfull \\hbox" not in diagnostics
    assert "Overfull \\vbox" not in diagnostics
    shutil.rmtree(manuscript / "tmp")


@pytest.mark.parametrize(
    ("publisher", "expected_sections"),
    (
        (
            "elsevier",
            {
                "00_abstract.tex",
                "01_introduction.tex",
                "02_methods.tex",
                "03_results.tex",
                "04_discussion.tex",
                "05_conclusion.tex",
            },
        ),
        (
            "nature",
            {
                "00_abstract.tex",
                "01_introduction.tex",
                "02_results.tex",
                "03_discussion.tex",
                "04_methods.tex",
            },
        ),
        (
            "acs",
            {
                "00_abstract.tex",
                "01_introduction.tex",
                "02_experimental.tex",
                "03_results_and_discussion.tex",
                "04_conclusion.tex",
            },
        ),
    ),
)
def test_non_chinese_initial_workflows_remain_unchanged(
    tmp_path: Path,
    publisher: str,
    expected_sections: set[str],
) -> None:
    _require_toolchain()
    project_dir = tmp_path / f"{publisher} initial project"
    initialize_manuscript(
        project_dir,
        title=f"{publisher.title()} Initial Workflow",
        journal="Example Journal",
        publisher=publisher,
        language="en",
        article_type="Research Article",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        authors_path=_author_library(tmp_path / f"{publisher}_authors.yaml"),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    assert {path.name for path in (initial / "sections").iterdir()} == expected_sections
    source = (initial / "manuscript.tex").read_text(encoding="utf-8")
    assert "FRONTMATTER_INPUT" not in source
    assert "00_frontmatter" not in source
    result = ManuscriptProject(manuscript).build(engine="tectonic")
    assert _pdf_text(result.artifacts[0].path).strip()


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
        "User-approved ordinary addition.\n\n"
        "An example citation~\\cite{replace_me} remains.",
    )
    _complete_responses(r01 / "response" / "responses.tex", ("E-1", "1-1", "2-1"))
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
    _complete_responses(r02 / "response" / "responses.tex", ("1-1",))
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
    introduction = revision / "sections" / "01_manuscript.tex"
    _replace_once(
        introduction,
        "Replace this placeholder with the manuscript body.",
        "\\review{1-1,2-1}{已按用户确认修改示例文本。}\n\n"
        "示例文献~\\cite{replace_me}。",
    )
    response_source = revision / "response" / "responses.tex"
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
    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    assembled_response = retained_runs[0] / "response_source" / "response_letter.tex"
    assembled_cover = retained_runs[0] / "cover_source" / "cover_letter.tex"
    assert assembled_response.is_file()
    assert assembled_cover.is_file()
    assembled_text = assembled_response.read_text(encoding="utf-8")
    assert "\\ReviewLocation{E-1}" not in assembled_text
    assert "Location unavailable" not in assembled_text
    assert "位置不可用" not in assembled_text
    assert assembled_text.count("\\reviewlocation{第 ") == 2
    assert not (revision / "response" / "response_letter.tex").exists()
    assert not (revision / "submission" / "cover_letter.tex").exists()
    assert "\\documentclass" not in response_source_text
    cover_body = revision / "submission" / "cover_letter_body.tex"
    assert "\\documentclass" not in cover_body.read_text(encoding="utf-8")
    logs = list(retained_runs[0].rglob("*.compiler.log"))
    diagnostics = "\n".join(path.read_text(errors="replace") for path in logs)
    assert "Overfull \\hbox" not in diagnostics
    assert "Overfull \\vbox" not in diagnostics
    shutil.rmtree(manuscript / "tmp")


def test_chinese_revision_submission_generates_registry_and_locations(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Chinese Revision Registry Project"
    initialize_manuscript(
        project_dir,
        title="中文修订位置测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        authors_path=_author_library(tmp_path / "registry_authors.yaml"),
        engine="tectonic",
    )
    reviews = tmp_path / "registry_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n"
        "## 1-1 | manuscript_revised\n\n"
        "Please revise the manuscript text.\n",
        encoding="utf-8",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    initial_body = manuscript / "initial_submission" / "sections" / "01_manuscript.tex"
    old_paragraph = (
        "原始中文段落包含行内公式 $A \\longrightarrow B$、引用"
        "~\\cite{replace_me}，并保留足够长的连续文字来验证自动差异标记"
        "不会改变中文断行或制造不可分割的水平盒子。"
    )
    _replace_once(
        initial_body,
        "Replace this placeholder with the manuscript body.",
        old_paragraph,
    )
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    body = revision / "sections" / "01_manuscript.tex"
    _replace_once(
        body,
        old_paragraph,
        "\\review{1-1}{修订后的中文长段落同样包含行内公式 "
        "$A \\longrightarrow C$、引用~\\cite{replace_me}，并覆盖标题、公式、"
        "引用及跨行中文在颜色标记下保持原生断行的回归场景。}\n\n"
        "作者普通新增中文包含行内公式 $x+y$，用于验证蓝色波浪线与数学隔离。",
    )
    _complete_responses(revision / "response" / "responses.tex", ("1-1",))
    _complete_cover(manuscript, 1)

    result = project.build_all(engine="tectonic", keep_temp=True)

    _assert_artifacts(result, revision)
    output = revision / "output"
    assert {path.name for path in output.glob("*.pdf")} == {
        "manuscript_clean.pdf",
        "manuscript_marked.pdf",
        "response_letter.pdf",
    }
    marked_text = "".join(_pdf_text(output / "manuscript_marked.pdf").split())
    marked_plain = marked_text.replace(":", "")
    response_text = "".join(_pdf_text(output / "response_letter.pdf").split())
    assert "修订后的中文长段落" in marked_plain
    assert "不会改变中文断行或制造不可分割的水平盒子" in marked_plain
    assert "作者普通新增中文" in marked_plain
    assert "第" in response_text and "行" in response_text
    assert "Locationunavailable" not in response_text
    assert "位置不可用" not in response_text
    layout_report = (output / "revision_layout_qa.txt").read_text(encoding="utf-8")
    assert "Marked-specific overfull boxes: 0" in layout_report
    assert "Result: PASS" in layout_report
    _assert_provenance_colors(output / "manuscript_marked.pdf", tmp_path / "colors")

    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    registry = retained_runs[0] / "marked_build" / "manuscript_marked.reviewloc"
    assert registry.read_text(encoding="utf-8").splitlines() == [
        REVIEW_REGISTRY_HEADER,
        "1-1|1",
    ]
    aux = retained_runs[0] / "marked_build" / "manuscript_marked.aux"
    aux_text = aux.read_text(encoding="utf-8")
    assert "review:1:start" in aux_text
    assert "review:1:end" in aux_text
    assert (retained_runs[0] / "response_source" / "response_letter.tex").is_file()
    assert (retained_runs[0] / "cover_source" / "cover_letter.tex").is_file()
    assert not (revision / "response" / "response_letter.tex").exists()
    assert not (revision / "submission" / "cover_letter.tex").exists()
    shutil.rmtree(manuscript / "tmp")
