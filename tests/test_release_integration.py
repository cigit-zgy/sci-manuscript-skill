"""Real release gates for compilation, provenance rendering, and lifecycle ancestry."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, doctor, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.diff import REVISION_RUNTIME
from sci_manuscript.locations import REVIEW_REGISTRY_HEADER
from sci_manuscript.submission import ensure_submission_workspace
from sci_manuscript.workspace import (
    load_project,
    source_digest,
)

pytestmark = pytest.mark.integration

REQUIRED_TOOLS = (
    "tectonic",
    "latexdiff",
    "pdftocairo",
    "pdftotext",
    "pdftoppm",
    "pdfinfo",
)
SVG_COLOR = re.compile(r'(fill|stroke)="rgb\(([\d.]+)%,\s*([\d.]+)%,\s*([\d.]+)%\)"')


def _require_toolchain() -> None:
    missing = [name for name in REQUIRED_TOOLS if shutil.which(name) is None]
    if missing:
        pytest.skip("release toolchain is missing: " + ", ".join(missing))


def _review_file(path: Path, round_number: int) -> Path:
    if round_number == 1:
        text = """# Editor

## Main comment

## Specific comments

1. Please clarify the scope.

# Reviewer #1

## Main comment

## Specific comments

1. Please revise the example sentence.

# Reviewer #2

## Main comment

## Specific comments

1. Please make the same sentence more precise.
"""
    else:
        text = """# Reviewer #1

## Main comment

## Specific comments

1. Please refine the explicitly approved example once more.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _complete_responses(source: Path, review_ids: tuple[str, ...]) -> None:
    text = source.read_text(encoding="utf-8")
    for review_id in review_ids:
        pattern = re.compile(
            rf"(\\Response\{{{re.escape(review_id)}\}}\{{)\s*(\}})",
        )
        text, count = pattern.subn(
            rf"\g<1>Anonymous response for {review_id}.\g<2>", text
        )
        assert count == 1
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
    """Normalize whitespace without masking line-decoration glyph leakage."""
    return " ".join(text.split())


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


def _near_color(
    actual: tuple[float, float, float], target: tuple[int, int, int]
) -> bool:
    converted = tuple(channel * 2.55 for channel in actual)
    return all(
        abs(left - right) <= 3 for left, right in zip(converted, target, strict=True)
    )


def _assert_vector_semantics(pdf: Path, render_dir: Path) -> None:
    info = subprocess.run(
        [shutil.which("pdfinfo") or "pdfinfo", str(pdf)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout
    pages_match = re.search(r"(?m)^Pages:\s+(\d+)$", info)
    assert pages_match is not None
    colors: list[tuple[str, tuple[float, float, float]]] = []
    for page in range(1, int(pages_match.group(1)) + 1):
        svg = render_dir / f"marked-{page}.svg"
        subprocess.run(
            [
                shutil.which("pdftocairo") or "pdftocairo",
                "-f",
                str(page),
                "-l",
                str(page),
                "-svg",
                str(pdf),
                str(svg),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        for match in SVG_COLOR.finditer(svg.read_text(encoding="utf-8")):
            color = (
                float(match.group(2)),
                float(match.group(3)),
                float(match.group(4)),
            )
            colors.append((match.group(1), color))
    strokes = [color for attribute, color in colors if attribute == "stroke"]
    fills = [color for attribute, color in colors if attribute == "fill"]
    assert any(_near_color(color, (220, 45, 45)) for color in fills)
    assert any(_near_color(color, (0, 92, 153)) for color in fills)
    assert any(_near_color(color, (160, 160, 160)) for color in strokes)
    assert not any(_near_color(color, (220, 45, 45)) for color in strokes)
    assert not any(_near_color(color, (0, 92, 153)) for color in strokes)


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
    assert _count_color(pixels, (220, 45, 45)) > 20, "red reviewer markup missing"
    assert _count_color(pixels, (160, 160, 160)) > 20, "gray deletion markup missing"
    _assert_vector_semantics(pdf, render_dir)


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
        "Submission files",
    }
    submission = version / "submission"
    assert not (submission / "package").exists()
    assert {
        path.name
        for path in submission.iterdir()
        if path.is_file() and path.suffix == ".pdf"
    } == {
        "cover_letter.pdf",
        "highlights.pdf",
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
    }
    assert {path.name for path in submission.iterdir()} == {
        "checklist.md",
        "cover_letter.tex",
        "cover_letter.pdf",
        "graphical_abstract",
        "highlights.tex",
        "highlights.pdf",
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
    }
    assert (submission / "graphical_abstract" / "graphical_abstract.pdf").is_file()


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
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    assert {path.name for path in (initial / "sections").iterdir()} == {
        "00_frontmatter.tex",
        "01_introduction.tex",
    }
    body = initial / "sections" / "01_introduction.tex"
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
                "00_frontmatter.tex",
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
                "00_frontmatter.tex",
                "01_introduction.tex",
                "02_results.tex",
                "03_discussion.tex",
                "04_methods.tex",
            },
        ),
        (
            "acs",
            {
                "00_frontmatter.tex",
                "01_introduction.tex",
                "02_experimental.tex",
                "03_results_and_discussion.tex",
                "04_conclusion.tex",
            },
        ),
    ),
)
def test_non_chinese_initial_workflows_own_scientific_frontmatter(
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
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    assert {path.name for path in (initial / "sections").iterdir()} == expected_sections
    source = (initial / "manuscript.tex").read_text(encoding="utf-8")
    assert "FRONTMATTER_INPUT" not in source
    assert "ABSTRACT_INPUT" not in source
    assert r"\input{sections/00_frontmatter}" in source
    frontmatter = initial / "sections" / "00_frontmatter.tex"
    text = frontmatter.read_text(encoding="utf-8")
    text = text.replace("% Manuscript abstract", "Canonical abstract ownership.")
    text = text.replace(
        "% Comma-separated manuscript keywords", "canonical, frontmatter"
    )
    frontmatter.write_text(text, encoding="utf-8")
    result = ManuscriptProject(manuscript).build(engine="tectonic")
    pdf_text = _pdf_text(result.artifacts[0].path)
    assert f"{publisher.title()} Initial Workflow" in pdf_text
    assert "Canonical abstract ownership" in pdf_text
    if publisher == "acs":
        assert r"\keywords{\ManuscriptKeywordsText}" in source
    else:
        assert "canonical" in pdf_text and "frontmatter" in pdf_text


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
    r01_result = project.prepare_submission(engine="tectonic", keep_temp=True)
    assert source_digest(r01, scientific_only=True) == before
    _assert_artifacts(r01_result, r01)
    marked = r01 / "output" / "manuscript_marked.pdf"
    response = r01 / "output" / "response_letter.pdf"
    marked_text = _pdf_text(marked)
    response_text = _pdf_text(response)
    cover_text = _pdf_text(r01 / "submission" / "cover_letter.pdf")
    marked_words = _marked_words(marked_text)
    assert "Reviewed wording" in marked_words
    assert "Replace this placeholder" in marked_words
    assert "Lines" in response_text or "Line" in response_text
    assert "E-1" in response_text
    assert "Location unavailable" not in response_text
    assert "Anonymous Release Validation" in cover_text
    assert "First Author" in cover_text
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
    r02_result = project.prepare_submission(engine="tectonic", keep_temp=True)
    assert source_digest(r02, scientific_only=True) == before
    _assert_artifacts(r02_result, r02)
    r02_marked_text = _pdf_text(r02 / "output" / "manuscript_marked.pdf")
    r02_marked_words = _marked_words(r02_marked_text)
    assert "Replace this placeholder and its example citation" not in r02_marked_words
    r02_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(r02_runs) == 1
    r02_source = (r02_runs[0] / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert r"\DIFdel{v}" in r02_source
    assert r"\DIFdel{ew}" in r02_source
    assert r"\DIFaddReview{f}" in r02_source
    assert r"\DIFaddReview{n}" in r02_source
    shutil.rmtree(manuscript / "tmp")
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
        "Replace this placeholder with the manuscript body.",
        "\\review{1-1,2-1}{已按用户确认修改示例文本。}\n\n"
        "示例文献~\\cite{replace_me}。",
    )
    response_source = revision / "response" / "responses.tex"
    _complete_responses(response_source, ("E-1", "1-1", "2-1"))
    _complete_cover(manuscript, 1)
    result = project.prepare_submission(engine="tectonic", keep_temp=True)
    _assert_artifacts(result, revision)
    cover_text = "".join(
        _pdf_text(revision / "submission" / "cover_letter.pdf").split()
    )
    response_text = "".join(
        _pdf_text(revision / "output" / "response_letter.pdf").split()
    )
    assert "匿名中文通讯模板验证" in cover_text
    assert "第一作者" in cover_text
    assert "意见1-1" in response_text
    assert "第" in response_text and "行" in response_text
    assert "使用说明" not in response_text
    assert "reviewer_comments.md" not in response_text
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
    assert (revision / "submission" / "cover_letter.tex").is_file()
    assert "\\documentclass" not in response_source_text
    cover_body = revision / "submission" / "cover_letter.tex"
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
        engine="tectonic",
    )
    reviews = tmp_path / "registry_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n"
        "## Main comment\n\n"
        "## Specific comments\n\n"
        "1. Please revise the manuscript text.\n",
        encoding="utf-8",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    initial_body = (
        manuscript / "initial_submission" / "sections" / "01_introduction.tex"
    )
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
    body = revision / "sections" / "01_introduction.tex"
    _replace_once(
        body,
        old_paragraph,
        "\\review{1-1}{修订后的中文长段落同样包含行内公式 "
        "$A \\longrightarrow C$、引用~\\cite{replace_me}，并覆盖标题、公式、"
        "引用及跨行中文在颜色标记下保持原生断行的回归场景。}\n\n"
        "作者普通新增中文包含行内公式 $x+y$，用于验证纯蓝正文与数学隔离。",
    )
    _complete_responses(revision / "response" / "responses.tex", ("1-1",))
    _complete_cover(manuscript, 1)

    result = project.prepare_submission(engine="tectonic", keep_temp=True)

    _assert_artifacts(result, revision)
    output = revision / "output"
    assert {path.name for path in output.glob("*.pdf")} == {
        "manuscript_clean.pdf",
        "manuscript_marked.pdf",
        "response_letter.pdf",
    }
    marked_text = "".join(_pdf_text(output / "manuscript_marked.pdf").split())
    response_text = "".join(_pdf_text(output / "response_letter.pdf").split())
    assert "修订后的中文长段落" in marked_text
    assert "作者普通新增中文" in marked_text
    assert "第" in response_text and "行" in response_text
    assert "Locationunavailable" not in response_text
    assert "位置不可用" not in response_text
    assert not list(output.glob("*")) or all(
        path.suffix == ".pdf" for path in output.iterdir()
    )
    _assert_provenance_colors(output / "manuscript_marked.pdf", tmp_path / "colors")

    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    layout_report = (retained_runs[0] / "revision_layout_qa.txt").read_text(
        encoding="utf-8"
    )
    assert "Marked-specific overfull boxes: 0" in layout_report
    assert "Result: PASS" in layout_report
    marked_source = (
        retained_runs[0] / "marked_source" / "manuscript_marked.tex"
    ).read_text(encoding="utf-8")
    assert r"\DIFdel" in marked_source
    assert r"\DIFaddReview" in marked_source
    ordered_fragments = ("修订后的", "中文", "长", "段落")
    cursor = 0
    for fragment in ordered_fragments:
        cursor = marked_source.index(fragment, cursor) + len(fragment)
    assert r"\DIFaddReview{修订后的}" in marked_source
    assert r"\DIFaddReview{长}" in marked_source
    assert r"\DIFaddReview{中文}" not in marked_source
    assert r"\DIFaddReview{段落}" not in marked_source
    assert "作者普通新增中文" in marked_source
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
    cover_source = revision / "submission" / "cover_letter.tex"
    assert cover_source.is_file()
    assert "\\documentclass" not in cover_source.read_text(encoding="utf-8")
    shutil.rmtree(manuscript / "tmp")


def test_math_revision_semantics_are_fine_grained_and_rendered(tmp_path: Path) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Math Revision Project"
    initialize_manuscript(
        project_dir,
        title="公式修订语义测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission" / "sections" / "01_introduction.tex"
    old = r"""Deleted inline $\mathcal{O}_{\mathrm{P}}$ with a subscript.
Reviewer inline $a+b$ and parenthesized \(\mathcal{O}_{\mathrm{M},old}\), plus unchanged math $u=v$.
\begin{equation}
x+y=z\label{eq:partial}
\end{equation}
\begin{equation}
p=q\label{eq:deleted}
\end{equation}
Stable anchor.
"""
    _replace_once(initial, "Replace this placeholder with the manuscript body.", old)
    reviews = tmp_path / "math_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Revise the formulas.\n",
        encoding="utf-8",
    )
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    current = revision / "sections" / "01_introduction.tex"
    new = r"""\review{1-1}{Reviewer inline $a+c$ and parenthesized \(\mathcal{O}_{\mathrm{M},new}\), plus unchanged math $u=v$.
\begin{equation}
x+y+w=z\label{eq:partial}
\end{equation}}
Stable anchor.
Author inline $\mathcal{O}_{\mathrm{M}}^{2}$ and $m+n$.
\begin{equation}
r=s\label{eq:author}
\end{equation}
"""
    _replace_once(current, old, new)

    project.build(engine="tectonic", keep_temp=True)
    output = revision / "output"
    marked_pdf = output / "manuscript_marked.pdf"
    marked_text = _pdf_text(marked_pdf)
    assert "Reviewer inline" in marked_text
    assert "Author inline" in marked_text
    assert "(1)" in marked_text and "(2)" in marked_text
    _assert_provenance_colors(marked_pdf, tmp_path / "math_colors")

    run = next((manuscript / "tmp").glob("run_*"))
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert r"$\DIFdelMath{a+b}$" in marked_source
    assert r"$\DIFaddReviewMath{a+c}$" in marked_source
    assert r"\DIFaddReview{+w}" in marked_source
    assert r"\DIFdel{p=q}" in marked_source
    assert r"$\DIFaddMath{m+n}$" in marked_source
    assert r"\DIFadd{r=s}" in marked_source
    assert r"$\DIFdelMath{\mathcal{O}_{\mathrm{P}}}$" in marked_source
    assert r"$\DIFaddMath{\mathcal{O}_{\mathrm{M}}^{2}}$" in marked_source
    assert r"\(\DIFdelMath{" in marked_source
    assert r"\(\DIFaddReviewMath{" in marked_source
    for math_macro in (r"\DIFdelMath", r"\DIFaddMath", r"\DIFaddReviewMath"):
        assert f"{math_macro}{{$" not in marked_source
        assert f"{math_macro}{{\\(" not in marked_source
    unchanged = marked_source[
        marked_source.index("u=v") - 30 : marked_source.index("u=v") + 30
    ]
    assert r"\DIFaddReview{u=v}" not in unchanged
    assert marked_source.count(r"\label{eq:partial}") == 1
    assert marked_source.count(r"\label{eq:author}") == 1
    shutil.rmtree(manuscript / "tmp")


def test_chinese_funding_metadata_participates_in_revision_diff(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Funding Revision Project"
    initialize_manuscript(
        project_dir,
        title="基金修订差异测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    _replace_once(
        initial / "meta.yaml",
        "  funding: []",
        "  funding:\n    - 国家自然科学基金项目（52500063）",
    )
    project = ManuscriptProject(manuscript)
    project.start_revision(confirmed=True)
    revision = manuscript / "revision_01"
    _replace_once(
        revision / "meta.yaml",
        "    - 国家自然科学基金项目（52500063）",
        "    - 国家自然科学基金项目（52500063, 52131003, 52327813）",
    )

    project.build(engine="tectonic", keep_temp=True)

    output = revision / "output"
    assert "52131003" in _pdf_text(output / "manuscript_clean.pdf")
    assert "52327813" in _pdf_text(output / "manuscript_marked.pdf")
    run = next((manuscript / "tmp").glob("run_*"))
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert "52131003" in marked_source
    assert "52327813" in marked_source
    assert re.search(r"\\DIFadd(?:FL)?\{[^{}]*52131003", marked_source)
    assert re.search(r"\\DIFadd(?:FL)?\{[^{}]*52327813", marked_source)
    assert not re.search(r"\\DIFaddReview(?:FL)?\{[^{}]*52[13]", marked_source)
    assert "marked_source" not in _pdf_text(output / "manuscript_marked.pdf")
    assert "publisher_metadata" not in _pdf_text(output / "manuscript_marked.pdf")
    old_runtime = run / "marked_source" / "old_runtime" / "publisher_metadata.tex"
    new_runtime = run / "marked_source" / "new_runtime" / "publisher_metadata.tex"
    assert "52500063" in old_runtime.read_text(encoding="utf-8")
    assert "52131003" not in old_runtime.read_text(encoding="utf-8")
    assert "52131003" in new_runtime.read_text(encoding="utf-8")
    assert "52327813" in new_runtime.read_text(encoding="utf-8")


def test_frontmatter_abstract_addition_is_marked(tmp_path: Path) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Frontmatter Abstract Revision Project"
    initialize_manuscript(
        project_dir,
        title="摘要修订覆盖测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(confirmed=True)
    revision = manuscript / "revision_01"
    frontmatter = revision / "sections" / "00_frontmatter.tex"
    _replace_once(
        frontmatter,
        "\\end{abstract}",
        "FrontmatterAbstractSentinel\n\\end{abstract}",
    )

    project.build(engine="tectonic", keep_temp=True)

    output = revision / "output"
    assert "FrontmatterAbstractSentinel" in _pdf_text(output / "manuscript_clean.pdf")
    assert "FrontmatterAbstractSentinel" in _pdf_text(output / "manuscript_marked.pdf")
    run = next((manuscript / "tmp").glob("run_*"))
    old_source = (run / "marked_source" / "old.tex").read_text(encoding="utf-8")
    new_source = (run / "marked_source" / "new.tex").read_text(encoding="utf-8")
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert "FrontmatterAbstractSentinel" not in old_source
    assert "FrontmatterAbstractSentinel" in new_source
    assert re.search(
        r"\\DIFadd(?:FL)?\{FrontmatterAbstractSentinel\s*\}", marked_source
    )


@pytest.mark.parametrize(
    ("placeholder", "addition"),
    (
        ("% Chinese title", "中文标题新增片段"),
        ("% English title", "EnglishTitleAddition"),
        ("% English abstract", "EnglishAbstractAddition"),
        (r"\keywords{\n\n}", "\\keywords{中文关键词新增}"),
        (r"\enkeywords{\n\n}", "\\enkeywords{EnglishKeywordAddition}"),
    ),
)
def test_frontmatter_visible_field_addition_is_marked(
    tmp_path: Path,
    placeholder: str,
    addition: str,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / f"Frontmatter Field {addition}"
    initialize_manuscript(
        project_dir,
        title="前置信息字段覆盖测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(confirmed=True)
    revision = manuscript / "revision_01"
    frontmatter = revision / "sections" / "00_frontmatter.tex"
    current = frontmatter.read_text(encoding="utf-8")
    old = placeholder.replace(r"\n", "\n")
    assert current.count(old) == 1
    frontmatter.write_text(current.replace(old, addition), encoding="utf-8")

    project.build(engine="tectonic", keep_temp=True)

    run = next((manuscript / "tmp").glob("run_*"))
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    visible = addition
    if addition.startswith((r"\keywords", r"\enkeywords")):
        visible = addition.split("{", 1)[1][:-1]
    assert visible in _pdf_text(revision / "output" / "manuscript_marked.pdf")
    assert re.search(rf"\\DIFadd(?:FL)?\{{[^}}]*{re.escape(visible)}", marked_source)


def test_response_body_reaches_response_letter_during_build(tmp_path: Path) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Build Response Revision Project"
    initialize_manuscript(
        project_dir,
        title="回复构建链路测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    reviews = tmp_path / "build_response_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Please revise the manuscript.\n"
        "2. Please explain without a manuscript change.\n",
        encoding="utf-8",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    body = revision / "sections" / "01_introduction.tex"
    _replace_once(
        body,
        "Replace this placeholder with the manuscript body.",
        "\\review{1-1}{BuildReviewSentinel}",
    )
    response_source = revision / "response" / "responses.tex"
    response_source.write_text(
        "\\Response{1-1}{ResponseSentinelOne}\n\\Response{1-2}{ResponseSentinelTwo}\n",
        encoding="utf-8",
    )

    result = project.build(engine="tectonic", keep_temp=True)

    response_pdf = revision / "output" / "response_letter.pdf"
    assert response_pdf.is_file()
    response_text = _pdf_text(response_pdf)
    assert "ResponseSentinelOne" in response_text
    assert "ResponseSentinelTwo" in response_text
    assert "第" in response_text and "行" in response_text
    assert "Location unavailable" not in response_text
    assert "位置不可用" not in response_text
    assert any(artifact.path == response_pdf for artifact in result.artifacts)
    run = next((manuscript / "tmp").glob("run_*"))
    assembled = (run / "response_source" / "response_letter.tex").read_text(
        encoding="utf-8"
    )
    assert assembled.count(r"\reviewlocation{") == 1
    response_source.write_text(
        "\\Response{1-1}{ResponseSentinelUpdated}\n"
        "\\Response{1-2}{ResponseSentinelTwo}\n",
        encoding="utf-8",
    )

    project.build(engine="tectonic")

    rebuilt_text = _pdf_text(response_pdf)
    assert "ResponseSentinelUpdated" in rebuilt_text
    assert "ResponseSentinelOne" not in rebuilt_text


def test_frontmatter_reviewer_addition_is_red_and_location_is_generated(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / "Frontmatter Provenance Revision Project"
    initialize_manuscript(
        project_dir,
        title="摘要审稿来源测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission" / "sections" / "00_frontmatter.tex"
    _replace_once(
        initial,
        "% Chinese abstract",
        "摘要稳定文本。待删除摘要内容。行内公式 $\\mathrm{ASM2d}_{old}$。",
    )
    reviews = tmp_path / "frontmatter_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Please revise the abstract.\n",
        encoding="utf-8",
    )
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    frontmatter = revision / "sections" / "00_frontmatter.tex"
    _replace_once(
        frontmatter,
        "摘要稳定文本。待删除摘要内容。行内公式 $\\mathrm{ASM2d}_{old}$。",
        "摘要稳定文本。作者普通新增。"
        "\\review{1-1}{审稿关联新增，行内公式 $\\mathrm{ASM2d}_{new}$。}",
    )
    (revision / "response" / "responses.tex").write_text(
        "\\Response{1-1}{FrontmatterResponseSentinel}\n",
        encoding="utf-8",
    )

    project.build(engine="tectonic", keep_temp=True)

    output = revision / "output"
    marked_pdf = output / "manuscript_marked.pdf"
    response_pdf = output / "response_letter.pdf"
    assert "作者普通新增" in _pdf_text(marked_pdf)
    response_text = _pdf_text(response_pdf)
    assert "FrontmatterResponseSentinel" in response_text
    assert "第" in response_text and "行" in response_text
    run = next((manuscript / "tmp").glob("run_*"))
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert r"\DIFaddReview{" in marked_source
    assert r"\DIFadd{" in marked_source
    assert r"\DIFdel{" in marked_source
    assert r"\DIFaddReviewMath{" in marked_source
    assert r"\DIFdelMath{" in marked_source
    registry = run / "marked_build" / "manuscript_marked.reviewloc"
    assert "1-1|" in registry.read_text(encoding="utf-8")
    _assert_provenance_colors(marked_pdf, tmp_path / "frontmatter_colors")
