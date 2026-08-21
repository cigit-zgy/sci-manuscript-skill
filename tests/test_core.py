"""Behavioral tests for the scientific-manuscript lifecycle."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import yaml

from sci_manuscript import Artifact
from sci_manuscript import cli as lifecycle_run
from sci_manuscript._runtime import diff, metadata, response, workspace
from sci_manuscript._runtime.resources import load_revision_contract

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "src" / "sci_manuscript" / "resources"


def _metadata(publisher: str = "elsevier") -> metadata.ManuscriptMetadata:
    return metadata.ManuscriptMetadata(
        title="Lifecycle Test",
        article_type="Research Paper",
        language="en",
        journal_name="Example Journal",
        publisher=publisher,
        journal_template=metadata.PUBLISHER_TEMPLATES[publisher],
        round_number=0,
        parent_round=None,
        submission=metadata.SubmissionSettings(True, True, True),
        first_authors=("Guangyao Zhao", "Fengjun Yin"),
        corresponding_authors=("Di Wu", "Hong Liu"),
        authors=("Cheng Song",),
    )


def _config(project: Path, publisher: str = "elsevier") -> workspace.ProjectConfig:
    return workspace.ProjectConfig(project, _metadata(publisher))


class MetadataTest(unittest.TestCase):
    """Verify round configuration and shared author-library behavior."""

    def test_round_trip_and_shared_author_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            config = workspace.initialize_project(_config(project))
            initial = project / "initial_submission"
            loaded = metadata.load_manuscript(initial / "manuscript.yaml")
            selection = metadata.generate_author_metadata(project, initial)
            generated = (project / "references" / "author_metadata.tex").read_text(
                encoding="utf-8"
            )
            self.assertEqual(loaded, config.metadata)
            self.assertEqual(
                tuple(author.name for author in selection.first_authors),
                ("Guangyao Zhao", "Fengjun Yin"),
            )
            self.assertEqual(
                tuple(author.name for author in selection.corresponding_authors),
                ("Di Wu", "Hong Liu"),
            )
            self.assertIn("wd@cigit.ac.cn", generated)
            self.assertIn("liuhong@cigit.ac.cn", generated)
            yaml_text = (initial / "manuscript.yaml").read_text(encoding="utf-8")
            self.assertIn("name: initial_submission", yaml_text)
            self.assertIn("template: elsarticle", yaml_text)
            self.assertNotIn("email:", yaml_text)

    def test_unknown_selected_author_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            config = workspace.initialize_project(_config(project))
            invalid = replace(config.metadata, authors=("Missing Author",))
            initial = project / "initial_submission"
            metadata.save_manuscript(initial / "manuscript.yaml", invalid)
            with self.assertRaises(metadata.MetadataError):
                metadata.generate_author_metadata(project, initial)

    def test_email_is_optional_except_for_corresponding_authors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library_path = Path(temp) / "authors.yaml"
            library_path.write_text(
                """authors:
  Ordinary Author:
    name_en: Ordinary Author
    name_zh: 普通作者
    role: author
    affiliations: [1]
  Corresponding Author:
    name_en: Corresponding Author
    name_zh: 通讯作者
    role: corresponding_author
    affiliations: [1]
affiliations:
  1:
    name_en: Example Institute
    address: Example City
""",
                encoding="utf-8",
            )
            library = metadata.load_author_library(library_path)
            self.assertEqual(library.authors["Ordinary Author"].email, "")
            selected = replace(
                _metadata(),
                first_authors=("Ordinary Author",),
                corresponding_authors=("Corresponding Author",),
                authors=(),
            )
            with self.assertRaisesRegex(
                metadata.MetadataError,
                "Corresponding authors must have email addresses",
            ):
                metadata.resolve_authors(selected, library)

    def test_chinese_project_uses_chinese_author_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            chinese = replace(_metadata("chinese"), language="zh")
            config = workspace.initialize_project(
                workspace.ProjectConfig(project, chinese)
            )
            initial = config.round_dir(0)
            generated = (project / "references" / "publisher_metadata.tex").read_text(
                encoding="utf-8"
            )
            preamble = (initial / "preamble.tex").read_text(encoding="utf-8")
            self.assertIn("\\author{赵光耀", generated)
            self.assertIn("刘鸿", generated)
            self.assertIn("\\renewcommand{\\abstractname}{摘要}", preamble)


class InitializationTest(unittest.TestCase):
    """Verify nested initial submission and publisher adaptation."""

    def test_initializes_root_workspace_and_local_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            workspace.initialize_project(_config(project))
            for name in ("run.py", "references", "initial_submission", "tmp"):
                self.assertTrue((project / name).exists(), name)
            expected = (
                "manuscript.yaml",
                "manuscript.tex",
                "preamble.tex",
                "sections",
                "figures",
                "tables",
                "submission",
                "output",
            )
            initial = project / "initial_submission"
            for name in expected:
                self.assertTrue((initial / name).exists(), name)
            self.assertFalse((project / "manuscript.tex").exists())
            self.assertFalse((project / "sections").exists())
            self.assertFalse((project / "figures").exists())
            self.assertFalse((project / "output").exists())
            self.assertFalse((project / "manuscripts").exists())
            self.assertFalse((project / "submission").exists())
            self.assertFalse((initial / "references").exists())
            shared = project / "references"
            for name in (
                "authors.yaml",
                "references.bib",
                "revision_style.tex",
                "zotero_setup.md",
                "journal_templates",
                "author_metadata.tex",
                "publisher_metadata.tex",
            ):
                self.assertTrue((shared / name).exists(), name)
            entrypoint = (project / "run.py").read_text(encoding="utf-8")
            self.assertNotIn("SCI_MANUSCRIPT_SKILL_ROOT", entrypoint)
            self.assertNotIn(str(ROOT), entrypoint)

    def test_publisher_section_mappings_are_applied(self) -> None:
        expected = {
            "elsevier": "02_methods.tex",
            "nature": "04_methods.tex",
            "acs": "03_results_and_discussion.tex",
            "chinese": "02_methods.tex",
        }
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for publisher, filename in expected.items():
                project = base / publisher
                workspace.initialize_project(_config(project, publisher))
                initial = project / "initial_submission"
                self.assertTrue((initial / "sections" / filename).exists())
                manuscript = (initial / "manuscript.tex").read_text(encoding="utf-8")
                self.assertIn(Path(filename).stem, manuscript)
                class_name = metadata.PUBLISHER_TEMPLATES[publisher]
                self.assertIn(
                    f"../references/journal_templates/{publisher}/{class_name}",
                    manuscript,
                )

    def test_refuses_reinitialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            config = workspace.initialize_project(_config(project))
            with self.assertRaises(workspace.WorkflowError):
                workspace.initialize_project(config)


class RevisionChainTest(unittest.TestCase):
    """Verify adjacent semantic revisions and inherited provenance cleanup."""

    def test_r0_to_r1_to_r2_uses_semantic_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            r0 = workspace.initialize_project(_config(project))
            with workspace.temporary_run(project, keep=False) as run_dir:
                r1 = workspace.start_revision(r0, 1, run_dir)
            r1_intro = r1.round_dir(1) / "sections" / "01_introduction.tex"
            r1_intro.write_text(
                "\\section{Introduction}\n\\review{1-1}{R1 revised text.}\n",
                encoding="utf-8",
            )
            with workspace.temporary_run(project, keep=False) as run_dir:
                r2 = workspace.start_revision(r1, 2, run_dir)
            r2_intro = (r2.round_dir(2) / "sections" / "01_introduction.tex").read_text(
                encoding="utf-8"
            )
            self.assertIn("R1 revised text.", r2_intro)
            self.assertNotIn("\\review", r2_intro)
            self.assertEqual(r2.metadata.parent_round, 1)
            self.assertTrue((project / "references" / "references.bib").exists())
            self.assertTrue((project / "references" / "authors.yaml").exists())
            self.assertFalse((r1.round_dir(1) / "references").exists())
            self.assertFalse((r2.round_dir(2) / "references").exists())
            self.assertFalse((project / "revision_0").exists())
            self.assertFalse(any((project / "tmp").iterdir()))

    def test_rejects_r0_to_r2(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            config = workspace.initialize_project(_config(project))
            with workspace.temporary_run(project, keep=False) as run_dir:
                with self.assertRaises(workspace.WorkflowError):
                    workspace.start_revision(config, 2, run_dir)


class SubmissionTest(unittest.TestCase):
    """Verify on-demand submission sources stay inside one version."""

    def test_submission_workspace_is_version_local_and_non_destructive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            config = workspace.initialize_project(_config(project))
            submission = workspace.ensure_submission_workspace(config, 0)
            self.assertEqual(submission, project / "initial_submission" / "submission")
            self.assertTrue((submission / "cover_letter.tex").exists())
            self.assertTrue((submission / "highlights.tex").exists())
            self.assertTrue((submission / "graphical_abstract").is_dir())
            cover = submission / "cover_letter.tex"
            cover.write_text("USER EDIT\n", encoding="utf-8")
            workspace.ensure_submission_workspace(config, 0)
            self.assertEqual(cover.read_text(encoding="utf-8"), "USER EDIT\n")


class BibliographyTest(unittest.TestCase):
    """Verify optional Better BibTeX synchronization is explicit and atomic."""

    def test_explicit_export_replaces_shared_bibliography(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "project"
            workspace.initialize_project(_config(project))
            export = Path(temp) / "zotero.bib"
            export.write_text("@article{test, title={Test}}\n", encoding="utf-8")
            targets = workspace.sync_bibliography(project, export)
            self.assertEqual(len(targets), 1)
            self.assertEqual(targets[0].read_text(encoding="utf-8"), export.read_text())


class ResponseTest(unittest.TestCase):
    """Verify reviewer parsing and unfinished-response detection."""

    def test_general_comment_has_no_response_id(self) -> None:
        text = """# Reviewer #1

General assessment.

1. First comment.

2. Second comment.
"""
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reviews.md"
            path.write_text(text, encoding="utf-8")
            blocks = response.parse_reviews(path)
        self.assertEqual(blocks[0].general_comment, "General assessment.")
        self.assertEqual(
            [comment.review_id for comment in blocks[0].comments],
            ["1-1", "1-2"],
        )

    def test_placeholder_definition_is_not_counted(self) -> None:
        source_text = "\\newcommand{\\ResponsePending}[1]{pending #1}\nCompleted.\n"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "response.tex"
            source.write_text(source_text, encoding="utf-8")
            self.assertEqual(response.pending_response_ids(source), ())
            source.write_text(
                source_text + "\\ResponsePending{1-1}\n", encoding="utf-8"
            )
            self.assertEqual(response.pending_response_ids(source), ("1-1",))

    def test_english_response_starts_with_reviewer_salutation(self) -> None:
        template = (RESOURCES / "response" / "response_en.tex").read_text(
            encoding="utf-8"
        )
        body = template.split("\\begin{document}", 1)[1].lstrip()
        self.assertTrue(body.startswith("Dear Reviewer,"))
        self.assertNotIn("Response to Reviewers", template)
        self.assertNotIn("Revision round", template)


class InterfaceTest(unittest.TestCase):
    """Verify public subcommands and user-style/runtime separation."""

    def test_explicit_subcommands_are_available(self) -> None:
        parser = lifecycle_run.build_parser()
        for command in (
            "doctor",
            "init",
            "build",
            "revision",
            "submission",
            "all",
            "setup-zotero",
            "sync-bib",
            "check",
            "status",
            "upgrade-project",
        ):
            arguments = [command]
            if command == "init":
                arguments.extend(
                    [
                        "--title",
                        "Test",
                        "--journal",
                        "Journal",
                        "--publisher",
                        "elsevier",
                    ]
                )
            self.assertEqual(parser.parse_args(arguments).command, command)

    def test_generated_wrapper_reports_missing_package_without_traceback(self) -> None:
        wrapper = RESOURCES / "project_run.py"
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(wrapper), "doctor"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not installed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_revision_style_contains_only_user_settings(self) -> None:
        style = (RESOURCES / "revision_style.tex").read_text(encoding="utf-8")
        self.assertNotIn("ReviewLocationFile", style)
        self.assertNotIn("DIFadd", style)
        self.assertNotIn("\\uwave", style)
        self.assertNotIn("\\sout", style)
        self.assertIn("% Equation handling", style)
        self.assertIn("% Long text handling", style)
        self.assertIn("\\RevisionAddedText", style)
        self.assertIn("\\RevisionDeletedText", style)
        self.assertIn("ReviewLocationFile", diff.REVISION_RUNTIME)

    def test_revision_contract_is_restricted_and_routed(self) -> None:
        contract_path = ROOT / "references" / "revision_contract.yaml"
        packaged_path = RESOURCES / "revision_contract.yaml"
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        packaged = yaml.safe_load(packaged_path.read_text(encoding="utf-8"))
        self.assertEqual(contract, packaged)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertEqual(
            contract["revision"]["default_permission"],
            "no_content_edit",
        )
        self.assertIn("scientific_content_change", contract["forbidden_operations"])
        self.assertIn("new_claim", contract["require_confirmation"])
        self.assertIn("Agent MUST NOT autonomously modify", skill)
        self.assertNotIn("concrete change directly required", skill)
        self.assertIn("references/revision_contract.yaml", skill)

    def test_revision_contract_is_enforced_by_the_runtime(self) -> None:
        loaded = load_revision_contract()
        revision = loaded["revision"]
        assert isinstance(revision, dict)
        self.assertEqual(revision["default_permission"], "no_content_edit")
        allowed = loaded["allowed_operations"]
        assert isinstance(allowed, list)
        self.assertIn("user_supplied_exact_text_replacement", allowed)
        forbidden = loaded["forbidden_operations"]
        assert isinstance(forbidden, list)
        for operation in (
            "scientific_content_change",
            "paragraph_rewrite",
            "section_restructure",
            "novelty_change",
            "interpretation_change",
            "unsupported_addition",
        ):
            self.assertIn(operation, forbidden)
        self.assertIn(
            "load_revision_contract",
            (ROOT / "src" / "sci_manuscript" / "_workflow.py").read_text(
                encoding="utf-8"
            ),
        )

    def test_latexdiff_uses_layout_safe_options(self) -> None:
        self.assertIn("--math-markup=whole", diff.LATEXDIFF_SAFE_OPTIONS)
        self.assertIn("--graphics-markup=none", diff.LATEXDIFF_SAFE_OPTIONS)
        self.assertIn(
            "--config=MAXCHANGESLETTER=0",
            diff.LATEXDIFF_SAFE_OPTIONS,
        )

    def test_generated_file_report_lists_complete_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            clean = project / "revision_1" / "output" / "manuscript_clean.pdf"
            cover = (
                project / "revision_1" / "submission" / "package" / "cover_letter.pdf"
            )
            package = cover.parent
            clean.parent.mkdir(parents=True)
            package.mkdir(parents=True)
            clean.touch()
            cover.touch()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                lifecycle_run._report_artifacts(
                    "Submission completed",
                    "revision_1",
                    project,
                    (
                        Artifact("Clean manuscript", clean),
                        Artifact("Cover letter", cover),
                        Artifact("Submission package", package),
                    ),
                )
        report = output.getvalue()
        self.assertIn("Generated:", report)
        self.assertIn("revision_1/output/manuscript_clean.pdf", report)
        self.assertIn(
            "revision_1/submission/package/cover_letter.pdf",
            report,
        )
        self.assertIn("revision_1/submission/package/", report)

    def test_config_directory_is_absent(self) -> None:
        self.assertFalse((ROOT / "config").exists())


class LocationTest(unittest.TestCase):
    """Verify continuous-line location prose and provenance denesting."""

    def test_location_joining(self) -> None:
        self.assertEqual(diff._format_location(4, 4), "Line 4")
        self.assertEqual(diff._format_location(4, 7), "Lines 4--7")
        self.assertEqual(
            diff._join_locations(["Line 4", "Lines 7--8"]),
            "Line 4 and Lines 7--8",
        )

    def test_reviewer_wrapper_is_not_nested_inside_diff_addition(self) -> None:
        nested = r"\DIFadd{\review{1-1}{Revised text.}}"
        self.assertEqual(
            diff._denest_provenance(nested),
            r"\review{1-1}{Revised text.}",
        )


if __name__ == "__main__":
    unittest.main()
