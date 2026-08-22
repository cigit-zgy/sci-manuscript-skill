from pathlib import Path
import shutil
import pytest
from sci_manuscript.api import ManuscriptProject
from sci_manuscript.workflow.reindex import execute_reindex
from sci_manuscript.infrastructure.hashing import source_hashes

def _broken(project: Path):
    p=ManuscriptProject(project); p.start_revision(); p.start_revision(); p.start_revision(); shutil.rmtree(project/'revision_01'); return p

def test_plan_broken(project: Path):
    p=_broken(project); plan=p.reindex_plan(); assert ('revision_02','revision_01') in plan.renames
def test_execute_reindex(project: Path):
    p=_broken(project); p.reindex(); assert (project/'revision_01').is_dir(); assert (project/'revision_02').is_dir(); assert not (project/'revision_03').exists()
def test_reindex_updates_metadata(project: Path):
    import yaml
    p=_broken(project); p.reindex(); data=yaml.safe_load((project/'revision_02/manuscript.yaml').read_text()); assert data['revision']['round']=='r02'; assert data['revision']['parent']=='revision_01'
def test_reindex_preserves_sources(project: Path):
    p=_broken(project); before=source_hashes(project/'revision_02'); p.reindex(); after=source_hashes(project/'revision_01'); before.pop('manuscript.yaml'); after.pop('manuscript.yaml'); assert before==after
def test_fault_injection_restores_tree(project: Path):
    _broken(project); before=sorted(x.name for x in project.iterdir() if x.is_dir())
    with pytest.raises(OSError): execute_reindex(project,fault_after=2)
    after=sorted(x.name for x in project.iterdir() if x.is_dir()); assert before==after; assert (project/'revision_02').is_dir(); assert not (project/'revision_01').exists()
def test_fault_second_phase_restores_tree(project: Path):
    _broken(project); before=sorted(x.name for x in project.iterdir() if x.is_dir())
    with pytest.raises(OSError): execute_reindex(project,fault_after=5)
    assert sorted(x.name for x in project.iterdir() if x.is_dir())==before
def test_already_ordered(project: Path):
    p=ManuscriptProject(project); result=p.reindex(); assert not result.applied and result.status=='already_ordered'
