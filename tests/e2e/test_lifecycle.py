from pathlib import Path
import shutil
from unittest.mock import patch
from sci_manuscript.api import ManuscriptProject
from sci_manuscript.results import Artifact, BuildResult

def fake_build(project, round_number=None, engine='auto'):
    p=ManuscriptProject(project); number=p.status().round_number if round_number is None else round_number; rd=Path(project)/('initial_submission' if number==0 else f'revision_{number:02d}'); out=rd/'output'/('manuscript.pdf' if number==0 else 'manuscript_clean.pdf'); out.parent.mkdir(exist_ok=True); out.write_bytes(b'%PDF-1.4\n'); return BuildResult(Path(project), 'initial_submission' if number==0 else f'revision_{number:02d}', (Artifact('Clean manuscript',out),))

def test_r00_r01_r02_rollback(project: Path):
    p=ManuscriptProject(project); p.start_revision(); p.start_revision(); assert p.status().round_number==2; p.remove_latest_revision(); assert p.status().round_number==1
def test_broken_chain_repair(project: Path):
    p=ManuscriptProject(project); p.start_revision(); p.start_revision(); p.start_revision(); shutil.rmtree(project/'revision_02'); assert p.status().broken; p.reindex(); assert not p.status().broken and p.status().round_number==2
def test_submission_package_with_mock_build(project: Path):
    import sci_manuscript.workflow.submission as s
    with patch.object(s,'build_manuscript',fake_build):
        result=ManuscriptProject(project).prepare_submission(); assert (project/'initial_submission/submission/package/manuscript.pdf').is_file(); assert result.version=='initial_submission'
