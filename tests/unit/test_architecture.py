from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def _defs(name: str):
    hits=[]
    for p in (ROOT/'src'/'workflow').glob('*.py'):
        tree=ast.parse(p.read_text())
        if any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name for n in tree.body): hits.append(p.name)
    return hits

def test_no_nested_sci_manuscript_directory(): assert not (ROOT/'src'/'sci_manuscript').exists()
def test_revision_single_owner(): assert _defs('start_revision')==['revision.py']
def test_rollback_single_owner(): assert _defs('rollback_latest')==['rollback.py']
def test_reindex_single_owner(): assert _defs('execute_reindex')==['reindex.py']
def test_submission_single_owner(): assert _defs('prepare_submission')==['submission.py']
def test_initialize_single_owner(): assert _defs('initialize_manuscript')==['initialize.py']
def test_build_single_owner(): assert _defs('build_manuscript')==['build.py']
def test_workflow_files_reasonable_size():
    assert all(len(p.read_text().splitlines()) < 250 for p in (ROOT/'src'/'workflow').glob('*.py'))
def test_no_always_true_boolean_assertions():
    needle = 'or' + ' True'
    for p in (ROOT/'tests').rglob('test_*.py'):
        assert needle not in p.read_text()
def test_readme_images_equal_dimensions():
    from PIL import Image
    pa=ROOT/'docs/images/marked_manuscript.png'; pb=ROOT/'docs/images/response_letter.png'; a=Image.open(pa); b=Image.open(pb); assert a.size==b.size; assert pa.stat().st_size==pb.stat().st_size
