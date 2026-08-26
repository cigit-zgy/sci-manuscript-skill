"""Real release gates for compilation, provenance rendering, and lifecycle ancestry."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import pytest

from sci_manuscript import ManuscriptProject, doctor, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.authors import resolve_author_library_path
from sci_manuscript.diff import REVISION_RUNTIME
from sci_manuscript.errors import WorkflowError
from sci_manuscript.locations import TEX_LOCATION_REGISTRY_HEADER
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
    "pdffonts",
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
    source = ensure_submission_workspace(config, round_number) / "cover_letter_body.tex"
    text = re.sub(
        r"\\guidance\{.*?\}",
        "Approved anonymous cover-letter statement.",
        source.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    assert "\\guidance{" not in text
    source.write_text(text, encoding="utf-8")
    submission = source.parent
    for pending in (
        submission / "highlights.tex",
        submission / "graphical_abstract" / "graphical_abstract.tex",
    ):
        pending.write_text(
            pending.read_text(encoding="utf-8")
            .replace("% SCI_MANUSCRIPT_PENDING: highlights\n", "")
            .replace("% SCI_MANUSCRIPT_PENDING: graphical_abstract\n", ""),
            encoding="utf-8",
        )
    return source


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")


def _custom_release_template(root: Path) -> Path:
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    (nested / "style.tex").write_text(
        "\\newcommand{\\CustomResourceMarker}{Custom resource loaded.}\n",
        encoding="utf-8",
    )
    (root / "workflow.tex").write_text(
        "\\documentclass{article}\n"
        "\\input{author_metadata}\n"
        "\\input{preamble/en}\n"
        "\\input{nested/style}\n"
        "\\title{\\ManuscriptTitle}\n"
        "\\author{\\SelectedAuthorNames}\n"
        "\\begin{document}\n\\maketitle\n"
        "\\CustomResourceMarker\n"
        "%%FRONTMATTER_INPUT%%\n%%SECTION_INPUTS%%\n"
        "\\bibliographystyle{%%BIBLIOGRAPHY_STYLE%%}\n"
        "\\bibliography{%%BIBLIOGRAPHY_PATH%%}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (root / "sections.yaml").write_text(
        "languages: [en]\n"
        "bibliography:\n  package: '% article supplies bibliography'\n"
        "  style: plain\n"
        "frontmatter:\n  file: 00_frontmatter.tex\n  source: frontmatter.tex\n"
        "sections:\n  - file: 01_body.tex\n    source: body.tex\n"
        "    title: Body\n",
        encoding="utf-8",
    )
    (root / "frontmatter.tex").write_text(
        "\\begin{abstract}\nCustom abstract.\n\\end{abstract}\n",
        encoding="utf-8",
    )
    (root / "body.tex").write_text(
        "\\section{%%SECTION_TITLE%%}\nCustom body.\n",
        encoding="utf-8",
    )
    return root


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


def _rendered_bibliography_source(marked_source: str) -> str:
    match = re.search(r"\\begin\{(?:mcite)?thebibliography\}", marked_source)
    assert match is not None
    environment = re.search(r"\\begin\{([^}]*bibliography)\}", match.group(0))
    assert environment is not None
    ending = rf"\end{{{environment.group(1)}}}"
    stop = marked_source.index(ending, match.end()) + len(ending)
    return marked_source[match.start() : stop]


def _pdf_word_x(path: Path, token: str) -> float:
    """Return the unique horizontal coordinate of one PDF word token."""
    result = subprocess.run(
        [shutil.which("pdftotext") or "pdftotext", "-bbox", str(path), "-"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    root = ElementTree.fromstring(result.stdout)
    positions = [
        float(element.attrib["xMin"])
        for element in root.iter()
        if element.tag.endswith("word") and element.text == token
    ]
    assert len(positions) == 1, (token, positions)
    return positions[0]


def _pdf_urls(path: Path) -> str:
    result = subprocess.run(
        [shutil.which("pdfinfo") or "pdfinfo", "-url", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout


def _pdf_fonts(path: Path) -> str:
    result = subprocess.run(
        [shutil.which("pdffonts") or "pdffonts", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.replace(" ", "").lower()


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
    assert any(_near_color(color, (236, 4, 126)) for color in fills)
    assert any(_near_color(color, (21, 155, 82)) for color in fills)
    assert not any(_near_color(color, (160, 160, 160)) for color in strokes)
    assert not any(_near_color(color, (236, 4, 126)) for color in strokes)
    assert not any(_near_color(color, (21, 155, 82)) for color in strokes)


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
    assert _count_color(pixels, (21, 155, 82)) > 20, (
        "ForestGreen author addition missing"
    )
    assert _count_color(pixels, (236, 4, 126)) > 20, "RubineRed reviewer markup missing"
    _assert_vector_semantics(pdf, render_dir)


def _assert_rendered_color(
    pdf: Path,
    render_dir: Path,
    target: tuple[int, int, int],
) -> None:
    """Verify rendered PDF pixels when a font lacks reliable Unicode mapping."""
    render_dir.mkdir()
    prefix = render_dir / "page"
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
        _ppm_pixels(path) for path in sorted(render_dir.glob("page-*.ppm"))
    )
    assert _count_color(pixels, target) > 20, (
        f"rendered revision color {target} is missing from {pdf}"
    )


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
        "cover_letter_body.tex",
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


def test_marked_runtime_does_not_own_the_location_registry(tmp_path: Path) -> None:
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
    assert not (build / "empty_registry.reviewloc").exists()


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
    project = ManuscriptProject(manuscript)
    project.start_revision(confirmed=True)
    revision = manuscript / "revision_01"
    if publisher == "elsevier":
        bibliography = manuscript / "references" / "references.bib"
        _replace_once(
            bibliography,
            "Replace this example bibliography entry",
            "Corrected visible bibliography entry",
        )
    introduction = revision / "sections" / "01_introduction.tex"
    _replace_once(
        introduction,
        "Replace this placeholder and its example citation~\\cite{replace_me} with the\n"
        "introduction.",
        "User-approved revision with citation~\\cite{replace_me}.",
    )
    before = source_digest(revision, scientific_only=True)
    project.build(target="clean", engine="tectonic")
    revision_result = project.build(
        target="marked",
        engine="tectonic",
        keep_temp=publisher == "elsevier",
    )
    assert source_digest(revision, scientific_only=True) == before
    assert {artifact.label for artifact in revision_result.artifacts} == {
        "Marked manuscript"
    }
    assert (revision / "output" / "manuscript_marked.pdf").is_file()
    if publisher == "elsevier":
        clean_text = _pdf_text(revision / "output" / "manuscript_clean.pdf")
        marked_text = _pdf_text(revision / "output" / "manuscript_marked.pdf")
        assert "Corrected visible bibliography entry" in clean_text
        assert "replace_me" not in marked_text
        retained_runs = list((manuscript / "tmp").glob("run_*"))
        assert len(retained_runs) == 1
        marked_source = (
            retained_runs[0] / "marked_source" / "manuscript_marked.tex"
        ).read_text(encoding="utf-8")
        bibliography_source = _rendered_bibliography_source(marked_source)
        assert "Corrected visible" in bibliography_source
        assert "Replace this example" not in bibliography_source
        assert r"\DIFdel{" not in bibliography_source
        assert r"\DIFadd{" not in bibliography_source
        shutil.rmtree(manuscript / "tmp")
    if (manuscript / "tmp").exists():
        assert not list((manuscript / "tmp").glob("run_*"))
        assert (manuscript / "tmp" / "cache" / "bibliography").is_dir()


def test_custom_publisher_initial_and_revision_workflow(tmp_path: Path) -> None:
    _require_toolchain()
    template = _custom_release_template(tmp_path / "custom-template")
    project_dir = tmp_path / "Custom Publisher Project"
    initialize_manuscript(
        project_dir,
        title="Custom Publisher Validation",
        journal="Custom Journal",
        publisher="custom",
        language="en",
        article_type="Article",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        custom_template=template,
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    copied = manuscript / "references" / "journal_template"
    assert (copied / "nested" / "style.tex").is_file()
    initial_pdf = manuscript / "initial_submission" / "output" / "manuscript.pdf"
    assert "Custom resource loaded" in _pdf_text(initial_pdf)

    reviews = tmp_path / "custom-reviews.md"
    reviews.write_text(
        "# Associate Editor\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Revise the custom body.\n",
        encoding="utf-8",
    )
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    body = revision / "sections" / "01_body.tex"
    _replace_once(body, "Custom body.", "\\review{AE-1}{Custom revised body.}")
    before = source_digest(revision, scientific_only=True)

    result = project.build(target="all", engine="tectonic")

    assert source_digest(revision, scientific_only=True) == before
    assert {artifact.label for artifact in result.artifacts} == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
    }
    marked_text = _pdf_text(revision / "output" / "manuscript_marked.pdf")
    assert "Custom body." not in marked_text
    assert "Custom revised body." in marked_text
    assert (manuscript / "state" / "revision_01" / "build_manifest.yaml").is_file()
    assert not list((manuscript / "tmp").glob("run_*"))
    assert (manuscript / "tmp" / "cache" / "bibliography").is_dir()


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
    response_source = r01 / "response" / "responses.tex"
    response_source.write_text(
        "\\Response{E-1}{Anonymous response for E-1.}\n"
        "\\Response{1-1}{Anonymous response for 1-1.}\n"
        "\\Response{2-1}{Anonymous response for 2-1.}\n",
        encoding="utf-8",
    )
    response_source_before = response_source.read_bytes()
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
    assert "Replace this placeholder and its example citation" not in marked_words
    assert "Lines" in response_text or "Line" in response_text
    assert "Anonymous Release Validation" in response_text
    assert response_source.read_bytes() == response_source_before
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
    assert r"\DIFdel" not in r02_source
    assert "Reviewed wording." not in r02_source
    assert r"\DIFaddReview{Refined}" in r02_source
    assert "Refined wording" in r02_marked_words
    shutil.rmtree(manuscript / "tmp")
    assert not (manuscript / "tmp").exists()


def test_chinese_deletion_only_review_has_no_fake_marked_location(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    project_dir = tmp_path / "中文纯删除审稿验证"
    initialize_manuscript(
        project_dir,
        title="纯删除审稿验证",
        journal="示例中文期刊",
        publisher="chinese",
        language="zh",
        article_type="研究论文",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        engine="tectonic",
    )
    reviews = tmp_path / "deletion_reviews.md"
    reviews.write_text(
        "# 审稿人 #1\n\n## 主意见\n\n## 具体意见\n\n1. 请删除不必要的句子。\n",
        encoding="utf-8",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    body = revision / "sections" / "01_manuscript.tex"
    _replace_once(
        body,
        "Replace this placeholder with the manuscript body.",
        r"\review{1-1}{}",
    )
    _complete_responses(revision / "response" / "responses.tex", ("1-1",))

    result = project.build(target="all", engine="tectonic", keep_temp=True)

    assert {artifact.label for artifact in result.artifacts} == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
    }
    run = next((manuscript / "tmp").glob("run_*"))
    response_source = (run / "response_source" / "response_letter.tex").read_text(
        encoding="utf-8"
    )
    assert r"\reviewlocation{相关内容已删除，当前稿无对应高亮文本}" in response_source
    assert "第 1 行" not in response_source
    audit = json.loads((run / "highlight_audit.json").read_text(encoding="utf-8"))
    assert audit["pure_deletion_reviews"] == ["1-1"]
    assert audit["reviewer_highlight_spans"] == 0
    assert audit["clean_marked_text_identity"] is True
    assert audit["clean_marked_numbering_identity"] is True
    assert audit["unresolved_additions"] == 0


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
    assert (revision / "submission" / "cover_letter_body.tex").is_file()
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
    assert r"\DIFdel" not in marked_source
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
    registry_lines = registry.read_text(encoding="utf-8").splitlines()
    assert registry_lines[0] == TEX_LOCATION_REGISTRY_HEADER
    assert len(registry_lines) > 2
    assert all(line.startswith("1-1|") for line in registry_lines[1:])
    assert (retained_runs[0] / "response_source" / "response_letter.tex").is_file()
    assert (retained_runs[0] / "highlight_audit.json").is_file()
    assert not (output / "diff_audit.json").exists()
    assert not (output / "highlight_audit.json").exists()
    assert (retained_runs[0] / "cover_source" / "cover_letter.tex").is_file()
    assert not (revision / "response" / "response_letter.tex").exists()
    cover_source = revision / "submission" / "cover_letter_body.tex"
    assert cover_source.is_file()
    assert "\\documentclass" not in cover_source.read_text(encoding="utf-8")
    shutil.rmtree(manuscript / "tmp")


def test_chinese_bibliography_doi_and_visible_revision_semantics(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    parent_bibliography = tmp_path / "parent-references.bib"
    parent_bibliography.write_text(
        """@article{hidden-citation-key-42,
  author = {M. Bran, A},
  title = {Augmenting Large Language Models with Chemistry Tools},
  journal = {Nature Machine Intelligence},
  year = {2024},
  volume = {6},
  pages = {525--535}
}
@article{removed-doi-entry,
  author = {Example, Deleted},
  title = {Removed DOI Entry},
  journal = {Example Journal},
  year = {2025},
  volume = {1},
  pages = {1--2},
  doi = {https://dx.doi.org/10.5555/Deleted.MixedCase}
}
""",
        encoding="utf-8",
    )
    project_dir = tmp_path / "Chinese Bibliography Revision Project"
    initialize_manuscript(
        project_dir,
        title="中文参考文献修订测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_one",),
        bibliography_path=parent_bibliography,
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    body = manuscript / "initial_submission" / "sections" / "01_manuscript.tex"
    _replace_once(
        body,
        "Replace this placeholder with the manuscript body.",
        "正文引用文献~\\cite{hidden-citation-key-42,removed-doi-entry}。",
    )
    project = ManuscriptProject(manuscript)
    reviews = tmp_path / "bibliography-reviews.md"
    reviews.write_text(
        "# Reviewer #2\n\n## Main comment\n\nPlease standardize the references.\n\n"
        "## Specific comments\n\n1. Correct the reference metadata.\n",
        encoding="utf-8",
    )
    project.start_revision(reviews=reviews, confirmed=True)
    current_body = manuscript / "revision_01" / "sections" / "01_manuscript.tex"
    _replace_once(
        current_body,
        r"\cite{hidden-citation-key-42,removed-doi-entry}",
        r"\cite{hidden-citation-key-42}",
    )
    shared = manuscript / "references" / "references.bib"
    shared.write_text(
        """@article{hidden-citation-key-42,
  author = {Bran, Andres M},
  title = {Augmenting Large Language Models with Chemistry Tools},
  journal = {Nature Machine Intelligence},
  year = {2024},
  volume = {6},
  pages = {525--535},
  doi = {https://doi.org/10.1038/s42256-024-00832-8}
}
""",
        encoding="utf-8",
    )
    response_source = manuscript / "revision_01" / "response" / "responses.tex"
    response_source.write_text(
        "\\Response{2-1}{The reference metadata was corrected.}\n"
        "\\ReviewReference{2-1}{hidden-citation-key-42}\n",
        encoding="utf-8",
    )

    result = project.build(target="all", engine="tectonic", keep_temp=True)

    output = manuscript / "revision_01" / "output"
    assert {artifact.label for artifact in result.artifacts} == {
        "Clean manuscript",
        "Marked manuscript",
        "Response letter",
    }
    clean_text = " ".join(_pdf_text(output / "manuscript_clean.pdf").split())
    marked_text = " ".join(_pdf_text(output / "manuscript_marked.pdf").split())
    assert "Bran A M" in clean_text
    assert "DOI: 10.1038/s42256-024-00832-8" in clean_text
    assert "DOI: https://doi.org/" not in clean_text
    assert "Bran A M" in marked_text
    assert "DOI: 10.1038/s42256-024-00832-8" in marked_text
    assert "M. Bran A" not in marked_text
    assert "DOI: 10.5555/Deleted.MixedCase" not in marked_text
    assert "hidden-citation-key-42" not in marked_text
    assert "DIFadd" not in marked_text
    assert "DIFdel" not in marked_text

    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    run = retained_runs[0]
    parent_bbl = (run / "parent_bibliography_build" / "manuscript.bbl").read_text(
        encoding="utf-8"
    )
    current_bbl = (run / "clean_build" / "manuscript.bbl").read_text(encoding="utf-8")
    assert not (run / "current_bibliography_build").exists()
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert "M. Bran A" in parent_bbl.replace("~", " ")
    assert "Bran A M" in current_bbl
    assert r"DOI: \nolinkurl{10.5555/Deleted.MixedCase}" in " ".join(parent_bbl.split())
    assert r"DOI: \nolinkurl{10.1038/s42256-024-00832-8}" in " ".join(
        current_bbl.split()
    )
    bibliography_source = _rendered_bibliography_source(marked_source)
    assert r"\SCIReviewReferenceSpan{2-1}{" in bibliography_source
    assert r"\DIFaddReview{" not in bibliography_source
    assert r"\DIFadd{" not in bibliography_source
    assert r"\DIFdel{" not in bibliography_source
    assert r"\SCIDeletedBibItem" not in bibliography_source
    assert r"\nolinkurl{10.1038/s42256-024-00832-8}" in bibliography_source
    assert r"\nolinkurl{10.5555/Deleted.MixedCase}" not in bibliography_source
    registry_lines = (
        (run / "marked_build" / "manuscript_marked.reviewloc")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert registry_lines[0] == TEX_LOCATION_REGISTRY_HEADER
    assert registry_lines[1].startswith("2-1|")
    response_text = _pdf_text(output / "response_letter.pdf")
    assert "The reference metadata was corrected." in response_text
    assert "修改位置：第" in response_text and "行。" in response_text
    assert "相关内容已删除" not in response_text
    audit = json.loads((run / "highlight_audit.json").read_text(encoding="utf-8"))
    assert audit["reference_visual_policy"] == "xcolor ProcessBlue"
    assert audit["clean_marked_reference_style_identity"] is True
    assert audit["clean_marked_source_projection_identity"] is True
    assert audit["whitespace_seam_identity"] is True
    assert audit["reviewer_reference_location_events"] >= 1
    assert audit["reference_provenance_conflicts"] == 0
    layout = (run / "revision_layout_qa.txt").read_text(encoding="utf-8")
    assert "Marked-specific overfull boxes: 0" in layout
    assert "Result: PASS" in layout


def test_math_revision_semantics_are_atomic_and_rendered(tmp_path: Path) -> None:
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
    initial = manuscript / "initial_submission" / "sections" / "01_manuscript.tex"
    old = r"""Deleted inline $\mathcal{O}_{\mathrm{P}}$ with a subscript.
Reviewer inline $a+b$ and parenthesized \(\mathcal{O}_{\mathrm{M},old}\), plus unchanged math $u=v$.
\begin{equation}
x+y=z\label{eq:partial}
\end{equation}
\begin{equation}
p=q\label{eq:deleted}
\end{equation}
\begin{equation}
\frac{a+b}{c+d}=e\label{eq:structural}
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
    current = revision / "sections" / "01_manuscript.tex"
    new = r"""\review{1-1}{Reviewer inline $a+c$ and parenthesized \(\mathcal{O}_{\mathrm{M},new}\), plus unchanged math $u=v$.
\begin{equation}
x+y+w=z\label{eq:partial}
\end{equation}
\begin{equation}
\sum_{i=1}^{n} x_i^2 = \mathcal{L}(\theta)\label{eq:structural}
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
    assert all(number in marked_text for number in ("(1)", "(2)", "(3)"))
    _assert_provenance_colors(marked_pdf, tmp_path / "math_colors")

    run = next((manuscript / "tmp").glob("run_*"))
    marked_source = (run / "marked_source" / "manuscript_marked.tex").read_text(
        encoding="utf-8"
    )
    assert "p=q" not in marked_source
    assert "r=s" in marked_source
    assert r"\frac{a+b}{c+d}=e" not in marked_source
    assert r"\sum_{i=1}^{n} x_i^2" in marked_source
    assert r"\label{eq:deleted}" not in marked_source
    assert marked_source.count("{eq:partial}") == 1
    assert marked_source.count("{eq:structural}") == 1
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

    project.build(target="clean", engine="tectonic")
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
    detector_parent = run / "marked_source" / "detector_parent.tex"
    detector_current = run / "marked_source" / "detector_current.tex"
    assert "52500063" in detector_parent.read_text(encoding="utf-8")
    assert "52131003" not in detector_parent.read_text(encoding="utf-8")
    assert "52131003" in detector_current.read_text(encoding="utf-8")
    assert "52327813" in detector_current.read_text(encoding="utf-8")


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

    project.build(target="clean", engine="tectonic")
    project.build(engine="tectonic", keep_temp=True)

    output = revision / "output"
    assert "FrontmatterAbstractSentinel" in _pdf_text(output / "manuscript_clean.pdf")
    assert "FrontmatterAbstractSentinel" in _pdf_text(output / "manuscript_marked.pdf")
    run = next((manuscript / "tmp").glob("run_*"))
    old_source = (run / "marked_source" / "detector_parent.tex").read_text(
        encoding="utf-8"
    )
    new_source = (run / "marked_source" / "detector_current.tex").read_text(
        encoding="utf-8"
    )
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
    assert re.search(rf"\\DIFadd(?:FL)?\{{[^}}]*{re.escape(visible)}", marked_source)
    marked_pdf = revision / "output" / "manuscript_marked.pdf"
    extracted = _pdf_text(marked_pdf)
    if not visible.isascii():
        # kxtbcas' Chinese title font can lack a usable ToUnicode map on some
        # macOS/Poppler combinations.  The exact marked-source assertion above
        # plus rendered author-addition color proves that the field reached the
        # final PDF without relying on font-text extraction metadata.
        _assert_rendered_color(
            marked_pdf, tmp_path / "frontmatter_render", (21, 155, 82)
        )
    else:
        assert visible in extracted


def test_three_corresponding_authors_reach_real_chinese_response_pdf(
    tmp_path: Path,
) -> None:
    _require_toolchain()
    resolve_author_library_path().write_text(
        """affiliations:
  first:
    name_en: First Institute, City 100001, Country
    name_zh: 第一研究院，城市 100001
  second:
    name_en: Second Institute, City 100002, Country
    name_zh: 第二研究院，城市 100002
  third:
    name_en: Third Institute, City 100003, Country
    name_zh: 第三研究院，城市 100003
authors:
  author_one:
    name_en: Author One
    name_zh: 作者甲
    email: one@example.invalid
    affiliations: [first, second]
  author_two:
    name_en: Author Two
    name_zh: 作者乙
    email: two@example.invalid
    correspondence_address: Explicit Correspondence Address 200002
    affiliations: [second]
  author_three:
    name_en: Author Three
    name_zh: 作者丙
    email: three@example.invalid
    affiliations: [third]
""",
        encoding="utf-8",
    )
    project_dir = tmp_path / "Three Corresponding Authors"
    initialize_manuscript(
        project_dir,
        title="三通讯作者回复信验证",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_three", "author_one", "author_two"),
        other_authors=("author_two", "author_three"),
        engine="tectonic",
    )
    reviews = tmp_path / "three_corresponding_reviews.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Please revise the manuscript.\n",
        encoding="utf-8",
    )
    manuscript = project_dir / "manuscript"
    project = ManuscriptProject(manuscript)
    project.start_revision(reviews=reviews, confirmed=True)
    revision = manuscript / "revision_01"
    _replace_once(
        revision / "sections" / "01_manuscript.tex",
        "Replace this placeholder with the manuscript body.",
        r"\review{1-1}{ThreeAuthorRevisionSentinel}",
    )
    (revision / "response" / "responses.tex").write_text(
        r"\Response{1-1}{ThreeAuthorResponseSentinel}" + "\n",
        encoding="utf-8",
    )

    project.build(target="response", engine="tectonic", keep_temp=True)

    response_pdf = revision / "output" / "response_letter.pdf"
    visible = "".join(_pdf_text(response_pdf).split())
    blocks = (
        ("作者甲", "通讯地址：第一研究院，城市100001", "邮箱：one@example.invalid"),
        (
            "作者乙",
            "通讯地址：ExplicitCorrespondenceAddress200002",
            "邮箱：two@example.invalid",
        ),
        ("作者丙", "通讯地址：第三研究院，城市100003", "邮箱：three@example.invalid"),
    )
    cursor = 0
    for block in blocks:
        for field in block:
            position = visible.find(field, cursor)
            assert position >= 0, field
            assert visible.count(field) == 1
            cursor = position + len(field)
    run = next((manuscript / "tmp").glob("run_*"))
    assembled = (run / "response_source" / "author_metadata.tex").read_text(
        encoding="utf-8"
    )
    zh = assembled.split(r"\newcommand{\CorrespondenceAuthorsZh}{%", 1)[1].split(
        "\n}", 1
    )[0]
    assert zh.count(r"\vspace{0.25\baselineskip}") == 6
    assert zh.count(r"\vspace{0.55\baselineskip}") == 2
    assert not zh.rstrip().endswith(r"\vspace{0.55\baselineskip}")


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
    body = revision / "sections" / "01_manuscript.tex"
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
    original_source = response_source.read_bytes()

    result = project.build(target="response", engine="tectonic", keep_temp=True)

    response_pdf = revision / "output" / "response_letter.pdf"
    assert response_pdf.is_file()
    response_text = _pdf_text(response_pdf)
    assert "尊敬的编辑" in response_text
    assert "回复构建链路测试" in response_text
    assert "《科学通报》" in response_text
    assert "ResponseSentinelOne" in response_text
    assert "ResponseSentinelTwo" in response_text
    assert "第" in response_text and "行" in response_text
    assert "Location unavailable" not in response_text
    assert "位置不可用" not in response_text
    assert "timesnewroman" in _pdf_fonts(response_pdf)
    assert any(artifact.path == response_pdf for artifact in result.artifacts)
    assert response_source.read_bytes() == original_source
    run = next((manuscript / "tmp").glob("run_*"))
    response_audit = json.loads(
        (run / "response_audit.json").read_text(encoding="utf-8")
    )
    assert response_audit["response_tex_projection_consistency"] is True
    assert response_audit["response_pdf_projection_consistency"] is True
    assert response_audit["response_source_pdf_consistency"] is True
    assembled = (run / "response_source" / "response_letter.tex").read_text(
        encoding="utf-8"
    )
    assert assembled.count(r"\reviewlocation{") == 1
    response_source.write_text(
        "\\Response{1-1}{ResponseSentinelUpdated}\n"
        "\\Response{1-2}{ResponseSentinelTwo}\n",
        encoding="utf-8",
    )

    project.build(target="response", engine="tectonic")

    rebuilt_text = _pdf_text(response_pdf)
    assert "ResponseSentinelUpdated" in rebuilt_text
    assert "ResponseSentinelOne" not in rebuilt_text

    response_source.write_text("\\Response{1-1}{Unbalanced.\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match=r"responses\.tex is invalid"):
        project.build(target="response", engine="tectonic")
    assert "ResponseSentinelUpdated" in _pdf_text(response_pdf)


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

    project.build(target="all", engine="tectonic", keep_temp=True)

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
    assert r"\DIFdel{" not in marked_source
    assert "ASM2d" in marked_source and "new" in marked_source
    registry = run / "marked_build" / "manuscript_marked.reviewloc"
    assert "1-1|" in registry.read_text(encoding="utf-8")
    _assert_provenance_colors(marked_pdf, tmp_path / "frontmatter_colors")
