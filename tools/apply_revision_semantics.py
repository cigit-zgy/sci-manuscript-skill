"""One-shot repository migration for reviewer-aware diff semantics."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, found {count}")
    return updated


def update_diff() -> None:
    path = "src/sci_manuscript/diff.py"
    text = read(path)
    text = replace_once(
        text,
        'REVIEW_REGISTRY_HEADER = "sci-manuscript-reviewloc-v1"\n',
        'REVIEW_REGISTRY_HEADER = "sci-manuscript-reviewloc-v1"\n'
        'INTERNAL_REVIEW_START = r"\\sciReviewStart"\n'
        'INTERNAL_REVIEW_END = r"\\sciReviewEnd"\n'
        'CHINESE_TEXT_COMMANDS = (\n'
        '    "cnabstract",\n'
        '    "cnkeywords",\n'
        '    "enabstract",\n'
        '    "enkeywords",\n'
        '    "firstauthorcn",\n'
        '    "firstauthoren",\n'
        '    "funding",\n'
        '    "entitle",\n'
        ')\n',
        "diff constants",
    )
    text = sub_once(
        text,
        r"\\newif\\ifRevisionReviewContext\n\\providecommand\{\\DIFaddMath\}\[1\]\{%.*?\\newbox\\DIFdelDisplayMathBox",
        r'''\providecommand{\DIFaddMath}[1]{%
  {\RevisionAddedFont\color{RevisionAddedColor}#1}%
}
\providecommand{\DIFaddReviewMath}[1]{%
  {\RevisionReviewFont\color{RevisionReviewColor}#1}%
}
\newbox\DIFdelDisplayMathBox''',
        "explicit addition math semantics",
    )
    text = sub_once(
        text,
        r"\\providecommand\{\\DIFadd\}\[1\]\{%.*?(?=\\providecommand\{\\DIFdel\}\[1\])",
        r'''\providecommand{\DIFadd}[1]{%
  \ifmmode
    \DIFaddMath{#1}%
  \else
    \RevisionAddedBackground{{\RevisionAddedFont\color{RevisionAddedColor}\RevisionAddedUnderline{#1}}}%
  \fi
}
\providecommand{\DIFaddReview}[1]{%
  \ifmmode
    \DIFaddReviewMath{#1}%
  \else
    \RevisionReviewBackground{{\RevisionReviewFont\color{RevisionReviewColor}\RevisionReviewUnderline{#1}}}%
  \fi
}
''',
        "explicit text addition semantics",
    )
    text = replace_once(
        text,
        r"\providecommand{\DIFaddFL}[1]{\DIFadd{#1}}" + "\n",
        r"\providecommand{\DIFaddFL}[1]{\DIFadd{#1}}" + "\n"
        + r"\providecommand{\DIFaddReviewFL}[1]{\DIFaddReview{#1}}"
        + "\n",
        "review float addition macro",
    )
    text = sub_once(
        text,
        r"\\providecommand\{\\review\}\[2\]\{#2\}\n\\providecommand\{\\user\}\[1\]\{#1\}\n\\AtBeginDocument\{%.*?\n\}\n\"\"\"",
        r'''\providecommand{\review}[2]{#2}
\providecommand{\user}[1]{#1}
\providecommand{\sciReviewStart}[1]{}
\providecommand{\sciReviewEnd}[1]{}
\newcommand{\CurrentReviewBlockID}{0}
\AtBeginDocument{%
  % User-facing provenance wrappers stay visually transparent. The marked-source
  % preprocessor replaces \review with internal boundaries before latexdiff so
  % unchanged text can still align with the parent revision.
  \renewcommand{\review}[2]{#2}%
  \renewcommand{\user}[1]{#1}%
  \renewcommand{\sciReviewStart}[1]{%
    \stepcounter{reviewblock}%
    \xdef\CurrentReviewBlockID{\arabic{reviewblock}}%
    \leavevmode
    \ReviewLineLabel{review:\CurrentReviewBlockID:start}%
    \immediate\write\ReviewLocationFile{#1|\CurrentReviewBlockID}%
  }%
  \renewcommand{\sciReviewEnd}[1]{%
    \leavevmode
    \ReviewLineLabel{review:\CurrentReviewBlockID:end}%
  }%
}
"""''',
        "transparent review runtime",
    )
    parser_pattern = (
        r"def _parse_provenance_command\(text: str, start: int\) -> tuple\[str, int\] \| None:\n"
        r".*?(?=\n\ndef _split_added_content)"
    )
    parser_replacement = r'''def _parse_command_arguments(
    text: str,
    start: int,
    name: str,
    count: int,
) -> tuple[tuple[str, ...], int] | None:
    if not text.startswith(name, start):
        return None
    end_name = start + len(name)
    if end_name < len(text) and (text[end_name].isalnum() or text[end_name] == "@"):
        return None
    cursor = end_name
    arguments: list[str] = []
    for _ in range(count):
        cursor = _skip_space(text, cursor)
        if cursor >= len(text) or text[cursor] != "{":
            return None
        argument, cursor = _extract_braced(text, cursor)
        arguments.append(argument)
    return tuple(arguments), cursor


def _expand_provenance_wrappers(text: str, *, review_depth: int = 0) -> str:
    """Replace user provenance wrappers with transparent diff boundaries."""
    output: list[str] = []
    cursor = 0
    while cursor < len(text):
        if text[cursor] == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            end = len(text) if newline == -1 else newline + 1
            output.append(text[cursor:end])
            cursor = end
            continue
        if text[cursor] == "\\":
            parsed_review = _parse_command_arguments(text, cursor, r"\review", 2)
            if parsed_review is not None:
                if review_depth:
                    raise WorkflowError(
                        "Nested \\review blocks are ambiguous; combine reviewer IDs "
                        "in one wrapper instead."
                    )
                (raw_ids, body), end = parsed_review
                review_ids = tuple(item.strip() for item in raw_ids.split(",") if item.strip())
                if not review_ids or any(not is_review_id(item) for item in review_ids):
                    raise WorkflowError(
                        f"Invalid reviewer ID list {raw_ids!r}; expected IDs such as 1-1."
                    )
                ids = ",".join(review_ids)
                expanded_body = _expand_provenance_wrappers(body, review_depth=1)
                output.append(
                    f"{INTERNAL_REVIEW_START}{{{ids}}}{expanded_body}"
                    f"{INTERNAL_REVIEW_END}{{{ids}}}"
                )
                cursor = end
                continue
            parsed_user = _parse_command_arguments(text, cursor, r"\user", 1)
            if parsed_user is not None:
                (body,), end = parsed_user
                output.append(_expand_provenance_wrappers(body, review_depth=review_depth))
                cursor = end
                continue
        output.append(text[cursor])
        cursor += 1
    return "".join(output)


def _parse_provenance_command(text: str, start: int) -> tuple[str, int] | None:
    for name, count in (
        (INTERNAL_REVIEW_START, 1),
        (INTERNAL_REVIEW_END, 1),
        (r"\review", 2),
        (r"\user", 1),
    ):
        parsed = _parse_command_arguments(text, start, name, count)
        if parsed is not None:
            _, end = parsed
            return text[start:end], end
    return None'''
    text = sub_once(text, parser_pattern, parser_replacement, "provenance parser")
    text = replace_once(
        text,
        '            if r"\\review" in content or r"\\user" in content:\n'
        '                raise WorkflowError(\n'
        '                    "Could not safely separate provenance markup from latexdiff output."\n'
        '                )\n',
        '            if any(\n'
        '                marker in content\n'
        '                for marker in (\n'
        '                    INTERNAL_REVIEW_START,\n'
        '                    INTERNAL_REVIEW_END,\n'
        '                    r"\\review",\n'
        '                    r"\\user",\n'
        '                )\n'
        '            ):\n'
        '                raise WorkflowError(\n'
        '                    "Could not safely separate provenance markup from latexdiff output."\n'
        '                )\n',
        "denest safety check",
    )
    marker = '\n\ndef _find_inline_math_end(text: str, start: int) -> int | None:\n'
    reviewer_classifier = r'''

def _mark_reviewer_additions(text: str) -> str:
    """Classify only latexdiff additions inside review boundaries as reviewer work."""
    output: list[str] = []
    cursor = 0
    active_ids: str | None = None
    while cursor < len(text):
        if text[cursor] == "%" and not _is_escaped(text, cursor):
            newline = text.find("\n", cursor)
            end = len(text) if newline == -1 else newline + 1
            output.append(text[cursor:end])
            cursor = end
            continue
        if text[cursor] == "\\":
            start_marker = _parse_command_arguments(
                text, cursor, INTERNAL_REVIEW_START, 1
            )
            if start_marker is not None:
                (ids,), end = start_marker
                if active_ids is not None:
                    raise WorkflowError("Nested internal reviewer boundaries are invalid.")
                active_ids = ids
                output.append(text[cursor:end])
                cursor = end
                continue
            end_marker = _parse_command_arguments(text, cursor, INTERNAL_REVIEW_END, 1)
            if end_marker is not None:
                (ids,), end = end_marker
                if active_ids is None or ids != active_ids:
                    raise WorkflowError("Unbalanced internal reviewer boundaries.")
                active_ids = None
                output.append(text[cursor:end])
                cursor = end
                continue
            if active_ids is not None:
                for source, target in (
                    (r"\DIFaddFL", r"\DIFaddReviewFL"),
                    (r"\DIFadd", r"\DIFaddReview"),
                ):
                    parsed = _parse_command_arguments(text, cursor, source, 1)
                    if parsed is None:
                        continue
                    (content,), end = parsed
                    output.append(f"{target}{{{content}}}")
                    cursor = end
                    break
                else:
                    output.append(text[cursor])
                    cursor += 1
                continue
        output.append(text[cursor])
        cursor += 1
    if active_ids is not None:
        raise WorkflowError("Unclosed internal reviewer boundary in marked source.")
    return "".join(output)
'''
    text = replace_once(text, marker, reviewer_classifier + marker, "review classifier")
    text = replace_once(
        text,
        '    math_macro = r"\\DIFaddMath" if macro == r"\\DIFadd" else r"\\DIFdelMath"\n',
        '    math_macros = {\n'
        '        r"\\DIFadd": r"\\DIFaddMath",\n'
        '        r"\\DIFaddReview": r"\\DIFaddReviewMath",\n'
        '        r"\\DIFdel": r"\\DIFdelMath",\n'
        '    }\n'
        '    math_macro = math_macros[macro]\n',
        "review math dispatch",
    )
    text = replace_once(
        text,
        '    macros = (r"\\DIFadd", r"\\DIFdel")\n',
        '    macros = (r"\\DIFaddReview", r"\\DIFadd", r"\\DIFdel")\n',
        "inline math macros",
    )
    text = replace_once(
        text,
        '    new_text = _flatten_tex(current / "manuscript.tex", roots)\n',
        '    new_text = _expand_provenance_wrappers(\n'
        '        _flatten_tex(current / "manuscript.tex", roots)\n'
        '    )\n',
        "new-source provenance expansion",
    )
    text = replace_once(
        text,
        '        "--disable-citation-markup",\n'
        '        "--append-textcmd=review,user",\n'
        '        "--ignore-warnings",\n',
        '        "--disable-citation-markup",\n'
        '        "--ignore-warnings",\n',
        "remove wrapper text command",
    )
    text = replace_once(
        text,
        '    result = run_command(command, cwd=source_dir)\n',
        '    if config.metadata.publisher == "chinese":\n'
        '        command.insert(\n'
        '            -3, f"--append-textcmd={\',\'.join(CHINESE_TEXT_COMMANDS)}"\n'
        '        )\n'
        '    result = run_command(command, cwd=source_dir)\n',
        "Chinese text commands",
    )
    text = replace_once(
        text,
        '    denested = _denest_provenance(result.stdout)\n'
        '    marked_source.write_text(\n'
        '        _separate_inline_math_from_diff_markup(denested), encoding="utf-8"\n'
        '    )\n',
        '    denested = _denest_provenance(result.stdout)\n'
        '    classified = _mark_reviewer_additions(denested)\n'
        '    marked_source.write_text(\n'
        '        _separate_inline_math_from_diff_markup(classified), encoding="utf-8"\n'
        '    )\n',
        "review addition classification",
    )
    write(path, text)


def update_api() -> None:
    path = "src/sci_manuscript/api.py"
    text = read(path)
    old = '''    def build(
        self,
        round: str | int | None = None,
        *,
        engine: str | None = None,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Compile one clean manuscript without changing its source."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        with temporary_run(self.root, keep_temp) as run_dir:
            clean = build_clean_manuscript(config, selected, run_dir, engine)
        return LifecycleResult(
            "build",
            revision_directory_name(selected),
            (Artifact("Clean manuscript", clean),),
        )
'''
    new = '''    def build(
        self,
        round: str | int | None = None,
        *,
        engine: str | None = None,
        keep_temp: bool = False,
    ) -> LifecycleResult:
        """Compile clean output and retain the adjacent marked PDF for revisions."""
        latest = load_project(self.root)
        selected = parse_round(round, latest.current_round)
        config = load_project(self.root, selected)
        with temporary_run(self.root, keep_temp) as run_dir:
            clean = build_clean_manuscript(config, selected, run_dir, engine)
            artifacts = [Artifact("Clean manuscript", clean)]
            if selected > 0:
                marked = build_marked_manuscript(config, selected, run_dir, engine)
                artifacts.append(Artifact("Marked manuscript", marked.pdf))
        return LifecycleResult(
            "build",
            revision_directory_name(selected),
            tuple(artifacts),
        )
'''
    text = replace_once(text, old, new, "revision build artifacts")
    write(path, text)


def update_cli() -> None:
    path = "src/sci_manuscript/cli.py"
    text = read(path)
    text = replace_once(
        text,
        '("build", "Compile a clean manuscript."),\n',
        '("build", "Compile clean output and a marked PDF for revisions."),\n',
        "CLI build help",
    )
    write(path, text)


def update_tests() -> None:
    core_path = "tests/test_core.py"
    core = read(core_path)
    core += r'''


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
'''
    write(core_path, core)

    integration_path = "tests/test_release_integration.py"
    integration = read(integration_path)
    integration += r'''


def test_chinese_review_scope_marks_only_changed_abstract_text_and_build_keeps_marked(
    tmp_path: Path,
) -> None:
    """A review wrapper is provenance scope; unchanged abstract text stays unmarked."""
    _require_toolchain()
    project_dir = tmp_path / "Chinese reviewer diff project"
    initialize_manuscript(
        project_dir,
        title="审稿修改语义测试",
        journal="科学通报",
        publisher="chinese",
        language="zh",
        article_type="观点",
        first_authors=("author_one",),
        corresponding_authors=("author_two",),
        authors_path=_author_library(tmp_path / "review_authors.yaml"),
        engine="tectonic",
    )
    manuscript = project_dir / "manuscript"
    initial = manuscript / "initial_submission"
    frontmatter = initial / "sections" / "00_frontmatter.tex"
    frontmatter.write_text(
        r"""\cnabstract{第一句保持不变。第二句使用旧表述。}
\cnkeywords{结构化对象；初稿}
\enabstract{The first sentence is unchanged. The second sentence uses old wording.}
\enkeywords{structured object; original}
""",
        encoding="utf-8",
    )
    body = initial / "sections" / "01_manuscript.tex"
    body.write_text("原有正文。\n", encoding="utf-8")
    project = ManuscriptProject(manuscript)
    project.start_revision(
        reviews=_review_file(tmp_path / "reviews_abstract.md", 1), confirmed=True
    )
    revision = manuscript / "revision_01"
    (revision / "sections" / "00_frontmatter.tex").write_text(
        r"""\cnabstract{\review{1-1}{第一句保持不变。第二句使用新表述。}}
\cnkeywords{结构化对象；初稿}
\enabstract{The first sentence is unchanged. The second sentence uses old wording.}
\enkeywords{structured object; original}
""",
        encoding="utf-8",
    )
    (revision / "sections" / "01_manuscript.tex").write_text(
        "原有正文。\n作者自行增加一句。\n",
        encoding="utf-8",
    )

    result = project.build(engine="tectonic", keep_temp=True)
    assert {artifact.label for artifact in result.artifacts} == {
        "Clean manuscript",
        "Marked manuscript",
    }
    marked = revision / "output" / "manuscript_marked.pdf"
    assert marked.is_file()
    retained_runs = list((manuscript / "tmp").glob("run_*"))
    assert len(retained_runs) == 1
    marked_source = (
        retained_runs[0] / "marked_source" / "manuscript_marked.tex"
    ).read_text(encoding="utf-8")
    assert r"\sciReviewStart{1-1}" in marked_source
    assert r"\DIFaddReview{" in marked_source
    assert r"\DIFdel{" in marked_source
    assert "第一句保持不变。" in marked_source
    assert r"\DIFaddReview{第一句保持不变。" not in marked_source
    _assert_provenance_colors(marked, tmp_path / "rendered_abstract_review")
    shutil.rmtree(manuscript / "tmp")
'''
    write(integration_path, integration)


def update_docs_and_version() -> None:
    path = "SKILL.md"
    text = read(path)
    text = replace_once(
        text,
        "| Build | Run `build`; do not change TeX or create a revision |",
        "| Build | Run `build`; r00 retains clean output, while revision rounds retain both clean and adjacent marked PDFs; do not change TeX or create a revision |",
        "SKILL build route",
    )
    text = replace_once(
        text,
        "- `\\review{ID}{text}` is the only manual provenance wrapper for new work.\n"
        "  Ordinary additions and deletions are detected by adjacent `latexdiff`;\n"
        "  legacy `\\user{text}` remains readable but should not be added.\n",
        "- `\\review{ID}{text}` is the only manual reviewer-provenance scope for new\n"
        "  work. The wrapper itself is visually transparent: adjacent `latexdiff`\n"
        "  determines the actual changed spans, only additions inside that scope are\n"
        "  rendered as reviewer-linked green changes, and unchanged text inside the\n"
        "  scope remains ordinary manuscript text. Deletions remain red everywhere;\n"
        "  additions outside the scope remain author-blue. Legacy `\\user{text}`\n"
        "  remains readable but should not be added.\n",
        "SKILL review invariant",
    )
    text = replace_once(
        text,
        "Automatic revision provenance uses three non-overlapping conventions: ordinary\n"
        "author additions detected by latexdiff are blue with a wave underline,\n"
        "deletions are red with strikeout, and reviewer-linked `\\review{}` additions are\n"
        "green with a straight underline. In Chinese marked manuscripts, all three line\n",
        "Automatic revision provenance uses three non-overlapping conventions: ordinary\n"
        "author additions detected by latexdiff are blue with a wave underline,\n"
        "deletions are red with strikeout, and actual latexdiff additions occurring\n"
        "inside reviewer-linked `\\review{}` scopes are green with a straight underline.\n"
        "Text that is unchanged relative to the direct parent remains unmarked even when\n"
        "it is enclosed by `\\review{}`. In Chinese marked manuscripts, all three line\n",
        "SKILL provenance semantics",
    )
    write(path, text)

    path = "README.md"
    text = read(path)
    text = replace_once(
        text,
        "reviewer-linked text uses a green straight underline.\n",
        "only actual additions inside reviewer-linked `\\review{}` scopes use a green\n"
        "straight underline; unchanged text inside the scope remains unmarked.\n",
        "README provenance summary",
    )
    text = replace_once(
        text,
        "| `build` | Compile one clean manuscript without changing sources |",
        "| `build` | Compile clean output; revision rounds also retain the adjacent marked PDF |",
        "README build table",
    )
    text = replace_once(
        text,
        "clean = project.build()\n",
        "build = project.build()\n",
        "README API example",
    )
    write(path, text)

    path = "pyproject.toml"
    text = read(path)
    text = replace_once(text, 'version = "1.0.0"', 'version = "1.1.0"', "version")
    write(path, text)


def update_self_cleanup() -> None:
    for relative in (
        "tools/apply_revision_semantics.py",
        ".github/workflows/apply-revision-semantics.yml",
    ):
        path = ROOT / relative
        if path.exists():
            path.unlink()
    tools = ROOT / "tools"
    if tools.exists() and not any(tools.iterdir()):
        tools.rmdir()


def main() -> None:
    update_diff()
    update_api()
    update_cli()
    update_tests()
    update_docs_and_version()
    update_self_cleanup()


if __name__ == "__main__":
    main()
