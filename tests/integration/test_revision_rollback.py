from pathlib import Path
import pytest
from sci_manuscript.api import ManuscriptProject
from sci_manuscript.exceptions import WorkflowError

def test_create_r01(project: Path):
    p=ManuscriptProject(project); r=p.start_revision(); assert r.version=='revision_01'; assert (project/'revision_01').is_dir()
def test_create_r02(project: Path):
    p=ManuscriptProject(project); p.start_revision(); p.start_revision(); assert p.status().round_number==2
def test_adjacent_requested_round(project: Path):
    p=ManuscriptProject(project)
    with pytest.raises(WorkflowError): p.start_revision(round=2)
def test_manifest_created(project: Path):
    p=ManuscriptProject(project); p.start_revision(); assert (project/'revision_01'/'.revision_creation.yaml').is_file()
def test_rollback_unchanged(project: Path):
    p=ManuscriptProject(project); p.start_revision(); assert p.rollback_plan().changed_files==(); p.remove_latest_revision(); assert p.status().round_number==0
def test_rollback_refuses_section_edit(project: Path):
    p=ManuscriptProject(project); p.start_revision(); f=project/'revision_01/sections/01_introduction.tex'; f.write_text(f.read_text()+'\nUser edit')
    assert 'sections/01_introduction.tex' in p.rollback_plan().changed_files
    with pytest.raises(WorkflowError): p.remove_latest_revision()
def test_rollback_refuses_response_edit(project: Path):
    p=ManuscriptProject(project); p.start_revision(); f=project/'revision_01/response/response_letter.tex'; f.write_text('Completed response')
    assert 'response/response_letter.tex' in p.rollback_plan().changed_files
def test_review_file_copied(project: Path, tmp_path: Path):
    review=tmp_path/'review.md'; review.write_text('# Reviewer #1\n\n1. Please clarify.\n')
    p=ManuscriptProject(project); p.start_revision(review); assert (project/'revision_01/response/reviewer_comments.md').read_text()==review.read_text()
