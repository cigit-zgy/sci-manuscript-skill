"""Tests for strict marked-manuscript layout diagnostics."""
from sci_manuscript.latex.compile import overfull_warnings


def test_overfull_warnings_detect_horizontal_and_vertical_boxes() -> None:
    log = """Normal line
Overfull \\hbox (21.68808pt too wide) in paragraph at lines 91--91
Overfull \\vbox (3.0pt too high) has occurred while \\output is active
"""
    warnings = overfull_warnings(log)
    assert len(warnings) == 2
    assert "hbox" in warnings[0]
    assert "vbox" in warnings[1]


def test_overfull_warnings_accept_clean_log() -> None:
    assert overfull_warnings("Output written on manuscript.pdf") == ()
