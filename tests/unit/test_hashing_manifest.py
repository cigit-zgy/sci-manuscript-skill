from pathlib import Path
from sci_manuscript.infrastructure.hashing import source_hashes
from sci_manuscript.infrastructure.manifest import write_creation_manifest, load_creation_manifest

def test_hash_sections(project: Path):
    h=source_hashes(project/'initial_submission'); assert 'sections/01_introduction.tex' in h
def test_generated_package_ignored(project: Path):
    p=project/'initial_submission'/'submission'/'package'; p.mkdir(parents=True); (p/'x.pdf').write_bytes(b'x')
    assert 'submission/package/x.pdf' not in source_hashes(project/'initial_submission')
def test_manifest_roundtrip(project: Path):
    d=project/'initial_submission'; write_creation_manifest(d,'none'); data=load_creation_manifest(d); assert data['parent']=='none'
