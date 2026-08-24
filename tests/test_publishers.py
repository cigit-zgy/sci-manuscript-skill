"""Compile bundled publisher and Chinese journal template resources."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_ASSETS = ROOT / "src" / "sci_manuscript" / "resources" / "journal_templates"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)
BIBLIOGRAPHY = """@article{template2026,
  author = {Reference Author},
  title = {Template Reference},
  journal = {Test Journal},
  year = {2026},
  volume = {1},
  pages = {1--2}
}
"""


class PublisherTemplateTest(unittest.TestCase):
    """Verify each bundled class with author, figure, and bibliography content."""

    tectonic: ClassVar[str | None]
    pdftotext: ClassVar[str | None]
    pdfimages: ClassVar[str | None]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tectonic = shutil.which("tectonic")
        cls.pdftotext = shutil.which("pdftotext")
        cls.pdfimages = shutil.which("pdfimages")
        if cls.tectonic is None or cls.pdftotext is None:
            raise unittest.SkipTest("tectonic and pdftotext are required")

    def _compile(
        self,
        publisher: str,
        source: str,
        resources: tuple[str, ...],
    ) -> str:
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            for name in resources:
                shutil.copy2(PUBLISHER_ASSETS / publisher / name, work / name)
            (work / "main.tex").write_text(source, encoding="utf-8")
            (work / "references.bib").write_text(BIBLIOGRAPHY, encoding="utf-8")
            (work / "figure.png").write_bytes(PNG_1X1)
            if publisher == "chinese":
                configured = os.environ.get("SCI_MANUSCRIPT_CJK_FONT_DIR")
                font_root = (
                    Path(configured).expanduser()
                    if configured
                    else Path.home() / "Library" / "Fonts"
                )
                names = (
                    "FandolSong-Regular.otf",
                    "FandolSong-Bold.otf",
                    "FandolKai-Regular.otf",
                )
                for name in names:
                    font = font_root / name
                    if font.is_file():
                        shutil.copy2(font, work / name)
                if all((work / name).is_file() for name in names):
                    font_configuration = (
                        "\\AtEndPreamble{"
                        "\\setCJKmainfont["
                        f"Path={{{work.as_posix()}/}}"
                        "]{FandolSong-Regular.otf}"
                        "}\n"
                    )
                    source = source.replace(
                        "\\documentclass[review]{kxtbcas}\n",
                        "\\documentclass[review]{kxtbcas}\n" + font_configuration,
                        1,
                    )
                    (work / "main.tex").write_text(source, encoding="utf-8")
            build = work / "build"
            build.mkdir()
            result = subprocess.run(
                [
                    self.tectonic or "tectonic",
                    "-X",
                    "compile",
                    f"--outdir={build}",
                    str(work / "main.tex"),
                ],
                cwd=work,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{publisher} compilation failed:\n{result.stdout}\n{result.stderr}",
            )
            pdf = build / "main.pdf"
            self.assertTrue(pdf.is_file(), publisher)
            extracted = subprocess.run(
                [self.pdftotext or "pdftotext", str(pdf), "-"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            ).stdout
            self.assertIn("Test Author", extracted)
            self.assertIn("template reference", extracted.lower())
            if self.pdfimages is not None:
                image_list = subprocess.run(
                    [self.pdfimages, "-list", str(pdf)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=True,
                ).stdout
                self.assertIn("image", image_list.lower())
            return extracted

    def test_elsevier_elsarticle(self) -> None:
        source = r"""
\documentclass{elsarticle}
\usepackage{graphicx}
\begin{document}
\begin{frontmatter}
\title{Elsevier Template Test}
\author[institute]{Test Author\corref{corresponding}}
\ead{test@example.org}
\cortext[corresponding]{Corresponding author}
\address[institute]{Example Research Institute}
\begin{abstract}Template compilation test.\end{abstract}
\end{frontmatter}
\section{Validation}
Figure~\ref{fig:test} and citation~\cite{template2026} are included.
\begin{figure}[htbp]
\centering
\includegraphics[width=10mm]{figure.png}
\caption{Template figure.}\label{fig:test}
\end{figure}
\bibliographystyle{elsarticle-num}
\bibliography{references}
\end{document}
"""
        self._compile(
            "elsevier",
            source,
            ("elsarticle.cls", "elsarticle-num.bst"),
        )

    def test_springer_nature_sn_jnl(self) -> None:
        source = r"""
\documentclass[pdflatex,sn-nature]{sn-jnl}
\usepackage{graphicx}
\usepackage{amsmath}
\begin{document}
\title[Template Test]{Springer Nature Template Test}
\author*[1]{\fnm{Test} \sur{Author}}\email{test@example.org}
\affil*[1]{\orgname{Example Research Institute}, \country{Example Country}}
\abstract{Template compilation test.}
\keywords{template, validation}
\maketitle
\section{Validation}
Figure~\ref{fig:test} and citation~\cite{template2026} are included.
\begin{figure}[htbp]
\centering
\includegraphics[width=10mm]{figure.png}
\caption{Template figure.}\label{fig:test}
\end{figure}
\bibliography{references}
\end{document}
"""
        self._compile(
            "nature",
            source,
            ("sn-jnl.cls", "sn-nature.bst"),
        )

    def test_acs_achemso(self) -> None:
        source = r"""
\documentclass[journal=esthag,manuscript=article]{achemso}
\title{ACS Template Test}
\author{Test Author}
\affiliation{Example Research Institute}
\email{test@example.org}
\begin{document}
\begin{abstract}Template compilation test.\end{abstract}
\section{Validation}
Figure~\ref{fig:test} and citation~\cite{template2026} are included.
\begin{figure}[htbp]
\centering
\includegraphics[width=10mm]{figure.png}
\caption{Template figure.}\label{fig:test}
\end{figure}
\bibliography{references}
\end{document}
"""
        self._compile("acs", source, ("achemso.cls",))

    def test_chinese_journal_kxtbcas(self) -> None:
        source = r"""
\documentclass[review]{kxtbcas}
\title{中文模板测试}
\entitle{Chinese Journal Template Test}
\author{Test Author$^{1,*}$}
\enauthor{Test Author$^{1,*}$}
\affiliation{$^{1}$示例研究机构}
\enaffiliation{$^{1}$Example Research Institute}
\begin{abstract}
本文仅用于模板编译验证。
\end{abstract}
\keywords{模板; 验证}
\begin{englishabstract}
Template compilation test.
\end{englishabstract}
\enkeywords{template; validation}
\corrauthorcn{Test Author, test@example.org}
\begin{document}
\maketitle
\section{验证}
图~\ref{fig:test}和文献\cite{template2026}用于编译测试。
\begin{figure}[htbp]
\centering
\includegraphics[width=10mm]{figure.png}
\bicaption{模板图片}{Template figure}\label{fig:test}
\end{figure}
\bibliographystyle{kxtbcas-numeric}
\bibliography{references}
\end{document}
"""
        self._compile("chinese", source, ("kxtbcas.cls", "kxtbcas-numeric.bst"))


if __name__ == "__main__":
    unittest.main()
