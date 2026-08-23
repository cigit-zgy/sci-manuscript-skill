"""Architecture and lifecycle regression tests."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.compile import (
    CjkProbeResult,
    CompileResult,
    parse_overfull_boxes,
    validate_revision_layout,
)
from sci_manuscript.diff import _separate_inline_math_from_diff_markup
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    load_author_library,
    load_meta,
    render_publisher_metadata,
    resolve_authors,
)
from sci_manuscript.response import (
    parse_responses,
    parse_reviews,
    pending_response_ids,
    validate_review_id_list,
)
from sci_manuscript.workspace import (
    ProjectConfig,
    WorkflowError,
    ensure_submission_workspace,
    finalize_revision_creation,
    initialize_project,
    reindex_revisions,
    resources_root,
    source_digest,
    start_revision,
    temporary_run,
)


def _metadata(publisher: str = "elsevier", language: str = "en") -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="Anonymous Lifecycle Test",
        article_type="Research Article",
        language=language,
        journal_name="Example Journal",
        publisher=publisher,
        round_number=0,
        parent_round=None,
        first_authors=("first_author",),
        corresponding_authors=("first_author", "corresponding_author"),
        other_authors=("other_author",),
        submission=SubmissionSettings(),
    )


def _anonymous_author_library(tmp_path: Path) -> Path:
    path = tmp_path / "anonymous_authors.yaml"
    if not path.exists():
        path.write_text(
            """affiliations:
  institute:
    name_en: Anonymous Research Institute
    address: Example City
authors:
  first_author:
    name_en: First Author
    name_zh: 第一作者
    email: first@example.invalid
    affiliations: [institute]
  corresponding_author:
    name_en: Corresponding Author
    name_zh: 通讯作者
    email: corresponding@example.invalid
    affiliations: [institute]
  other_author:
    name_en: Other Author
    name_zh: 其他作者
    affiliations: [institute]
""",
            encoding="utf-8",
        )
    return path


def _workspace(
    tmp_path: Path,
    publisher: str = "elsevier",
    language: str = "en",
) -> ProjectConfig:
    root = tmp_path / "existing project" / "manuscript"
    root.parent.mkdir(parents=True)
    (root.parent / "unrelated.txt").write_text("preserve", encoding="utf-8")
    return initialize_project(
        ProjectConfig(root, _metadata(publisher, language)),
        _anonymous_author_library(tmp_path),
    )


def _revision(config: ProjectConfig, reviews: Path | None = None) -> ProjectConfig:
    with temporary_run(config.project) as run_dir:
        child = start_revision(config, config.current_round + 1, run_dir, reviews)
        from sci_manuscript.response import init_response

        init_response(child, child.current_round)
        finalize_revision_creation(child)
    return child


def test_public_api_is_stable() -> None:
    from sci_manuscript import __all__

    assert "ManuscriptProject" in __all__
    assert "initialize_manuscript" in __all__
    assert "workspace" not in __all__


def test_workspace_contract_and_meta(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    root = config.project
    assert (root.parent / "unrelated.txt").read_text() == "preserve"
    assert not (root / "run.py").exists()
    assert not (root / "tmp").exists()
    assert {path.name for path in (root / "references").iterdir()} == {
        "authors.yaml",
        "references.bib",
        "revision_style.tex",
    }
    initial = root / "initial_submission"
    assert (initial / "meta.yaml").is_file()
    assert not (initial / "manuscript.yaml").exists()
    assert "Document class" in (initial / "manuscript.tex").read_text()
    assert (initial / "sections" / "00_abstract.tex").is_file()
    assert not (initial / "sections" / "00_frontmatter.tex").exists()
    assert load_meta(initial / "meta.yaml").first_authors == ("first_author",)
    with pytest.raises(WorkflowError, match="overwrite"):
        initialize_project(config, _anonymous_author_library(tmp_path))


def test_chinese_workspace_has_frontmatter_and_semantic_free_body(
    tmp_path: Path,
) -> None:
    config = _workspace(tmp_path, publisher="chinese", language="zh")
    initial = config.round_dir(0)
    sections = initial / "sections"
    assert {path.name for path in sections.iterdir()} == {
        "00_frontmatter.tex",
        "01_manuscript.tex",
    }
    manuscript = (initial / "manuscript.tex").read_text(encoding="utf-8")
    frontmatter_input = r"\input{sections/00_frontmatter}"
    assert manuscript.index(frontmatter_input) < manuscript.index(r"\begin{document}")
    assert r"\input{sections/01_manuscript}" in manuscript
    assert r"\usepackage{indentfirst}" in manuscript
    assert r"\setlength{\parindent}" not in manuscript
    assert r"\bibliographystyle{kxtbcas-numeric}" in manuscript
    assert r"\bibliography{references}" in manuscript
    assert r"\clearpage" not in manuscript
    assert "kxtbsummary" not in manuscript
    for forbidden in ("methods", "results", "discussion", "conclusion"):
        assert forbidden not in manuscript.lower()
    frontmatter = (sections / "00_frontmatter.tex").read_text(encoding="utf-8")
    for command in (
        r"\title{",
        r"\author{",
        r"\enauthor{",
        r"\affiliation{",
        r"\enaffiliation{",
        r"\corrauthorcn{",
        r"\corrauthoren{",
    ):
        assert command not in frontmatter


def test_author_library_is_role_free_and_allows_overlap(tmp_path: Path) -> None:
    example = resources_root() / "authors.yaml"
    text = example.read_text(encoding="utf-8")
    assert "role:" not in text
    assert "zhao_guangyao:" in text
    assert "song_cheng:" in text
    path = _anonymous_author_library(tmp_path)
    library = load_author_library(path)
    selection = resolve_authors(_metadata(), library)
    assert selection.first_authors[0] in selection.corresponding_authors
    assert selection.authors[0].author_id == "first_author"


def test_chinese_publisher_uses_full_width_commas_between_authors(
    tmp_path: Path,
) -> None:
    metadata = _metadata(publisher="chinese", language="zh")
    selection = resolve_authors(
        metadata,
        load_author_library(_anonymous_author_library(tmp_path)),
    )
    rendered = render_publisher_metadata(metadata, selection)
    author_line = next(
        line for line in rendered.splitlines() if line.startswith(r"\author{")
    )
    assert author_line == (
        r"\author{第一作者$^{1,*}$，其他作者$^{1}$，通讯作者$^{1,*}$}"  # noqa: RUF001
    )
    assert "、" not in author_line
    assert (
        r"\enauthor{First Author$^{1,*}$, Other Author$^{1}$, "
        r"Corresponding Author$^{1,*}$}"
    ) in rendered


def test_revision_provenance_fallbacks_live_only_in_shared_preamble() -> None:
    root = resources_root()
    preamble = (root / "manuscript" / "preamble.tex").read_text(encoding="utf-8")
    definitions = (
        r"\providecommand{\review}[2]{#2}",
        r"\providecommand{\user}[1]{#1}",
    )
    for definition in definitions:
        assert definition in preamble
    templates = root / "journal_templates"
    for workflow in templates.glob("*/workflow.tex"):
        text = workflow.read_text(encoding="utf-8")
        for definition in definitions:
            assert definition not in text


def test_chinese_build_refuses_a_failed_real_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _workspace(tmp_path, publisher="chinese")
    monkeypatch.setattr(
        "sci_manuscript.compile.probe_cjk_environment",
        lambda _engine: CjkProbeResult(False, "anonymous CJK probe failure"),
    )
    with pytest.raises(WorkflowError, match="Chinese environment is blocked"):
        ManuscriptProject(config.project).build(engine="tectonic")


def test_chinese_init_preflight_runs_before_workspace_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def blocked(_config: ProjectConfig, _engine: str) -> None:
        raise WorkflowError("Chinese environment is blocked: anonymous failure")

    monkeypatch.setattr("sci_manuscript.api.ensure_cjk_environment", blocked)
    project = tmp_path / "blocked Chinese project"
    with pytest.raises(WorkflowError, match="Chinese environment is blocked"):
        initialize_manuscript(
            project,
            title="Blocked Test",
            journal="Example Journal",
            publisher="chinese",
            language="zh",
            article_type="Research Article",
            first_authors=("first_author",),
            corresponding_authors=("corresponding_author",),
            authors_path=_anonymous_author_library(tmp_path),
            engine="tectonic",
        )
    assert not (project / "manuscript").exists()


def test_revision_contract_and_parent_integrity(tmp_path: Path) -> None:
    r00 = _workspace(tmp_path)
    before = source_digest(r00.round_dir(0), scientific_only=True)
    r01 = _revision(r00)
    assert before == source_digest(r00.round_dir(0), scientific_only=True)
    assert r01.round_dir(1).name == "revision_01"
    assert load_meta(r01.round_dir(1) / "meta.yaml").parent_round == 0
    assert (r01.round_dir(1) / "revision_creation.yaml").is_file()
    assert not (r01.round_dir(1) / "references").exists()
    assert not any((r01.round_dir(1) / "output").iterdir())
    assert not any((r01.round_dir(1) / "submission").iterdir())
    r02 = _revision(r01)
    assert r02.round_dir(2).name == "revision_02"
    assert not (r02.project / "tmp").exists()


def test_rollback_success_and_refusal(tmp_path: Path) -> None:
    project = ManuscriptProject(_revision(_workspace(tmp_path)).project)
    result = project.rollback(confirmed=True)
    assert result.version == "initial_submission"
    assert result.artifacts[0].path.is_dir()
    r01 = _revision(ProjectConfig(project.root, _metadata()))
    section = r01.round_dir(1) / "sections" / "01_introduction.tex"
    section.write_text(section.read_text() + "\nUser edit.\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="source has changed"):
        ManuscriptProject(project.root).rollback(confirmed=True)


def test_reindex_success_preserves_scientific_bytes(tmp_path: Path) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    r03 = _revision(r02)
    before = {
        2: source_digest(r03.round_dir(2), scientific_only=True),
        3: source_digest(r03.round_dir(3), scientific_only=True),
    }
    shutil.rmtree(r03.round_dir(1))
    with temporary_run(r03.project) as run_dir:
        mapping = reindex_revisions(r03.project, run_dir)
    assert mapping == (
        ("revision_02", "revision_01"),
        ("revision_03", "revision_02"),
    )
    assert source_digest(r03.round_dir(1), scientific_only=True) == before[2]
    assert source_digest(r03.round_dir(2), scientific_only=True) == before[3]
    assert load_meta(r03.round_dir(1) / "meta.yaml").round_number == 1
    assert load_meta(r03.round_dir(2) / "meta.yaml").round_number == 2
    assert any((r03.project / "00_archive").iterdir())


def test_reindex_injected_failure_restores_original(tmp_path: Path) -> None:
    r03 = _revision(_revision(_revision(_workspace(tmp_path))))
    shutil.rmtree(r03.round_dir(1))
    before = {
        number: hashlib.sha256(
            (r03.round_dir(number) / "meta.yaml").read_bytes()
        ).hexdigest()
        for number in (2, 3)
    }
    with pytest.raises(WorkflowError, match="Injected"):
        with temporary_run(r03.project) as run_dir:
            reindex_revisions(r03.project, run_dir, fail_after_swap=True)
    assert not r03.round_dir(1).exists()
    for number in (2, 3):
        assert r03.round_dir(number).is_dir()
        observed = hashlib.sha256(
            (r03.round_dir(number) / "meta.yaml").read_bytes()
        ).hexdigest()
        assert observed == before[number]


def test_review_parser_ids_status_and_paragraphs(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Editor\n\n## E-1 | response_only\n\nFirst paragraph.\n\n"
        "Second paragraph with 10% and A_B.\n\n# Reviewer #1\n\n"
        "## 1-1 | manuscript_revised\n\nRevise this.\n",
        encoding="utf-8",
    )
    blocks = parse_reviews(reviews)
    assert [comment.review_id for block in blocks for comment in block.comments] == [
        "E-1",
        "1-1",
    ]
    assert blocks[0].comments[0].paragraphs == (
        "First paragraph.",
        "Second paragraph with 10% and A_B.",
    )
    assert blocks[0].comments[0].status == "response_only"
    assert validate_review_id_list("1-1,2-3") == ("1-1", "2-3")
    with pytest.raises(WorkflowError):
        validate_review_id_list("E-0")


def test_response_source_uses_authoritative_ids_and_preserves_user_edits(
    tmp_path: Path,
) -> None:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Editor\n\n## E-1 | response_only\n\nClarify scope.\n\n"
        "# Reviewer #1\n\n## 1-1 | manuscript_revised\n\nRevise text.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    source = config.round_dir(1) / "response" / "responses.tex"
    text = source.read_text(encoding="utf-8")
    assert text.count("\\Response{E-1}{") == 1
    assert text.count("\\Response{1-1}{") == 1
    assert "Clarify scope" not in text
    assert "Revise text" not in text
    assert "\\documentclass" not in text
    assert not (source.parent / "response_letter.tex").exists()
    source.write_text(text + "\n% user-owned edit\n", encoding="utf-8")
    from sci_manuscript.response import init_response

    with pytest.raises(WorkflowError, match="already exists"):
        init_response(config, 1)
    assert source.read_text(encoding="utf-8").endswith("% user-owned edit\n")


def test_responses_parser_supports_nested_latex_and_pending_markers(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        "% editable response content\n"
        "\\Response{E-1}{First {nested \\textbf{response}}.}\n"
        "\\Response{1-1}{\n\\ResponsePending{1-1}\n}\n",
        encoding="utf-8",
    )
    responses = parse_responses(source, ("E-1", "1-1"))
    assert responses["E-1"] == "First {nested \\textbf{response}}."
    assert pending_response_ids(responses) == ("1-1",)


@pytest.mark.parametrize(
    ("text", "expected", "message"),
    (
        (
            "\\Response{1-1}{A}\\Response{1-1}{B}",
            ("1-1",),
            "Duplicate response ID",
        ),
        ("\\Response{1-1}{A}", ("1-1", "2-1"), "Missing response IDs"),
        ("\\Response{2-1}{A}", ("1-1",), "Unknown response IDs"),
        ("\\Response{bad}{A}", ("1-1",), "Invalid response ID"),
    ),
)
def test_responses_parser_rejects_invalid_contracts(
    tmp_path: Path,
    text: str,
    expected: tuple[str, ...],
    message: str,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(WorkflowError, match=message):
        parse_responses(source, expected)


def test_response_build_uses_current_package_template_without_editing_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    reviews = tmp_path / "response_only.md"
    reviews.write_text(
        "# Editor\n\n## E-1 | response_only\n\nClarify scope.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    responses = config.round_dir(1) / "response" / "responses.tex"
    responses.write_text("\\Response{E-1}{Stable user response.}\n", encoding="utf-8")
    original = responses.read_bytes()
    package_root = tmp_path / "upgraded_package"
    template_dir = package_root / "correspondence_templates" / "response"
    template_dir.mkdir(parents=True)
    (template_dir / "response_en.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "UPGRADED TEMPLATE\n"
        "%%RESPONSE_BODY%%\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    def fake_compile(
        source: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None = None,
    ) -> CompileResult:
        assembled = source.read_text(encoding="utf-8")
        assert "UPGRADED TEMPLATE" in assembled
        assert "Stable user response." in assembled
        build_dir.mkdir(parents=True)
        pdf = build_dir / "response_letter.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return CompileResult(pdf, "")

    monkeypatch.setattr(response_module, "resources_root", lambda: package_root)
    monkeypatch.setattr(response_module, "compile_tex", fake_compile)
    run_dir = tmp_path / "run"
    result = response_module.build_response(config, 1, {}, run_dir)
    assert result.is_file()
    assert responses.read_bytes() == original
    assert not (responses.parent / "response_letter.tex").exists()
    assert (run_dir / "response_source" / "response_letter.tex").is_file()


def test_response_build_rejects_missing_marked_location(tmp_path: Path) -> None:
    reviews = tmp_path / "revised.md"
    reviews.write_text(
        "# Reviewer #1\n\n## 1-1 | manuscript_revised\n\nRevise the manuscript.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    response_source = config.round_dir(1) / "response" / "responses.tex"
    response_source.write_text(
        "\\Response{1-1}{Completed response.}\n", encoding="utf-8"
    )
    section = config.round_dir(1) / "sections" / "01_introduction.tex"
    section.write_text(
        section.read_text(encoding="utf-8") + "\n\\review{1-1}{Revision.}\n",
        encoding="utf-8",
    )
    import sci_manuscript.response as response_module

    with pytest.raises(WorkflowError, match="locations are missing for: 1-1"):
        response_module.build_response(config, 1, {}, tmp_path / "run")
    with pytest.raises(WorkflowError, match="locations are missing for: 1-1"):
        response_module.build_response(
            config,
            1,
            {"1-1": "Location unavailable"},
            tmp_path / "run_unavailable",
        )


def test_cover_guidance_blocks_submission_and_source_is_not_overwritten(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cover project" / "manuscript"
    config = initialize_project(
        ProjectConfig(
            root,
            replace(
                _metadata(),
                corresponding_authors=("first_author",),
            ),
        ),
        _anonymous_author_library(tmp_path),
    )
    source = ensure_submission_workspace(config, 0) / "cover_letter_body.tex"
    original = source.read_text(encoding="utf-8")
    assert "\\guidance{" in original
    assert "\\documentclass" not in original
    assert not (source.parent / "cover_letter.tex").exists()
    source.write_text(original + "\n% user-owned cover edit\n", encoding="utf-8")
    ensure_submission_workspace(config, 0)
    assert source.read_text(encoding="utf-8").endswith("% user-owned cover edit\n")
    with pytest.raises(WorkflowError, match="guidance"):
        ManuscriptProject(root).prepare_submission()


def test_submission_requires_signer_for_multiple_corresponding_authors(
    tmp_path: Path,
) -> None:
    config = _workspace(tmp_path)
    with pytest.raises(MetadataError, match="signing_author"):
        ManuscriptProject(config.project).prepare_submission()


def test_multi_id_review_location_registry(tmp_path: Path) -> None:
    from sci_manuscript.diff import REVIEW_REGISTRY_HEADER, _calculate_locations

    (tmp_path / "manuscript_marked.reviewloc").write_text(
        f"{REVIEW_REGISTRY_HEADER}\n1-1,2-3|1\nE-1|2\n", encoding="utf-8"
    )
    (tmp_path / "manuscript_marked.aux").write_text(
        "\\newlabel{review:1:start}{{7}{1}}\n"
        "\\newlabel{review:1:end}{{8}{1}}\n"
        "\\newlabel{review:2:start}{{12}{1}}\n"
        "\\newlabel{review:2:end}{{12}{1}}\n",
        encoding="utf-8",
    )
    assert _calculate_locations(tmp_path) == {
        "1-1": "Lines 7--8",
        "2-3": "Lines 7--8",
        "E-1": "Line 12",
    }


def test_empty_versioned_review_location_registry_is_valid(tmp_path: Path) -> None:
    from sci_manuscript.diff import REVIEW_REGISTRY_HEADER, _calculate_locations

    (tmp_path / "manuscript_marked.reviewloc").write_text(
        f"{REVIEW_REGISTRY_HEADER}\n", encoding="utf-8"
    )
    (tmp_path / "manuscript_marked.aux").write_text("", encoding="utf-8")
    assert _calculate_locations(tmp_path) == {}


def test_revision_layout_qa_rejects_marked_specific_overflow(
    tmp_path: Path,
) -> None:
    common = (
        "warning: manuscript.tex:13: Overfull \\hbox (2.57132pt too wide) "
        "in paragraph at lines 13--13\n"
    )
    marked = common.replace("manuscript.tex", "manuscript_marked.tex") + (
        "warning: manuscript_marked.tex:164: Overfull \\hbox "
        "(226.45685pt too wide) in paragraph at lines 160--164\n"
    )
    assert len(parse_overfull_boxes(marked + marked)) == 2
    report = tmp_path / "revision_layout_qa.txt"
    with pytest.raises(WorkflowError, match="226.46 pt"):
        validate_revision_layout(common, marked, report)
    assert "Marked-specific overfull boxes: 1" in report.read_text(encoding="utf-8")


def test_revision_layout_qa_accepts_only_clean_baseline_overflow(
    tmp_path: Path,
) -> None:
    clean = (
        "warning: manuscript.tex:13: Overfull \\hbox (2.57132pt too wide) "
        "in paragraph at lines 13--13\n"
    )
    marked = clean.replace("manuscript.tex", "manuscript_marked.tex")
    report = tmp_path / "revision_layout_qa.txt"
    assert validate_revision_layout(clean, marked, report) == report
    assert "Result: PASS" in report.read_text(encoding="utf-8")


def test_diff_markup_separates_inline_math_from_line_decoration() -> None:
    source = (
        r"\DIFadd{中文 $A \longrightarrow B$ 文本} "
        r"\DIFdel{old \(x+y\) text}"
    )
    rewritten = _separate_inline_math_from_diff_markup(source)
    assert rewritten == (
        r"\DIFadd{中文 }\DIFaddMath{$A \longrightarrow B$}\DIFadd{ 文本} "
        r"\DIFdel{old }\DIFdelMath{\(x+y\)}\DIFdel{ text}"
    )


@pytest.mark.integration
def test_init_api_returns_structured_result(tmp_path: Path) -> None:
    result = initialize_manuscript(
        tmp_path / "API Project 中文",
        title="API Test",
        journal="Example Journal",
        publisher="elsevier",
        language="en",
        article_type="Research Article",
        first_authors=("first_author",),
        corresponding_authors=("corresponding_author",),
        authors_path=_anonymous_author_library(tmp_path),
        engine="tectonic",
    )
    assert isinstance(result, LifecycleResult)
    assert result.artifacts[0].path.is_file()
    manuscript = tmp_path / "API Project 中文" / "manuscript"
    before = source_digest(manuscript / "initial_submission", scientific_only=True)
    ManuscriptProject(manuscript).build(engine="tectonic")
    assert before == source_digest(
        manuscript / "initial_submission", scientific_only=True
    )
    assert not (manuscript / "tmp").exists()


def test_review_scope_marks_only_actual_latexdiff_additions() -> None:
    from sci_manuscript.diff import (
        INTERNAL_REVIEW_END,
        INTERNAL_REVIEW_START,
        _denest_provenance,
        _expand_provenance_wrappers,
        _mark_reviewer_additions,
    )

    expanded = _expand_provenance_wrappers(
        r"\review{1-1,2-1}{Unchanged wording and revised wording.}"
    )
    assert expanded == (
        rf"{INTERNAL_REVIEW_START}{{1-1,2-1}}"
        rf"Unchanged wording and revised wording."
        rf"{INTERNAL_REVIEW_END}{{1-1,2-1}}"
    )

    latexdiff = (
        rf"\DIFadd{{{INTERNAL_REVIEW_START}{{1-1}}}}"
        r"Unchanged wording \DIFdel{old}\DIFadd{new} wording."
        rf"\DIFadd{{{INTERNAL_REVIEW_END}{{1-1}}}}"
        r" Outside \DIFadd{author addition}."
    )
    classified = _mark_reviewer_additions(_denest_provenance(latexdiff))
    assert r"Unchanged wording " in classified
    assert r"\DIFdel{old}" in classified
    assert r"\DIFaddReview{new}" in classified
    assert r"\DIFadd{author addition}" in classified
    assert r"\DIFaddReview{Unchanged wording" not in classified


def test_nested_review_scope_is_rejected() -> None:
    from sci_manuscript.diff import _expand_provenance_wrappers

    with pytest.raises(WorkflowError, match="Nested"):
        _expand_provenance_wrappers(r"\review{1-1}{outer \review{2-1}{inner}}")
