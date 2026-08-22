from pathlib import Path
from unittest.mock import patch
from sci_manuscript.cli import main
from sci_manuscript.api import ManuscriptProject

def test_cli_revision_default_no(project: Path):
    with patch('builtins.input',return_value='n'): assert main(['revision','--project',str(project)])==0
    assert not (project/'revision_01').exists()
def test_cli_revision_yes(project: Path):
    assert main(['revision','--project',str(project),'--yes'])==0; assert (project/'revision_01').exists()
def test_setup_zotero(project: Path):
    bib,guide=ManuscriptProject(project).setup_zotero(); assert bib.is_file() and guide.is_file()
def test_sync_bib(project: Path,tmp_path: Path):
    source=tmp_path/'x.bib'; source.write_text('@article{x,title={X}}'); target=ManuscriptProject(project).sync_bib(source); assert target.read_text()==source.read_text()
