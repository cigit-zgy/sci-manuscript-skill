\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{kxtbcas}[2026/03/08 CASAD-style journal template]

\newif\ifkxtb@review
\DeclareOption{review}{\kxtb@reviewtrue}
\DeclareOption{final}{\kxtb@reviewfalse}
\ExecuteOptions{final}
\ProcessOptions\relax

\LoadClass[a4paper,10pt]{article}

\RequirePackage{iftex}
\ifXeTeX\else
  \ClassError{kxtbcas}{This class requires XeLaTeX}{Please compile with XeLaTeX.}
\fi

\RequirePackage{geometry}
\ifkxtb@review
  \geometry{top=2.5cm,bottom=2.5cm,left=2.5cm,right=2.5cm}
\else
  \geometry{top=1.8cm,bottom=2.1cm,left=1.55cm,right=1.55cm,columnsep=6.5mm}
\fi

\RequirePackage{fontspec}
\RequirePackage{xeCJK}
\RequirePackage{unicode-math}
\RequirePackage{setspace}
\RequirePackage{titlesec}
\RequirePackage{graphicx}
\RequirePackage{caption}
\RequirePackage{subcaption}
\RequirePackage{booktabs}
\RequirePackage{multirow}
\RequirePackage{array}
\RequirePackage{tabularx}
\RequirePackage{threeparttable}
\RequirePackage{makecell}
\RequirePackage{enumitem}
\RequirePackage{etoolbox}
\RequirePackage[numbers,sort&compress]{natbib}
\RequirePackage{hyperref}
\RequirePackage{dblfloatfix}
\RequirePackage{lineno}
\RequirePackage{xcolor}

% Chinese journal default layout settings.
% Managed by sci-manuscript-skill.
% Do not duplicate these settings in manuscript.tex.
\setlength{\parindent}{2em}
\hypersetup{
  colorlinks=true,
  linkcolor=blue,
  citecolor=blue,
  urlcolor=blue,
  filecolor=blue,
  pdfborder={0 0 0},
  pdfcreator={},
  pdfproducer={}
}
\setcitestyle{numbers,square,comma,sort&compress}
\defaultfontfeatures{Ligatures=TeX,Scale=MatchLowercase}

\makeatletter

% Portable bundled default: use local files when supplied, otherwise fall back
% to the system font names declared below.
\def\kxtb@latinfontpath{./}
\def\kxtb@cjkfontpath{./}
\def\kxtb@latinfont@upright{TimesNewRoman-Regular.ttf}
\def\kxtb@latinfont@bold{TimesNewRoman-Bold.ttf}
\def\kxtb@latinfont@italic{TimesNewRoman-Italic.ttf}
\def\kxtb@latinfont@bolditalic{TimesNewRoman-BoldItalic.ttf}
\def\kxtb@cjkfont@upright{SimSun.ttf}
\def\kxtb@cjkfont@bold{SimSun-Bold.ttf}
\def\kxtb@cjkfont@italic{SimSun.ttf}
\def\kxtb@mathfont{STIX Two Math}

\def\kxtb@latinfallback@main{Times New Roman}
\def\kxtb@latinfallback@mainalt{TeX Gyre Termes}
\def\kxtb@latinfallback@sans{Times New Roman}
\def\kxtb@latinfallback@sansalt{TeX Gyre Termes}
\def\kxtb@cjkfallback@main{Songti SC}
\def\kxtb@cjkfallback@mainalt{STSong}
\def\kxtb@cjkfallback@sans{Heiti SC}
\def\kxtb@cjkfallback@sansalt{STHeiti}

\newcommand{\kxtbsetfontroot}[1]{%
  \gdef\kxtb@latinfontpath{#1}%
  \gdef\kxtb@cjkfontpath{#1}%
}
\newcommand{\kxtbsetlatinfontpath}[1]{\gdef\kxtb@latinfontpath{#1}}
\newcommand{\kxtbsetcjkfontpath}[1]{\gdef\kxtb@cjkfontpath{#1}}
\newcommand{\kxtbsetlatinfontfiles}[4]{%
  \gdef\kxtb@latinfont@upright{#1}%
  \gdef\kxtb@latinfont@bold{#2}%
  \gdef\kxtb@latinfont@italic{#3}%
  \gdef\kxtb@latinfont@bolditalic{#4}%
}
\newcommand{\kxtbsetcjkfontfiles}[3]{%
  \gdef\kxtb@cjkfont@upright{#1}%
  \gdef\kxtb@cjkfont@bold{#2}%
  \gdef\kxtb@cjkfont@italic{#3}%
}
\newcommand{\kxtbsetmathfont}[1]{\gdef\kxtb@mathfont{#1}}

\newcommand{\kxtb@applylatinfonts}{%
  \IfFileExists{\kxtb@latinfontpath\kxtb@latinfont@upright}{%
    \setmainfont[
      Path=\kxtb@latinfontpath,
      UprightFont=\kxtb@latinfont@upright,
      BoldFont=\kxtb@latinfont@bold,
      ItalicFont=\kxtb@latinfont@italic,
      BoldItalicFont=\kxtb@latinfont@bolditalic
    ]{\kxtb@latinfont@upright}%
    \setsansfont[
      Path=\kxtb@latinfontpath,
      UprightFont=\kxtb@latinfont@upright,
      BoldFont=\kxtb@latinfont@bold,
      ItalicFont=\kxtb@latinfont@italic,
      BoldItalicFont=\kxtb@latinfont@bolditalic
    ]{\kxtb@latinfont@upright}%
  }{%
    \IfFontExistsTF{\kxtb@latinfallback@main}{%
      \setmainfont{\kxtb@latinfallback@main}%
      \setsansfont{\kxtb@latinfallback@main}%
    }{%
      \setmainfont{\kxtb@latinfallback@mainalt}%
      \IfFontExistsTF{\kxtb@latinfallback@sans}{%
        \setsansfont{\kxtb@latinfallback@sans}%
      }{%
        \setsansfont{\kxtb@latinfallback@sansalt}%
      }%
    }%
  }%
}

\newcommand{\kxtb@applycjkfonts}{%
  \IfFileExists{\kxtb@cjkfontpath\kxtb@cjkfont@upright}{%
    \setCJKmainfont[
      Path=\kxtb@cjkfontpath,
      UprightFont=\kxtb@cjkfont@upright,
      BoldFont=\kxtb@cjkfont@bold,
      ItalicFont=\kxtb@cjkfont@italic
    ]{\kxtb@cjkfont@upright}%
    \setCJKsansfont[
      Path=\kxtb@cjkfontpath,
      UprightFont=\kxtb@cjkfont@upright,
      BoldFont=\kxtb@cjkfont@bold,
      ItalicFont=\kxtb@cjkfont@italic
    ]{\kxtb@cjkfont@upright}%
  }{%
    \IfFontExistsTF{\kxtb@cjkfallback@main}{%
      \setCJKmainfont{\kxtb@cjkfallback@main}%
    }{%
      \setCJKmainfont{\kxtb@cjkfallback@mainalt}%
    }%
    \IfFontExistsTF{\kxtb@cjkfallback@sans}{%
      \setCJKsansfont{\kxtb@cjkfallback@sans}%
    }{%
      \setCJKsansfont{\kxtb@cjkfallback@sansalt}%
    }%
  }%
}

\newcommand{\kxtb@applymathfont}{%
  \ifstrempty{\kxtb@mathfont}{}{%
    \IfFontExistsTF{\kxtb@mathfont}{\setmathfont{\kxtb@mathfont}}{}%
  }%
}

\AtEndPreamble{%
  \kxtb@applylatinfonts
  \kxtb@applycjkfonts
  \kxtb@applymathfont
}

\setlength{\parskip}{0pt}
\setlength{\skip\footins}{6pt}
\setlength{\textfloatsep}{8pt plus 1pt minus 2pt}
\setlength{\floatsep}{6pt plus 1pt minus 2pt}
\setlength{\intextsep}{6pt plus 1pt minus 2pt}
\renewcommand{\baselinestretch}{1.05}
\setlist{nosep}
\pagestyle{plain}

\captionsetup{
  font=small,
  labelfont=normalfont,
  textfont=normalfont,
  labelsep=space,
  skip=2.4pt,
  aboveskip=2.4pt,
  belowskip=0pt,
  justification=raggedright,
  singlelinecheck=false
}
\captionsetup[figure]{name=图,position=bottom}
\captionsetup[table]{name=表,position=top}

\titleformat{\section}{\sffamily\bfseries\fontsize{14}{18}\selectfont}{\thesection}{0.6em}{}
\titleformat{\subsection}{\sffamily\bfseries\fontsize{12}{15}\selectfont}{\thesubsection}{0.6em}{}
\titlespacing*{\section}{0pt}{8pt plus 2pt minus 1pt}{4pt}
\titlespacing*{\subsection}{0pt}{6pt plus 2pt minus 1pt}{3pt}

\ifkxtb@review
  \AtBeginDocument{\fontsize{10.5}{12.6}\selectfont}
\fi

\AtBeginEnvironment{thebibliography}{%
  \fontsize{10}{12}\selectfont\setstretch{1.2}%
  % The class-level \doi command stores article metadata. Restrict the
  % bibliography meaning to visible, breakable DOI output so BibTeX entries are
  % not swallowed into \kxtb@doi and followed by an orphan full stop.
  \renewcommand{\doi}[1]{\href{https://doi.org/##1}{\nolinkurl{##1}}}%
}

\def\kxtb@entitle{}
\def\kxtb@enauthor{}
\def\kxtb@affiliation{}
\def\kxtb@enaffiliation{}
\def\kxtb@cnabstract{}
\def\kxtb@cnkeywords{}
\def\kxtb@enabstract{}
\def\kxtb@enkeywords{}
\def\kxtb@doi{}
\def\kxtb@citationline{}
\def\kxtb@received{}
\def\kxtb@revised{}
\def\kxtb@accepted{}
\def\kxtb@onlinepublished{}
\def\kxtb@funding{}
\def\kxtb@firstauthorcn{}
\def\kxtb@corrauthorcn{}
\def\kxtb@firstauthoren{}
\def\kxtb@corrauthoren{}
\def\kxtb@shorttitle{}
\def\kxtb@shortauthors{}

\newlength{\onehalfcolumnwidth}
\setlength{\onehalfcolumnwidth}{0.74\textwidth}

\newcommand{\entitle}[1]{\gdef\kxtb@entitle{#1}}
\newcommand{\enauthor}[1]{\gdef\kxtb@enauthor{#1}}
\newcommand{\affiliation}[1]{\gdef\kxtb@affiliation{#1}}
\newcommand{\enaffiliation}[1]{\gdef\kxtb@enaffiliation{#1}}
\newcommand{\cnabstract}[1]{\gdef\kxtb@cnabstract{#1}}
\newcommand{\cnkeywords}[1]{\gdef\kxtb@cnkeywords{#1}}
\newcommand{\enabstract}[1]{\gdef\kxtb@enabstract{#1}}
\newcommand{\enkeywords}[1]{\gdef\kxtb@enkeywords{#1}}
\RenewDocumentEnvironment{abstract}{+b}{\gdef\kxtb@cnabstract{#1}}{}
\NewDocumentEnvironment{englishabstract}{+b}{\gdef\kxtb@enabstract{#1}}{}
\newcommand{\keywords}[1]{\gdef\kxtb@cnkeywords{#1}}
\newcommand{\doi}[1]{\gdef\kxtb@doi{#1}}
\newcommand{\citationline}[1]{\gdef\kxtb@citationline{#1}}
\newcommand{\received}[1]{\gdef\kxtb@received{#1}}
\newcommand{\revised}[1]{\gdef\kxtb@revised{#1}}
\newcommand{\accepted}[1]{\gdef\kxtb@accepted{#1}}
\newcommand{\onlinepublished}[1]{\gdef\kxtb@onlinepublished{#1}}
\newcommand{\funding}[1]{\gdef\kxtb@funding{#1}}
\newcommand{\firstauthorcn}[1]{\gdef\kxtb@firstauthorcn{#1}}
\newcommand{\corrauthorcn}[1]{\gdef\kxtb@corrauthorcn{#1}}
\newcommand{\firstauthoren}[1]{\gdef\kxtb@firstauthoren{#1}}
\newcommand{\corrauthoren}[1]{\gdef\kxtb@corrauthoren{#1}}
\newcommand{\shorttitle}[1]{\gdef\kxtb@shorttitle{#1}}
\newcommand{\shortauthors}[1]{\gdef\kxtb@shortauthors{#1}}

\newcommand{\firstauthorinfo}[1]{\firstauthorcn{#1}}
\newcommand{\corrauthorinfo}[1]{\corrauthorcn{#1}}
\newcommand{\firstemail}[1]{\firstauthorcn{#1}\firstauthoren{#1}}
\newcommand{\corremail}[1]{\corrauthorcn{#1}\corrauthoren{#1}}

\newcommand{\kxtb@captionenname}[1]{%
  \ifcsstring{@captype}{table}{Table}{Figure}%
}
\newcommand{\bicaption}[2]{%
  \caption{#1\\[-0.35ex]{\footnotesize \kxtb@captionenname{\@captype}~\csname the\@captype\endcsname\ #2}}%
}

\newenvironment{singlecolumnfigure}[1][htbp]
{\begin{figure}[#1]\centering\begin{minipage}{\linewidth}\centering}
      {\end{minipage}\end{figure}}

\newenvironment{onehalfcolumnfigure}[1][t]
{\begin{figure*}[#1]\centering\begin{minipage}{\onehalfcolumnwidth}\centering}
      {\end{minipage}\end{figure*}}

\newenvironment{fullwidthfigure}[1][t]
{\begin{figure*}[#1]\centering}
    {\end{figure*}}

\newenvironment{singlecolumntable}[1][htbp]
{\begin{table}[#1]\centering\begin{minipage}{\linewidth}\centering}
      {\end{minipage}\end{table}}

\newenvironment{onehalfcolumntable}[1][t]
{\begin{table*}[#1]\centering\begin{minipage}{\onehalfcolumnwidth}\centering}
      {\end{minipage}\end{table*}}

\newenvironment{fullwidthtable}[1][t]
{\begin{table*}[#1]\centering}
    {\end{table*}}

\newcommand{\kxtb@metaentry}[2]{%
  \ifstrempty{#2}{}{\noindent\raggedright\textbf{#1}#2\par}%
}

\newcommand{\kxtb@datesline}{%
  \begingroup
  \footnotesize
  \ifstrempty{\kxtb@received}{}{\kxtb@received~收稿}%
  \ifstrempty{\kxtb@revised}{}{，\kxtb@revised~修回}%
  \ifstrempty{\kxtb@accepted}{}{，\kxtb@accepted~接受}%
  \ifstrempty{\kxtb@onlinepublished}{}{，\kxtb@onlinepublished~网络版发表}%
  \par
  \endgroup
}

\newcommand{\kxtb@frontmatter}{%
  \begingroup
  \parindent=0pt
  \begin{center}
    {\sffamily\bfseries\fontsize{16}{21}\selectfont \@title\par}
    \vspace{10pt}
    {\fontsize{12}{16}\selectfont \@author\par}
    \vspace{7pt}
    {\fontsize{10.5}{14}\selectfont \kxtb@affiliation\par}
  \end{center}
  \vspace{9pt}
  % \kxtb@datesline
  {\fontsize{10.5}{14}\selectfont
    \kxtb@metaentry{基金项目：}{\kxtb@funding~}
    \vspace{4pt}
    \kxtb@metaentry{第一作者：}{\kxtb@firstauthorcn}
    \vspace{4pt}
    \kxtb@metaentry{*通讯作者：}{\kxtb@corrauthorcn}
  }
  \vspace{10pt}
  {\fontsize{10.5}{13.65}\selectfont\setstretch{1.3}\textbf{摘要：}\kxtb@cnabstract\par}
  \vspace{6pt}
  {\fontsize{10.5}{13.65}\selectfont\setstretch{1.3}\textbf{关键词：}\kxtb@cnkeywords\par}
  \vspace{12pt}
  \endgroup
}

\renewcommand{\maketitle}{%
  \ifkxtb@review
    \onehalfspacing
    \linenumbers
    \kxtb@frontmatter
  \else
    \twocolumn[\kxtb@frontmatter]
  \fi
  \setcounter{footnote}{0}
}

\newenvironment{kxtbsummary}{%
  \clearpage
  \onecolumn
  \pagestyle{plain}
  \parindent=0pt
  \begin{center}
    {\bfseries\fontsize{14}{18}\selectfont English Summary\par}
    \vspace{10pt}
    {\bfseries\fontsize{16}{21}\selectfont \kxtb@entitle\par}
    \vspace{9pt}
    {\fontsize{12}{16}\selectfont \kxtb@enauthor\par}
    \vspace{6pt}
    {\fontsize{10.5}{14}\selectfont \kxtb@enaffiliation\par}
  \end{center}
  \ifstrempty{\kxtb@firstauthoren}{}{\vspace{6pt}{\fontsize{10}{13}\selectfont\raggedright First author: \kxtb@firstauthoren\par}}
  \ifstrempty{\kxtb@corrauthoren}{}{\vspace{4pt}{\fontsize{10}{13}\selectfont\raggedright * Corresponding author: \kxtb@corrauthoren\par}}
  \vspace{10pt}
  {\fontsize{10.5}{13.65}\selectfont\setstretch{1.3}\textbf{Abstract: }\kxtb@enabstract\par}
  \vspace{8pt}
  {\fontsize{10.5}{13.65}\selectfont\setstretch{1.3}\textbf{Keywords: }\kxtb@enkeywords\par}
  % \ifstrempty{\kxtb@doi}{}{\vspace{0.5em}{\small doi: \kxtb@doi\par}}
}{}

\newcommand{\kxtb@renderenglishsummary}{%
  \begin{kxtbsummary}
  \end{kxtbsummary}%
}

\newcommand{\makeenglishsummary}{%
  \ifstrempty{\kxtb@entitle}
    {\ifstrempty{\kxtb@enabstract}{}{\kxtb@renderenglishsummary}}
    {\kxtb@renderenglishsummary}%
}

\makeatother
