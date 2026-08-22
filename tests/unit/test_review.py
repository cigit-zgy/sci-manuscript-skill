from pathlib import Path
import pytest
from sci_manuscript.domain.review import parse_reviews
from sci_manuscript.exceptions import WorkflowError

def test_parse_review(tmp_path: Path):
    p=tmp_path/'r.md'; p.write_text('# Reviewer #2\n\n1. First\n\n2. Second\n')
    c=parse_reviews(p); assert [x.owner for x in c]==['2','2']; assert [x.number for x in c]==[1,2]
def test_parse_editor(tmp_path: Path):
    p=tmp_path/'r.md'; p.write_text('# Editor\n\n1. Comment\n'); assert parse_reviews(p)[0].owner=='E'
def test_nonconsecutive_rejected(tmp_path: Path):
    p=tmp_path/'r.md'; p.write_text('# Reviewer #1\n\n2. Bad\n')
    with pytest.raises(WorkflowError): parse_reviews(p)
def test_text_before_heading_rejected(tmp_path: Path):
    p=tmp_path/'r.md'; p.write_text('oops\n# Reviewer #1\n1. X\n')
    with pytest.raises(WorkflowError): parse_reviews(p)
def test_missing_review_rejected(tmp_path: Path):
    with pytest.raises(WorkflowError): parse_reviews(tmp_path/'missing.md')
