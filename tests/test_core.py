"""Architecture and lifecycle regression tests."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from sci_manuscript import ManuscriptProject, initialize_manuscript
from sci_manuscript.api import LifecycleResult
from sci_manuscript.authors import load_author_library, resolve_authors
from sci_manuscript.compile import (
    CjkProbeResult,
    CompileResult,
    parse_overfull_boxes,
    relocate_pre_document_section_inputs,
    resolve_engine,
    validate_revision_layout,
)
from sci_manuscript.diff import (
    _bibliography_change_states,
    _current_bibliography_with_reference_provenance,
    _flatten_tex,
    _remove_revision_output_diagnostics,
    _replace_bibliography,
)
from sci_manuscript.metadata import (
    ManuscriptMetadata,
    MetadataError,
    SubmissionSettings,
    load_meta,
    render_author_metadata,
    render_publisher_metadata,
)
from sci_manuscript.review import (
    parse_response_entries,
    parse_response_source,
    parse_reviews,
)
from sci_manuscript.review_ids import validate_review_id_list
from sci_manuscript.revision_render import CitationProvenance
from sci_manuscript.submission import ensure_submission_workspace
from sci_manuscript.workspace import (
    ProjectConfig,
    WorkflowError,
    bibliography_source_for_round,
    finalize_revision_creation,
    initialize_project,
    load_project,
    reindex_revisions,
    resources_root,
    source_digest,
    start_revision,
    temporary_run,
)


def test_bibliography_comparison_uses_keys_and_ignores_numbering() -> None:
    parent = r"""\providecommand{\EndOfBibitem}{}
\begin{thebibliography}{2}
\bibitem{a} Alpha old metadata.\EndOfBibitem
\bibitem{b} Beta deleted metadata.\EndOfBibitem
\end{thebibliography}
"""
    current = r"""\providecommand{\EndOfBibitem}{}
\begin{thebibliography}{2}
\bibitem[Gamma(2026)]{c} Gamma new metadata.\EndOfBibitem
\bibitem{a} Alpha corrected metadata.\EndOfBibitem
\end{thebibliography}
"""

    assert _bibliography_change_states(parent, current) == {
        "a": "modified",
        "b": "deleted",
        "c": "added",
    }

    renumbered = current.replace(r"\bibitem{a}", r"\bibitem[19]{a}")
    assert _bibliography_change_states(current, renumbered) == {
        "a": "unchanged",
        "c": "unchanged",
    }

    manuscript = r"""\documentclass{article}
\bibliographystyle{style}
\begin{document}
\bibliography{references}
\end{document}
"""
    materialized = _replace_bibliography(manuscript, current)
    assert r"\bibliographystyle" not in materialized
    assert r"\bibliography{references}" not in materialized
    assert "Gamma new metadata" in materialized


@pytest.mark.parametrize(
    ("old_content", "new_content"),
    (
        ("M. Bran A. Stable title.", "Bran A M. Stable title."),
        ("Author. Old title. 2024, 1, 1--2.", "Author. New title. 2024, 1, 1--2."),
        ("Author. Title. 2023, 1, 1--2.", "Author. Title. 2024, 1, 1--2."),
        ("Author. Title. 2024, 1, 1--2.", "Author. Title. 2024, 1, 3--4."),
        ("Author. Title. 2024, 1, 1--2.", "Author. Title. 2024, 1, 1--2. DOI: 10.1/x."),
    ),
)
def test_current_bibliography_provenance_wraps_only_real_current_changes(
    tmp_path: Path,
    old_content: str,
    new_content: str,
) -> None:
    parent = (
        r"\begin{thebibliography}{1}"
        "\n"
        r"\bibitem{stable-key} "
        f"{old_content}\n"
        r"\end{thebibliography}"
    )
    current = (
        r"\begin{thebibliography}{1}"
        "\n"
        r"\bibitem{stable-key} "
        f"{new_content}\n"
        r"\end{thebibliography}"
    )

    responses = tmp_path / "responses.tex"
    responses.write_text(
        r"\ReviewReference{1-1}{stable-key}"
        "\n",
        encoding="utf-8",
    )
    visible, notices = _current_bibliography_with_reference_provenance(
        parent, current, responses
    )

    if old_content not in new_content:
        assert old_content not in visible
    assert new_content in visible
    assert r"\SCIReviewReferenceSpan{1-1}{" in visible
    assert notices == ()


def test_review_reference_deleted_and_unchanged_keys_have_no_fake_location(
    tmp_path: Path,
) -> None:
    parent = (
        r"\begin{thebibliography}{2}"
        "\n"
        r"\bibitem{stable} Stable content."
        "\n"
        r"\bibitem{deleted} Deleted content."
        "\n"
        r"\end{thebibliography}"
    )
    current = (
        r"\begin{thebibliography}{1}"
        "\n"
        r"\bibitem[20]{stable} Stable content."
        "\n"
        r"\end{thebibliography}"
    )
    responses = tmp_path / "responses.tex"
    responses.write_text(
        r"\ReviewReference{1-1}{stable,deleted}"
        "\n",
        encoding="utf-8",
    )

    visible, notices = _current_bibliography_with_reference_provenance(
        parent, current, responses
    )

    assert r"\SCIReviewSpan" not in visible
    assert "Deleted content" not in visible
    assert {notice.code for notice in notices} == {
        "REVIEW_REFERENCE_UNCHANGED",
        "REVIEW_REFERENCE_DELETED",
    }


def test_review_reference_unknown_key_reports_id_key_and_absolute_path(
    tmp_path: Path,
) -> None:
    bibliography = (
        r"\begin{thebibliography}{1}"
        "\n"
        r"\bibitem{known} Known."
        "\n"
        r"\end{thebibliography}"
    )
    responses = tmp_path / "responses.tex"
    responses.write_text(
        r"\ReviewReference{2-5}{unknownKey}"
        "\n",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError) as error:
        _current_bibliography_with_reference_provenance(
            bibliography, bibliography, responses
        )

    message = str(error.value)
    assert "2-5" in message
    assert "unknownKey" in message
    assert str(responses.resolve()) in message


def _single_bibliography(key: str, content: str) -> str:
    return (
        r"\begin{thebibliography}{1}"
        "\n"
        f"\\bibitem{{{key}}} {content}\n"
        r"\end{thebibliography}"
    )


def test_new_author_citation_and_bibliography_entry_are_both_author_owned(
    tmp_path: Path,
) -> None:
    parent = _single_bibliography("stable", "Stable.")
    current = _single_bibliography("newKey", "New entry.")
    responses = tmp_path / "responses.tex"
    responses.write_text("", encoding="utf-8")

    visible, _notices = _current_bibliography_with_reference_provenance(
        parent,
        current,
        responses,
        {"newKey": CitationProvenance(None, (12,))},
    )

    assert r"\bibitem{newKey} New entry." in visible
    assert r"\DIFadd" not in visible
    assert r"\SCIReviewReferenceSpan" not in visible


def test_new_reviewer_citation_and_bibliography_entry_are_both_reviewer_owned(
    tmp_path: Path,
) -> None:
    parent = _single_bibliography("stable", "Stable.")
    current = _single_bibliography("newKey", "New entry.")
    responses = tmp_path / "responses.tex"
    responses.write_text("", encoding="utf-8")

    visible, _notices = _current_bibliography_with_reference_provenance(
        parent,
        current,
        responses,
        {"newKey": CitationProvenance(("1-1",), (12,))},
    )

    assert r"\SCIReviewReferenceSpan{1-1}{ New entry." in visible
    assert r"\DIFaddReview" not in visible


def test_review_reference_agreement_and_reviewer_union_are_allowed(
    tmp_path: Path,
) -> None:
    parent = _single_bibliography("stable", "Stable.")
    current = _single_bibliography("newKey", "New entry.")
    responses = tmp_path / "responses.tex"
    responses.write_text(
        r"\ReviewReference{1-1}{newKey}"
        "\n"
        r"\ReviewReference{2-2}{newKey}",
        encoding="utf-8",
    )

    visible, _notices = _current_bibliography_with_reference_provenance(
        parent,
        current,
        responses,
        {"newKey": CitationProvenance(("1-1",), (12,))},
    )

    assert r"\SCIReviewReferenceSpan{1-1,2-2}" in visible


def test_author_citation_and_review_reference_raise_provenance_conflict(
    tmp_path: Path,
) -> None:
    parent = _single_bibliography("stable", "Stable.")
    current = _single_bibliography("newKey", "New entry.")
    responses = tmp_path / "responses.tex"
    responses.write_text(
        r"\ReviewReference{2-5}{newKey}",
        encoding="utf-8",
    )

    with pytest.raises(WorkflowError, match="REFERENCE_PROVENANCE_CONFLICT") as error:
        _current_bibliography_with_reference_provenance(
            parent,
            current,
            responses,
            {"newKey": CitationProvenance(None, (172,))},
        )

    message = str(error.value)
    assert "newKey" in message
    assert "AUTHOR" in message and "REVIEWER" in message
    assert "172" in message and str(responses.resolve()) in message


def test_revision_output_cleanup_preserves_exact_three_pdfs(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    expected = {
        "manuscript_clean.pdf",
        "manuscript_marked.pdf",
        "response_letter.pdf",
    }
    for name in (*expected, "diff_audit.json", "highlight_audit.json"):
        (output / name).write_bytes(b"artifact")

    _remove_revision_output_diagnostics(output)

    assert {path.name for path in output.iterdir()} == expected


def test_highlight_audit_remains_in_run_workspace(tmp_path: Path) -> None:
    output = tmp_path / "revision_01" / "output"
    run = tmp_path / "tmp" / "run_123"
    output.mkdir(parents=True)
    run.mkdir(parents=True)
    audit = run / "highlight_audit.json"
    audit.write_text("{}\n", encoding="utf-8")

    _remove_revision_output_diagnostics(output)

    assert audit.is_file()
    assert not (output / "highlight_audit.json").exists()


def test_repeated_output_cleanup_never_republishes_legacy_audit(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    legacy = output / "diff_audit.json"
    legacy.write_text("{}\n", encoding="utf-8")

    _remove_revision_output_diagnostics(output)
    _remove_revision_output_diagnostics(output)

    assert not legacy.exists()


def _metadata(publisher: str = "elsevier", language: str = "en") -> ManuscriptMetadata:
    return ManuscriptMetadata(
        title="Anonymous Lifecycle Test",
        article_type="Research Article",
        language=language,
        journal_name="Example Journal",
        publisher=publisher,
        round_number=0,
        parent_round=None,
        first_authors=("author_one",),
        corresponding_authors=("author_one", "author_two"),
        other_authors=("author_three",),
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
  author_one:
    name_en: First Author
    name_zh: 第一作者
    email: first@example.invalid
    affiliations: [institute]
  author_two:
    name_en: Corresponding Author
    name_zh: 通讯作者
    email: corresponding@example.invalid
    affiliations: [institute]
  author_three:
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
    language: str | None = None,
) -> ProjectConfig:
    selected_language = language or ("zh" if publisher == "chinese" else "en")
    root = tmp_path / "existing project" / "manuscript"
    root.parent.mkdir(parents=True)
    (root.parent / "unrelated.txt").write_text("preserve", encoding="utf-8")
    return initialize_project(
        ProjectConfig(root, _metadata(publisher, selected_language)),
    )


def _revision(config: ProjectConfig, reviews: Path | None = None) -> ProjectConfig:
    with temporary_run(config.project) as run_dir:
        child = start_revision(config, config.current_round + 1, run_dir, reviews)
        from sci_manuscript.response import init_response

        init_response(child, child.current_round)
        finalize_revision_creation(child)
    return child


def test_workspace_rejects_symlinks_in_managed_round_sources(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    external = tmp_path / "external.tex"
    external.write_text("private external source", encoding="utf-8")
    link = config.round_dir(0) / "sections" / "external.tex"
    link.symlink_to(external)

    with pytest.raises(WorkflowError, match="Symbolic links are forbidden"):
        load_project(config.project)


def test_public_api_is_stable() -> None:
    from sci_manuscript import __all__

    assert "ManuscriptProject" in __all__
    assert "initialize_manuscript" in __all__
    assert "workspace" not in __all__


def test_latex_engine_is_part_of_the_v2_public_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ProjectConfig(tmp_path / "manuscript", _metadata())
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert resolve_engine(config, "latex") == "latex"


def test_flatten_tex_ignores_comments_and_rejects_root_escape(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    source = root / "manuscript.tex"
    included = root / "included.tex"
    outside = tmp_path / "outside.tex"
    included.write_text("Included text.\n", encoding="utf-8")
    outside.write_text("Outside text.\n", encoding="utf-8")
    source.write_text(
        "% \\input{included}\nVisible.\n\\input{included}\n",
        encoding="utf-8",
    )

    flattened = _flatten_tex(source, (root,))

    assert flattened.count("Included text.") == 1
    source.write_text("\\input{../outside}\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="escapes permitted project roots"):
        _flatten_tex(source, (root,))


def test_flatten_tex_ignores_malformed_commented_input_and_reports_active_path(
    tmp_path: Path,
) -> None:
    current = tmp_path / "revision_01"
    sibling = tmp_path / "initial_submission"
    current.mkdir()
    sibling.mkdir()
    (sibling / "secret.tex").write_text("parent round", encoding="utf-8")
    source = current / "manuscript.tex"
    source.write_text("% \\input{unfinished\nVisible.\n", encoding="utf-8")
    assert "Visible." in _flatten_tex(source, (current,))

    source.write_text("\\input{unfinished\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="Malformed active TeX input") as error:
        _flatten_tex(source, (current,))
    assert str(source.resolve()) in str(error.value)

    source.write_text("\\input{../initial_submission/secret}\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="escapes permitted project roots"):
        _flatten_tex(source, (current,))


def test_runtime_staging_moves_all_visible_section_inputs_into_document() -> None:
    source = r"""\documentclass{article}
\input{publisher_metadata}
\input{preamble/en}
\input{sections/frontmatter_custom}
% \input{sections/commented_out}
\begin{document}
\input{sections/body}
\end{document}
"""

    relocated = relocate_pre_document_section_inputs(source)

    boundary = relocated.index(r"\begin{document}")
    assert relocated.index(r"\input{publisher_metadata}") < boundary
    assert relocated.index(r"\input{preamble/en}") < boundary
    assert relocated.index(r"\input{sections/frontmatter_custom}") > boundary
    assert relocated.index(r"\input{sections/body}") > boundary
    assert relocated.count(r"\input{sections/frontmatter_custom}") == 1
    assert "% \\input{sections/commented_out}" in relocated


def test_workspace_contract_and_meta(tmp_path: Path) -> None:
    config = _workspace(tmp_path)
    root = config.project
    assert (root.parent / "unrelated.txt").read_text() == "preserve"
    assert not (root / "run.py").exists()
    assert not (root / "tmp").exists()
    assert config.output_dir(0) == root / "initial_submission" / "output"
    assert config.response_dir(1) == root / "revision_01" / "response"
    assert config.submission_dir(1) == root / "revision_01" / "submission"
    assert config.state_dir(1) == root / "state" / "revision_01"
    assert config.review_index_path(1) == (
        root / "state" / "revision_01" / "review_index.yaml"
    )
    assert config.creation_record_path(1) == (
        root / "state" / "revision_01" / "creation.yaml"
    )
    assert config.tmp_root() == root / "tmp"
    assert config.archive_root() == root / "00_archive"
    assert {path.name for path in (root / "references").iterdir()} == {
        "references.bib",
        "revision_style.tex",
    }
    initial = root / "initial_submission"
    assert (initial / "meta.yaml").is_file()
    assert not (initial / "manuscript.yaml").exists()
    assert "Document class" in (initial / "manuscript.tex").read_text()
    assert not (initial / "sections" / "00_abstract.tex").exists()
    frontmatter = initial / "sections" / "00_frontmatter.tex"
    assert frontmatter.is_file()
    frontmatter_text = frontmatter.read_text(encoding="utf-8")
    assert r"\title{" in frontmatter_text
    assert "Anonymous Lifecycle Test" in frontmatter_text
    assert load_meta(initial / "meta.yaml").first_authors == ("author_one",)
    with pytest.raises(WorkflowError, match="overwrite"):
        initialize_project(config)


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
    assert r"\input{preamble/zh}" in manuscript
    assert r"\usepackage{indentfirst}" not in manuscript
    assert r"\makeatletter" not in manuscript
    assert r"\setlength{\parindent}" not in manuscript
    assert r"\bibliographystyle{kxtbcas-numeric}" in manuscript
    assert r"\bibliography{references}" in manuscript
    assert r"\clearpage" not in manuscript
    assert manuscript.count(r"\makeenglishsummary") == 1
    assert manuscript.index(r"\bibliography{references}") < manuscript.index(
        r"\makeenglishsummary"
    )
    for forbidden in ("methods", "results", "discussion", "conclusion"):
        assert forbidden not in manuscript.lower()
    frontmatter = (sections / "00_frontmatter.tex").read_text(encoding="utf-8")
    for command in (
        r"\title{",
        r"\entitle{",
    ):
        assert command in frontmatter
    for command in (
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
    assert selection.authors[0].author_id == "author_one"


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
    shared = render_author_metadata(metadata, selection)
    assert (
        r"\newcommand{\SelectedAuthorNamesZh}{第一作者，其他作者，通讯作者}"  # noqa: RUF001
        in shared
    )
    assert (
        r"\newcommand{\CorrespondingAuthorNameZh}{第一作者，通讯作者}"  # noqa: RUF001
        in shared
    )


def test_revision_provenance_definition_lives_only_in_shared_preamble() -> None:
    root = resources_root()
    preamble = (root / "manuscript_preamble" / "common.tex").read_text(encoding="utf-8")
    definitions = (r"\providecommand{\review}[2]{#2}",)
    for definition in definitions:
        assert definition in preamble
    templates = root / "journal_templates"
    for workflow in templates.glob("*/workflow.tex"):
        text = workflow.read_text(encoding="utf-8")
        for definition in definitions:
            assert definition not in text


def test_response_automatic_signature_uses_frozen_locale_email_labels() -> None:
    templates = resources_root() / "correspondence_templates" / "response"
    chinese = (templates / "response_zh.tex").read_text(encoding="utf-8")
    english = (templates / "response_en.tex").read_text(encoding="utf-8")

    assert r"\CorrespondenceAuthorsZh" in chinese
    assert r"\CorrespondenceAuthorsEn" in english
    assert r"\CorrespondenceAuthorsEn" not in chinese
    assert r"\CorrespondenceAuthorsZh" not in english


def test_response_templates_require_times_new_roman_for_latin_text() -> None:
    templates = resources_root() / "correspondence_templates" / "response"
    chinese = (templates / "response_zh.tex").read_text(encoding="utf-8")
    english = (templates / "response_en.tex").read_text(encoding="utf-8")

    for template in (chinese, english):
        assert r"\usepackage{fontspec}" in template
        assert r"\setmainfont{Times New Roman}" in template
        assert r"\usepackage{lmodern}" not in template


def test_chinese_build_refuses_a_failed_real_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _workspace(tmp_path, publisher="chinese")
    monkeypatch.setattr(
        "sci_manuscript.compile.probe_cjk_environment",
        lambda _engine, _telemetry=None: CjkProbeResult(
            False, "anonymous CJK probe failure"
        ),
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
            first_authors=("author_one",),
            corresponding_authors=("author_two",),
            engine="tectonic",
        )
    assert not (project / "manuscript").exists()


def test_init_rejects_unsupported_publisher_language_before_workspace_creation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "unsupported matrix"
    with pytest.raises(MetadataError, match="accepted language"):
        initialize_manuscript(
            project,
            title="Unsupported Test",
            journal="Example Journal",
            publisher="elsevier",
            language="zh",
            article_type="Research Article",
            first_authors=("zhao_guangyao",),
            corresponding_authors=("liu_hong",),
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
    assert r01.creation_record_path(1).is_file()
    assert not (r01.round_dir(1) / "references").exists()
    assert not any((r01.round_dir(1) / "output").iterdir())
    assert not any((r01.round_dir(1) / "submission").iterdir())
    r02 = _revision(r01)
    assert r02.round_dir(2).name == "revision_02"
    assert not (r02.project / "tmp").exists()


def test_revision_creation_preserves_commented_review_and_strips_live_wrapper(
    tmp_path: Path,
) -> None:
    config = _workspace(tmp_path)
    section = config.round_dir(0) / "sections" / "01_introduction.tex"
    section.write_text(
        section.read_text(encoding="utf-8")
        + "\n% \\review{1-1}{Disabled provenance.}\n"
        + "\\review{1-1}{Visible inherited text.}\n",
        encoding="utf-8",
    )

    child = _revision(config)
    inherited = (child.round_dir(1) / "sections" / "01_introduction.tex").read_text(
        encoding="utf-8"
    )

    assert "% \\review{1-1}{Disabled provenance.}" in inherited
    assert "Visible inherited text." in inherited
    assert "\\review{1-1}{Visible inherited text.}" not in inherited


def test_failed_revision_creation_removes_partial_round_state_and_tmp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _workspace(tmp_path)
    parent_before = source_digest(config.round_dir(0), scientific_only=True)
    from sci_manuscript.workspace import snapshot_bibliography

    parent_snapshot = snapshot_bibliography(config, 0)
    snapshot_before = parent_snapshot.read_bytes()
    (config.references / "references.bib").write_text(
        "@article{replace_me, title={Changed before failed revision}}\n",
        encoding="utf-8",
    )

    def fail_after_state(child: ProjectConfig) -> Path:
        path = child.creation_record_path(child.current_round)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("partial: true\n", encoding="utf-8")
        raise WorkflowError("injected revision finalization failure")

    monkeypatch.setattr(
        "sci_manuscript.api.finalize_revision_creation",
        fail_after_state,
    )

    with pytest.raises(WorkflowError, match="injected revision"):
        ManuscriptProject(config.project).start_revision(confirmed=True)

    assert not config.round_dir(1).exists()
    assert not config.state_dir(1).exists()
    assert not config.tmp_root().exists()
    assert source_digest(config.round_dir(0), scientific_only=True) == parent_before
    assert parent_snapshot.read_bytes() == snapshot_before
    assert not config.round_state_path(0).exists()


def test_sync_bib_uses_only_the_explicit_export(tmp_path: Path) -> None:
    config = _revision(_workspace(tmp_path))
    parent_snapshot = config.bibliography_snapshot_path(0)
    frozen_parent = parent_snapshot.read_bytes()
    unrelated = config.project.parent / "unrelated.txt"
    before = unrelated.read_bytes()
    export = tmp_path / "user-export.bib"
    export.write_text("@article{explicit, title={Explicit export}}\n", encoding="utf-8")

    result = ManuscriptProject(config.project).sync_bib(export)

    assert result.artifacts[0].path == config.references / "references.bib"
    assert result.artifacts[0].path.read_bytes() == export.read_bytes()
    assert parent_snapshot.read_bytes() == frozen_parent
    assert unrelated.read_bytes() == before
    with pytest.raises(WorkflowError, match="is missing"):
        ManuscriptProject(config.project).sync_bib(tmp_path / "missing.bib")
    malformed = tmp_path / "malformed.bib"
    malformed.write_text("not BibTeX", encoding="utf-8")
    with pytest.raises(WorkflowError, match="does not contain BibTeX"):
        ManuscriptProject(config.project).sync_bib(malformed)


def test_round_bibliography_snapshots_preserve_visible_history(tmp_path: Path) -> None:
    r00 = _workspace(tmp_path)
    shared = r00.references / "references.bib"
    bibliography_a = b"@article{replace_me, title={Parent bibliography}}\n"
    bibliography_b = b"@article{replace_me, title={First revision bibliography}}\n"
    bibliography_c = b"@article{replace_me, title={Second revision bibliography}}\n"
    shared.write_bytes(bibliography_a)

    r01 = _revision(r00)
    assert r01.bibliography_snapshot_path(0).read_bytes() == bibliography_a
    shared.write_bytes(bibliography_b)
    assert bibliography_source_for_round(r01, 0).read_bytes() == bibliography_a
    assert bibliography_source_for_round(r01, 1).read_bytes() == bibliography_b

    r02 = _revision(r01)
    assert r02.bibliography_snapshot_path(1).read_bytes() == bibliography_b
    shared.write_bytes(bibliography_c)
    assert bibliography_source_for_round(r02, 0).read_bytes() == bibliography_a
    assert bibliography_source_for_round(r02, 1).read_bytes() == bibliography_b
    assert bibliography_source_for_round(r02, 2).read_bytes() == bibliography_c

    r02.bibliography_snapshot_path(1).unlink()
    with pytest.raises(WorkflowError, match="Historical bibliography snapshot"):
        bibliography_source_for_round(r02, 1)


def test_revision_creation_refreshes_active_bibliography_before_freezing(
    tmp_path: Path,
) -> None:
    r00 = _workspace(tmp_path)
    shared = r00.references / "references.bib"
    from sci_manuscript.workspace import snapshot_bibliography

    snapshot_bibliography(r00, 0)
    updated = b"@article{replace_me, title={Updated before revision}}\n"
    shared.write_bytes(updated)

    r01 = _revision(r00)

    assert r01.bibliography_snapshot_path(0).read_bytes() == updated


def test_revision_creation_refuses_conflicting_parent_round_state_atomically(
    tmp_path: Path,
) -> None:
    r00 = _workspace(tmp_path)
    from sci_manuscript.workspace import snapshot_bibliography

    snapshot_bibliography(r00, 0)
    frozen = r00.round_state_path(0)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    frozen.write_text("schema: conflicting\n", encoding="utf-8")

    with pytest.raises(WorkflowError, match="HISTORICAL_ROUND_STATE_MISMATCH"):
        _revision(r00)

    assert not r00.round_dir(1).exists()


def test_rollback_success_and_refusal(tmp_path: Path) -> None:
    revision = _revision(_workspace(tmp_path))
    parent_bibliography = revision.bibliography_snapshot_path(0).read_bytes()
    current_bibliography = b"@article{replace_me, title={Current revision}}\n"
    (revision.references / "references.bib").write_bytes(current_bibliography)
    project = ManuscriptProject(revision.project)
    result = project.rollback(confirmed=True)
    assert result.version == "initial_submission"
    assert result.artifacts[0].path.is_dir()
    assert not (project.root / "state" / "revision_01").exists()
    assert (
        result.artifacts[0].path.parent / "state" / "revision_01" / "creation.yaml"
    ).is_file()
    assert (
        result.artifacts[0].path.parent / "state" / "revision_01" / "bibliography.bib"
    ).read_bytes() == current_bibliography
    assert (revision.references / "references.bib").read_bytes() == parent_bibliography
    r01 = _revision(ProjectConfig(project.root, _metadata()))
    section = r01.round_dir(1) / "sections" / "01_introduction.tex"
    section.write_text(section.read_text() + "\nUser edit.\n", encoding="utf-8")
    with pytest.raises(WorkflowError, match="source has changed"):
        ManuscriptProject(project.root).rollback(confirmed=True)


def test_reindex_success_preserves_scientific_bytes(tmp_path: Path) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    r03 = _revision(r02)
    bibliography_by_round = {
        number: r03.bibliography_snapshot_path(number).read_bytes()
        for number in (0, 1, 2)
    }
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
    assert r03.creation_record_path(1).is_file()
    assert r03.creation_record_path(2).is_file()
    assert r03.bibliography_snapshot_path(0).read_bytes() == bibliography_by_round[0]
    assert r03.bibliography_snapshot_path(1).read_bytes() == bibliography_by_round[2]
    assert not r03.state_dir(3).exists()
    assert load_meta(r03.round_dir(2) / "meta.yaml").round_number == 2
    assert any((r03.project / "00_archive").iterdir())


def test_reindex_preserves_editable_submission_sources(tmp_path: Path) -> None:
    r01 = _revision(_workspace(tmp_path))
    r02 = _revision(r01)
    r03 = _revision(r02)
    submission = r02.submission_dir(2)
    graphical = submission / "graphical_abstract"
    graphical.mkdir(parents=True, exist_ok=True)
    editable = {
        "cover_letter_body.tex": b"user cover letter\n",
        "highlights.tex": b"user highlights\n",
        "checklist.md": b"user checklist note\n",
        "supporting_note.txt": b"user submission note\n",
        "graphical_abstract/graphical_abstract.tex": b"user graphical source\n",
    }
    for relative, content in editable.items():
        path = submission / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    for relative in (
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
        "cover_letter.pdf",
        "highlights.pdf",
    ):
        path = submission / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated pdf")
    shutil.rmtree(r03.round_dir(1))

    with temporary_run(r03.project) as run_dir:
        reindex_revisions(r03.project, run_dir)

    migrated = r03.submission_dir(1)
    for relative, content in editable.items():
        assert (migrated / relative).read_bytes() == content
    for relative in (
        "manuscript.pdf",
        "marked_manuscript.pdf",
        "response_letter.pdf",
        "cover_letter.pdf",
        "highlights.pdf",
        "graphical_abstract/graphical_abstract.pdf",
    ):
        assert not (migrated / relative).exists()


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


def test_review_parser_ids_summary_and_paragraphs(tmp_path: Path) -> None:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Editor\n\n## Main comment\n\nFirst paragraph.\n\n"
        "Second paragraph with 10% and A_B.\n\n## Specific comments\n\n"
        "1. Clarify scope.\n\n# Reviewer #1\n\n## Main comment\n\n"
        "## Specific comments\n\n1. Revise this.\n",
        encoding="utf-8",
    )
    blocks = parse_reviews(reviews)
    assert [comment.review_id for block in blocks for comment in block.comments] == [
        "E-1",
        "1-1",
    ]
    assert blocks[0].summary == (
        "First paragraph.",
        "Second paragraph with 10% and A_B.",
    )
    assert validate_review_id_list("1-1,2-3") == ("1-1", "2-3")
    with pytest.raises(WorkflowError):
        validate_review_id_list("E-0")


def test_response_source_uses_authoritative_ids_and_preserves_user_edits(
    tmp_path: Path,
) -> None:
    reviews = tmp_path / "reviews.md"
    reviews.write_text(
        "# Editor\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Clarify scope.\n\n# Reviewer #1\n\n## Main comment\n\n"
        "## Specific comments\n\n1. Revise text.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    source = config.round_dir(1) / "response" / "responses.tex"
    text = source.read_text(encoding="utf-8")
    assert parse_response_entries(source) == {"E-1": "", "1-1": ""}
    assert "% Clarify scope." in text
    assert "% Revise text." in text
    assert "\\documentclass" not in text
    assert not (source.parent / "response_letter.tex").exists()
    source.write_text(text + "\n% user-owned edit\n", encoding="utf-8")
    from sci_manuscript.response import init_response

    with pytest.raises(WorkflowError, match="already exists"):
        init_response(config, 1)
    assert source.read_text(encoding="utf-8").endswith("% user-owned edit\n")


def test_response_parser_supports_nested_latex(
    tmp_path: Path,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(
        "% editable response content\n"
        "\\Response{E-1}{First {nested \\textbf{response}}.}\n"
        "\\Response{1-1}{Second response.}\n",
        encoding="utf-8",
    )
    responses = parse_response_entries(source)
    assert responses["E-1"] == "First {nested \\textbf{response}}."
    assert responses["1-1"] == "Second response."


@pytest.mark.parametrize(
    ("text", "message"),
    (
        (
            "\\Response{1-1}{A}\\Response{1-1}{B}",
            "Duplicate response ID",
        ),
        ("\\Response{bad}{A}", "Invalid response ID"),
    ),
)
def test_responses_parser_rejects_invalid_contracts(
    tmp_path: Path,
    text: str,
    message: str,
) -> None:
    source = tmp_path / "responses.tex"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(WorkflowError, match=message):
        parse_response_entries(source)


def test_response_build_uses_package_template_without_mutating_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    reviews = tmp_path / "response_only.md"
    reviews.write_text(
        "# Editor\n\n## Main comment\n\n## Specific comments\n\n1. Clarify scope.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    responses = config.round_dir(1) / "response" / "responses.tex"
    responses.write_text(
        "\\Response{E-1}{Stable user response.}\n",
        encoding="utf-8",
    )
    original_source = responses.read_bytes()
    package_root = tmp_path / "upgraded_package"
    template_dir = package_root / "correspondence_templates" / "response"
    template_dir.mkdir(parents=True)
    (template_dir / "response_en.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "UPGRADED FIXED OPENING\n"
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
        assert "UPGRADED FIXED OPENING" in assembled
        assert "Stable user response." in assembled
        build_dir.mkdir(parents=True)
        pdf = build_dir / "response_letter.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return CompileResult(pdf, "")

    monkeypatch.setattr(response_module, "resources_root", lambda: package_root)
    monkeypatch.setattr(response_module, "compile_tex", fake_compile)
    monkeypatch.setattr(
        response_module,
        "_response_pdf_consistency",
        lambda *_args, **_kwargs: (True, ()),
    )
    run_dir = tmp_path / "run"
    result = response_module.build_response(config, 1, {}, run_dir)
    assert result.is_file()
    parsed = parse_response_source(responses)
    assert parsed.responses == {"E-1": "Stable user response."}
    assert responses.read_bytes() == original_source
    assert tuple(config.archive_root().rglob("responses.tex")) == ()
    assert not (responses.parent / "response_letter.tex").exists()
    assert (run_dir / "response_source" / "response_letter.tex").is_file()


def test_response_build_rejects_pdf_missing_visible_response_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    reviews = tmp_path / "pdf_consistency.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Clarify scope.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    responses = config.response_dir(1) / "responses.tex"
    responses.write_text("\\Response{1-1}{VisibleResponseSentinel}\n", encoding="utf-8")

    def fake_compile(
        _source: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None = None,
    ) -> CompileResult:
        build_dir.mkdir(parents=True)
        pdf = build_dir / "response_letter.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return CompileResult(pdf, "")

    monkeypatch.setattr(response_module, "ensure_response_latin_font", lambda: None)
    monkeypatch.setattr(response_module, "compile_tex", fake_compile)
    monkeypatch.setattr(
        response_module,
        "_extract_pdf_text",
        lambda _path: "Dear Editor, Comment 1-1",
        raising=False,
    )

    with pytest.raises(WorkflowError, match="RESPONSE_SOURCE_PDF_CONSISTENCY_FAILED"):
        response_module.build_response(config, 1, {}, tmp_path / "run")


def test_response_build_accepts_empty_response_for_response_only_comment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sci_manuscript.response as response_module

    reviews = tmp_path / "unanswered.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Please clarify.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    responses = config.round_dir(1) / "response" / "responses.tex"
    responses.write_text(
        "\\Response{1-1}{}\n",
        encoding="utf-8",
    )

    def fake_compile(
        source: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None = None,
    ) -> CompileResult:
        assembled = source.read_text(encoding="utf-8")
        assert "Please clarify." in assembled
        build_dir.mkdir(parents=True)
        pdf = build_dir / "response_letter.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return CompileResult(pdf, "")

    monkeypatch.setattr(response_module, "compile_tex", fake_compile)
    monkeypatch.setattr(
        response_module,
        "_response_pdf_consistency",
        lambda *_args, **_kwargs: (True, ()),
    )

    result = response_module.build_response(config, 1, {}, tmp_path / "run")

    assert result.is_file()
    assert responses.read_text(encoding="utf-8") == "\\Response{1-1}{}\n"


def test_response_build_omits_unavailable_marked_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviews = tmp_path / "revised.md"
    reviews.write_text(
        "# Reviewer #1\n\n## Main comment\n\n## Specific comments\n\n"
        "1. Revise the manuscript.\n",
        encoding="utf-8",
    )
    config = _revision(_workspace(tmp_path), reviews)
    response_source = config.round_dir(1) / "response" / "responses.tex"
    response_source.write_text(
        "\\Response{1-1}{Completed response.}\n",
        encoding="utf-8",
    )
    section = config.round_dir(1) / "sections" / "01_introduction.tex"
    section.write_text(
        section.read_text(encoding="utf-8") + "\n\\review{1-1}{Revision.}\n",
        encoding="utf-8",
    )
    import sci_manuscript.response as response_module

    def fake_compile(
        source: Path,
        build_dir: Path,
        _config: ProjectConfig,
        _engine: str | None = None,
    ) -> CompileResult:
        assert r"\reviewlocation{" not in source.read_text(encoding="utf-8")
        build_dir.mkdir(parents=True)
        pdf = build_dir / "response_letter.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        return CompileResult(pdf, "")

    monkeypatch.setattr(response_module, "compile_tex", fake_compile)
    monkeypatch.setattr(
        response_module,
        "_response_pdf_consistency",
        lambda *_args, **_kwargs: (True, ()),
    )
    assert response_module.build_response(config, 1, {}, tmp_path / "run").is_file()


def test_cover_guidance_blocks_submission_and_source_is_not_overwritten(
    tmp_path: Path,
) -> None:
    root = tmp_path / "cover project" / "manuscript"
    config = initialize_project(
        ProjectConfig(
            root,
            replace(
                _metadata(),
                corresponding_authors=("author_one",),
            ),
        ),
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


@pytest.mark.integration
def test_init_api_returns_structured_result(tmp_path: Path) -> None:
    result = initialize_manuscript(
        tmp_path / "API Project 中文",
        title="API Test",
        journal="Example Journal",
        publisher="elsevier",
        language="en",
        article_type="Research Article",
        first_authors=("author_one",),
        corresponding_authors=("author_two",),
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
