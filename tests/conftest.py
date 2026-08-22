from __future__ import annotations
from pathlib import Path
import pytest
from sci_manuscript.api import initialize_manuscript

@pytest.fixture
def project(tmp_path: Path):
    root=tmp_path/'paper'
    initialize_manuscript(root,'Test Manuscript','Test Journal','elsevier')
    return root
