"""Canonical review, response, and location workflow contracts."""

# ruff: noqa: RUF001 -- exact frozen Chinese response-letter punctuation.

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from sci_manuscript import ManuscriptProject
from sci_manuscript.api import LifecycleResult
from sci_manuscript.cli import _print_lifecycle
from sci_manuscript.errors import WorkflowError
from sci_manuscript.metadata import ManuscriptMetadata, SubmissionSettings
from sci_manuscript.response import ensure_response_source
from sci_manuscript.review import (
    audit_reviews,
    parse_response_entries,
    parse_response_source,
    parse_reviews,
)
from sci_manuscript.workspace import ProjectConfig, initialize_project


def _project(tmp_path: Path, language: str = "en") -> ProjectConfig:
    root = tmp_path / language / "manuscript"
    root.parent.mkdir(parents=True)
    metadata = ManuscriptMetadata(
        title="Review Workflow Test",
        article_type="Research Article",
        language=language,
        journal_name="Example Journal",
        publisher="kxtbcas" if language == "zh" else "elsevier",
        round_number=0,
        parent_round=None,
        first_authors=("author",),
        corresponding_authors=("author",),
        other_authors=(),
        submission=SubmissionSettings(),
    )
    return initialize_project(ProjectConfig(root, metadata))


def _canonical_reviews(path: Path) -> None:
    path.write_text(
        """# Editor

## Main comment

Optional editor summary.

## Specific comments

1. First editor detail.
2. Second editor detail.

# Reviewer #1

## Main comment

## Specific comments

1. First reviewer detail.
2.
3. Second reviewer detail.
""",
        encoding="utf-8",
    )


@pytest.mark.parametrize("language", ("zh", "en"))
def test_revision_initializes_response_entries_without_free_letter(
    tmp_path: Path, language: str
) -> None:
    config = _project(tmp_path, language)

    ManuscriptProject(config.project).start_revision(confirmed=True)

    source = config.response_dir(1) / "responses.tex"
    parsed = parse_response_source(source)
    assert parsed.responses == {}
    text = source.read_text(encoding="utf-8")
    assert r"\ResponseLetter" not in text
    if language == "zh":
        assert "% 逐条回复" in text
    else:
        assert "% Point-by-point responses" in text


def test_ensure_response_source_never_mutates_user_responses(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    ManuscriptProject(config.project).start_revision(confirmed=True)
    source = config.response_dir(1) / "responses.tex"
    custom = "\\Response{1-1}{Stable {nested} user response.}\n"
    source.write_text(custom, encoding="utf-8")

    assert ensure_response_source(config, 1) == source
    assert source.read_text(encoding="utf-8") == custom


def test_legacy_response_letter_is_rejected_with_migration_diagnostic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        "\\ResponseLetter{CUSTOM RESPONSE LETTER SENTINEL}\n"
        "\\Response{1-1}{Stable response.}\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="LEGACY_RESPONSE_LETTER_UNSUPPORTED"):
        parse_response_source(source)


def test_canonical_parser_uses_summary_without_id_and_ignores_blank_items(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reviews.md"
    _canonical_reviews(path)

    blocks = parse_reviews(path)

    assert blocks[0].summary == ("Optional editor summary.",)
    assert [comment.review_id for comment in blocks[0].comments] == ["E-1", "E-2"]
    assert blocks[1].summary == ()
    assert [comment.review_id for comment in blocks[1].comments] == ["1-1", "1-2"]


@pytest.mark.parametrize(
    "invalid_source",
    (
        "# Reviewer #1\n\n1. Old unlabeled list.\n",
        "# Reviewer #1\n\n## Unknown section\n\nOld detail.\n",
        "# Unknown role\n\n## Main comment\n\n## Specific comments\n\n1. Detail.\n",
    ),
)
def test_noncanonical_review_formats_are_rejected(
    tmp_path: Path,
    invalid_source: str,
) -> None:
    path = tmp_path / "reviews.md"
    path.write_text(invalid_source, encoding="utf-8")

    with pytest.raises(WorkflowError):
        parse_reviews(path)


def test_revision_initializes_only_actual_response_entries(tmp_path: Path) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)

    result = ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )

    response_source = config.response_dir(1) / "responses.tex"
    assert parse_response_entries(response_source) == {
        "E-1": "",
        "E-2": "",
        "1-1": "",
        "1-2": "",
    }
    text = response_source.read_text(encoding="utf-8")
    assert "% Optional editor summary." in text
    assert r"\ResponseLetter{" not in text
    assert "Revision locations are calculated automatically" not in text
    assert all(token not in text for token in ("Location:", "Lines "))
    assert any(artifact.path == response_source for artifact in result.artifacts)


def test_blank_revision_still_initializes_response_scaffold_and_editor_example(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)

    ManuscriptProject(config.project).start_revision(confirmed=True)

    source = config.response_dir(1) / "responses.tex"
    assert source.is_file()
    text = source.read_text(encoding="utf-8")
    assert r"\ResponseLetter{" not in text
    assert "% Editor" in text


def test_audit_reports_missing_empty_and_orphan_without_blocking(
    tmp_path: Path,
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text(
        "\\Response{E-1}{Completed.}\n"
        "\\Response{E-2}{}\n"
        "\\Response{1-2}{Completed.}\n"
        "\\Response{2-1}{Orphan.}\n",
        encoding="utf-8",
    )

    audit = audit_reviews(config, 1)

    codes = {(issue.code, issue.review_id) for issue in audit.issues}
    assert ("EMPTY_RESPONSE", "E-2") in codes
    assert ("MISSING_RESPONSE", "1-1") in codes
    assert ("ORPHAN_RESPONSE", "2-1") in codes
    assert not audit.is_complete


def test_cli_completeness_output_is_concise_and_hides_source_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text(
        "\\Response{E-1}{}\n",
        encoding="utf-8",
    )
    audit = audit_reviews(config, 1)

    _print_lifecycle(LifecycleResult("build", "revision_01", (), audit), config.project)

    output = capsys.readouterr().out
    assert "Review responses incomplete:" in output
    assert "- E-1: empty response" in output
    assert "- E-2: missing response" in output
    assert "Path:" not in output
    assert str(config.response_dir(1)) not in output


def test_cli_malformed_response_prints_its_absolute_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _project(tmp_path)
    reviews = tmp_path / "reviews.md"
    _canonical_reviews(reviews)
    ManuscriptProject(config.project).start_revision(
        reviews=reviews,
        confirmed=True,
    )
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text(
        "\\Response{invalid}{Body.}\n",
        encoding="utf-8",
    )
    audit = audit_reviews(config, 1)

    _print_lifecycle(LifecycleResult("build", "revision_01", (), audit), config.project)

    output = capsys.readouterr().out
    assert "RESPONSES_INVALID" in output
    assert f"Path: {responses.resolve()}" in output


def test_response_templates_own_localized_automatic_location_labels() -> None:
    resources = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "resources"
        / "correspondence_templates"
        / "response"
    )
    zh = (resources / "response_zh.tex").read_text(encoding="utf-8")
    en = (resources / "response_en.tex").read_text(encoding="utf-8")
    assert "修改位置：#1。" in zh
    assert "Location: #1." in en
    assert "Location of revisions:" not in en
    assert "给编辑的回复" not in zh
    assert "Response to the Editor" not in en
    assert "%%RESPONSE_LETTER%%" not in zh
    assert "%%RESPONSE_LETTER%%" not in en
    assert zh.count("%%RESPONSE_BODY%%") == 1
    assert en.count("%%RESPONSE_BODY%%") == 1
    assert zh.count(r"\clearpage") == 1
    assert en.count(r"\clearpage") == 1
    assert r"\newcommand{\ResponseSection}[1]" in zh
    assert r"\newcommand{\ResponseSection}[1]" in en
    assert r"\CorrespondenceAuthorsZh" in zh
    assert r"\CorrespondenceAuthorsEn" in en
    assert "谨代表全体作者" not in zh
    assert "on behalf of all authors" not in en
    assert "1.20\\baselineskip" in zh
    assert "1.20\\baselineskip" in en
    assert "稿件题目" not in zh
    assert "Manuscript ID" not in en


@pytest.mark.parametrize(
    ("system_name", "platform_name", "latin", "cjk"),
    (
        (
            "Darwin",
            "macOS",
            ("Times New Roman", "Times", "TeX Gyre Termes"),
            ("Songti SC", "STSong", "Noto Serif CJK SC"),
        ),
        (
            "Windows",
            "Windows",
            ("Times New Roman", "Cambria", "Georgia"),
            ("SimSun", "NSimSun", "Noto Serif CJK SC"),
        ),
        (
            "Linux",
            "Linux",
            (
                "Times New Roman",
                "TeX Gyre Termes",
                "Liberation Serif",
                "Nimbus Roman",
            ),
            ("Noto Serif CJK SC", "Source Han Serif SC", "FandolSong"),
        ),
    ),
)
def test_response_font_candidates_are_platform_ordered_serif_fallbacks(
    system_name: str,
    platform_name: str,
    latin: tuple[str, ...],
    cjk: tuple[str, ...],
) -> None:
    from sci_manuscript.response import response_font_candidates

    assert response_font_candidates(system_name) == (platform_name, latin, cjk)


def test_response_font_resolution_uses_first_tex_usable_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    attempts: list[tuple[str, str]] = []

    def usable(
        _config: ProjectConfig,
        _probe_root: Path,
        kind: str,
        candidate: str,
        _engine: str | None,
        _telemetry: object,
    ) -> bool:
        attempts.append((kind, candidate))
        return candidate in {"Times", "STSong"}

    monkeypatch.setattr(response_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(response_module, "_font_usable_by_tex", usable)

    resolution = response_module.resolve_response_fonts(
        _project(tmp_path, "zh"), tmp_path / "font_probe"
    )

    assert resolution.platform == "macOS"
    assert resolution.latin_preferred == "Times New Roman"
    assert resolution.latin_resolved == "Times"
    assert resolution.latin_fallback is True
    assert resolution.cjk_resolved == "STSong"
    assert attempts == [
        ("latin", "Times New Roman"),
        ("latin", "Times"),
        ("cjk", "Songti SC"),
        ("cjk", "STSong"),
    ]


def test_response_font_resolution_fails_with_platform_and_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    monkeypatch.setattr(response_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        response_module,
        "_font_usable_by_tex",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(WorkflowError) as error:
        response_module.resolve_response_fonts(
            _project(tmp_path, "en"), tmp_path / "font_probe"
        )

    message = str(error.value)
    assert "RESPONSE_LATIN_FONT_UNAVAILABLE" in message
    assert "platform=Linux" in message
    assert "Times New Roman" in message
    assert "Nimbus Roman" in message


def test_response_font_contract_compiles_mixed_text_with_preferred_fonts(
    tmp_path: Path,
) -> None:
    tectonic = shutil.which("tectonic")
    pdffonts = shutil.which("pdffonts")
    if tectonic is None or pdffonts is None:
        pytest.skip("Tectonic and pdffonts are required for response font QA")
    source = tmp_path / "response-font-contract.tex"
    source.write_text(
        r"""\documentclass{article}
\usepackage{fontspec}
\usepackage{xeCJK}
\setmainfont{Times New Roman}
\setCJKmainfont{Songti SC}
\begin{document}
中文 English 2026 DOI response
\end{document}
""",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [tectonic, "-X", "compile", str(source)],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stdout
    fonts = subprocess.run(
        [pdffonts, str(source.with_suffix(".pdf"))],
        cwd=tmp_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert fonts.returncode == 0, fonts.stdout
    normalized = fonts.stdout.replace(" ", "").lower()
    assert "timesnewroman" in normalized
    assert "songti" in normalized


def test_response_parser_preserves_multiline_latex_body_semantics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        r"""\Response{1-1}{
第一段包含 English、引用~\cite{example}、行内公式 $x_1+y$ 与转义符号 \% 和 \&。

第二段包含 \textbf{nested {braces}}。
}
""",
        encoding="utf-8",
    )

    responses = parse_response_entries(source)

    assert set(responses) == {"1-1"}
    assert "第一段包含 English" in responses["1-1"]
    assert r"\cite{example}" in responses["1-1"]
    assert r"$x_1+y$" in responses["1-1"]
    assert "第二段" in responses["1-1"]
    assert r"\textbf{nested {braces}}" in responses["1-1"]


def test_response_parser_ignores_commented_legacy_letter(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        r"""% commented reading aid: \ResponseLetter{not active}
\Response{1-1}{
Please preserve \textit{our {nested} response} \{carefully\}.
}
""",
        encoding="utf-8",
    )

    parsed = parse_response_source(source)

    assert parsed.responses == {
        "1-1": r"Please preserve \textit{our {nested} response} \{carefully\}."
    }


def test_response_parser_supports_multiple_reference_keys(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        "% reading aid\n"
        "\\Response{2-5}{Completed.}\n"
        "\\ReviewReference{2-5}{refA, refB,refA}\n",
        encoding="utf-8",
    )

    parsed = parse_response_source(source)

    assert parsed.responses == {"2-5": "Completed."}
    assert parsed.references[0].citation_keys == ("refA", "refB")
    assert parsed.references[0].source_line == 3


@pytest.mark.parametrize(
    "command", (r"\ResponseOpening{Text}", r"\ResponseClosing{Text}")
)
def test_removed_response_commands_are_rejected(tmp_path: Path, command: str) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(f"{command}\n", encoding="utf-8")

    with pytest.raises(WorkflowError, match="Unexpected"):
        parse_response_source(source)
