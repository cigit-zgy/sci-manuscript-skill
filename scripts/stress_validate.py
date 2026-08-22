"""Deterministic lifecycle stress validation without LaTeX compilation."""
from __future__ import annotations
import argparse
import shutil
import tempfile
from pathlib import Path
from sci_manuscript.api import ManuscriptProject, initialize_manuscript
from sci_manuscript.exceptions import WorkflowError
from sci_manuscript.infrastructure.hashing import source_hashes
from sci_manuscript.workflow.reindex import execute_reindex

def run(cycles: int) -> None:
    for cycle in range(cycles):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'paper'
            initialize_manuscript(root,f'Title {cycle}','Journal','elsevier')
            p=ManuscriptProject(root)
            p.start_revision(); p.start_revision(); p.start_revision()
            # Rollback refusal on an edited latest round.
            edited=root/'revision_03/sections/01_introduction.tex'
            edited.write_text(edited.read_text()+f'\ncycle {cycle}\n',encoding='utf-8')
            try:
                p.remove_latest_revision()
            except WorkflowError:
                pass
            else:
                raise AssertionError('rollback accepted edited user source')
            # Remove the edited latest round manually to create a safe test baseline.
            shutil.rmtree(root/'revision_03')
            # Break the chain in the middle and verify transaction repair.
            before=source_hashes(root/'revision_02'); before.pop('manuscript.yaml',None)
            shutil.rmtree(root/'revision_01')
            if cycle % 7 == 0:
                snapshot=sorted(x.name for x in root.iterdir() if x.is_dir())
                try:
                    execute_reindex(root,fault_after=2)
                except OSError:
                    pass
                else:
                    raise AssertionError('fault injection did not fail')
                assert sorted(x.name for x in root.iterdir() if x.is_dir())==snapshot
            p.reindex()
            after=source_hashes(root/'revision_01'); after.pop('manuscript.yaml',None)
            assert before==after
            assert p.status().round_number==1 and not p.status().broken
            # Add and rollback one untouched adjacent revision.
            p.start_revision(); assert p.status().round_number==2
            p.remove_latest_revision(); assert p.status().round_number==1

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--cycles',type=int,default=100); args=ap.parse_args()
    run(args.cycles); print(f'stress validation passed: {args.cycles} cycles'); return 0
if __name__=='__main__': raise SystemExit(main())
