import pytest
from sci_manuscript.domain.revision import RevisionChain, parse_round, round_directory_name, round_name
from sci_manuscript.exceptions import WorkflowError

def test_round_name_two_digit(): assert round_name(1)=='r01'
def test_round_name_ten(): assert round_name(10)=='r10'
def test_directory_zero(): assert round_directory_name(0)=='initial_submission'
def test_directory_one(): assert round_directory_name(1)=='revision_01'
def test_parse_canonical(): assert parse_round('r02')==2
def test_parse_legacy_round(): assert parse_round('r2')==2
def test_parse_legacy_dir(): assert parse_round('revision_2')==2
def test_parse_initial(): assert parse_round('initial_submission')==0
def test_negative_rejected():
    with pytest.raises(WorkflowError): round_name(-1)
def test_chain_gap_free(): assert not RevisionChain((0,1,2)).broken
def test_chain_broken(): assert RevisionChain((0,2)).broken
def test_chain_next(): assert RevisionChain((0,1)).next_round()==2
def test_chain_next_rejects_gap():
    with pytest.raises(WorkflowError): RevisionChain((0,2)).next_round()
