import os
import shutil
import tempfile
import unittest

from bookformatter.cli import main as cli_main
from bookformatter.indesign import extract_link_assets
from bookformatter.latex import (LatexError, compile_pdf, escape,
                                 write_latex)
from bookformatter.models import Chapter
from tests import support

CHAPTER_ONE_HTML = (
    "<p>First chapter with an image.</p>"
    '<img src="images/img-abc.png" alt="pic" />'
    "<p>Then <em>emphatic <strong>and bold</strong></em> plus "
    "<strong>stark</strong> words.</p>"
    '<p>A cited claim<sup id="fnref:1"><a href="#fn:1">1</a></sup>'
    " continues onward.</p>"
    '<div class="footnotes"><ol><li id="fn:1"><p>The note text. '
    '<a href="#fnref:1">&#8617;</a></p></li></ol></div>'
)

CHAPTER_TWO_HTML = (
    "<p>Read <a href=\"https://example.com/ref\">the reference</a> today.</p>"
    "<blockquote><p>A quoted thought.</p></blockquote>"
    "<ul><li>alpha</li><li>beta<ul><li>nested</li></ul></li></ul>"
    "<ol><li>first</li><li>second</li></ol>"
    "<pre>code_block %raw&amp;\n\\end{verbatim}</pre>"
    "<table><tr><th>Name</th><th>Value</th></tr>"
    "<tr><td>a &amp; b</td><td>1</td></tr></table>"
    "<p>Specials: 50% #tag under_score {brace} ~tilde ^caret \\slash.</p>"
    "<hr />"
    "<p>Line<br />break.</p>"
)


# Leading "[" traps: after \item, and in a table's first column following
# \toprule and a row's \\ — all of which accept an optional [argument].
BRACKETS_HTML = (
    "<ul><li>[sic] an item</li></ul>"
    "<table><tr><td>[a]</td><td>x</td></tr>"
    "<tr><td>[b]</td><td>y</td></tr></table>"
)


def book():
    return support.make_book([
        Chapter(title="One & Only", html=CHAPTER_ONE_HTML),
        Chapter(title="Two", html=CHAPTER_TWO_HTML),
        Chapter(title="Three", html=BRACKETS_HTML),
    ])


def render(**kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "book.tex")
        write_latex(book(), path, **kwargs)
        with open(path, encoding="utf-8") as fh:
            return fh.read()


class EscapeTests(unittest.TestCase):
    def test_specials(self):
        self.assertEqual(escape("50% & #_{}"), r"50\% \& \#\_\{\}")
        self.assertEqual(escape("$x$"), r"\$x\$")
        self.assertEqual(escape("a~b^c"),
                         r"a\textasciitilde{}b\textasciicircum{}c")
        self.assertEqual(escape("a\\b"), r"a\textbackslash{}b")

    def test_unicode_passes_through(self):
        self.assertEqual(escape("café — “quotes”"), "café — “quotes”")


class WriteLatexTests(unittest.TestCase):
    def test_generic_document(self):
        tex = render()
        self.assertTrue(tex.startswith("% !TEX program = lualatex"))
        self.assertIn("\\documentclass[11pt,twoside,openright]{book}", tex)
        self.assertIn("paperwidth=6in,paperheight=9in", tex)
        self.assertIn("\\setmainfont{TeX Gyre Pagella}", tex)
        self.assertIn("\\usepackage{microtype}", tex)
        self.assertIn("\\chapter{One \\& Only}", tex)
        self.assertIn("\\tableofcontents", tex)
        # Title page and copyright carry the metadata, escaped.
        self.assertIn("{\\Huge Test \\& Book\\par}", tex)
        self.assertIn("Copyright © 2026 A. Author <tester>."
                      " All rights reserved.", tex)

    def test_body_conversion(self):
        tex = render()
        self.assertIn("\\emph{emphatic \\textbf{and bold}}", tex)
        self.assertIn("\\footnote{The note text.}", tex)
        self.assertIn("\\includegraphics[width=\\maxwidth]"
                      "{images/img-abc.png}", tex)
        self.assertIn("\\begin{quotation}\nA quoted thought."
                      "\n\\end{quotation}", tex)
        self.assertIn("\\item alpha", tex)
        self.assertIn("\\begin{itemize}\n\\item nested\n\\end{itemize}", tex)
        self.assertIn("\\begin{enumerate}\n\\item first\n"
                      "\\item second\n\\end{enumerate}", tex)
        self.assertIn("Specials: 50\\% \\#tag under\\_score \\{brace\\} "
                      "\\textasciitilde{}tilde \\textasciicircum{}caret "
                      "\\textbackslash{}slash.", tex)
        self.assertIn("\\begin{center}* * *\\end{center}", tex)
        self.assertIn("Line\\newline break.", tex)

    def test_verbatim_cannot_close_early(self):
        tex = render()
        self.assertIn("code_block %raw&", tex)
        self.assertIn("\\end{verbatim }", tex)  # the guarded content
        self.assertEqual(tex.count("\\end{verbatim}"), 1)

    def test_table_booktabs(self):
        tex = render()
        self.assertIn("\\begin{tabular}{ll}", tex)
        self.assertIn("Name & Value \\\\", tex)
        self.assertIn("\\midrule", tex)
        self.assertIn("a \\& b & 1 \\\\", tex)

    def test_link_notes_become_footnotes(self):
        tex = render()
        self.assertIn(
            "the reference\\footnote{\\href{https://example.com/ref}"
            "{https://example.com/ref}}", tex)

    def test_link_notes_off_keeps_hyperlink(self):
        tex = render(link_notes=False)
        self.assertIn("\\href{https://example.com/ref}{the reference}", tex)
        self.assertNotIn("reference\\footnote", tex)

    def test_classicthesis_uses_real_package(self):
        tex = render(theme="classicthesis")
        self.assertTrue(tex.startswith("% !TEX program = pdflatex"))
        self.assertIn("{scrreprt}", tex)
        self.assertIn("paper=a4,fontsize=11pt", tex)
        self.assertIn("{classicthesis}", tex)
        self.assertIn("\\spacedallcaps{Test \\& Book}", tex)
        self.assertIn("\\pagenumbering{arabic}", tex)
        self.assertNotIn("\\frontmatter", tex)
        # The genuine style already loads microtype and sets the leading.
        self.assertNotIn("\\usepackage{microtype}", tex)
        self.assertNotIn("\\linespread", tex)

    def test_classicthesis_trade_trim_gets_geometry(self):
        tex = render(theme="classicthesis", trim="6x9")
        self.assertIn("paper=a4", tex)  # class option stays canonical
        self.assertIn("paperwidth=6in,paperheight=9in", tex)

    def test_memoir_uses_real_class(self):
        tex = render(theme="memoir")
        self.assertTrue(tex.startswith("% !TEX program = pdflatex"))
        self.assertIn("\\documentclass[12pt,twoside,onecolumn,openright,"
                      "extrafontsizes]{memoir}", tex)
        # The template's stock, margins, face, and leading.
        self.assertIn("\\setstocksize{9in}{6in}", tex)
        self.assertIn("\\setlrmarginsandblock{0.75in}{0.625in}{*}", tex)
        self.assertIn("\\setulmarginsandblock{0.75in}{0.75in}{*}", tex)
        self.assertIn("\\usepackage{ebgaramond}", tex)
        self.assertIn("\\renewcommand{\\baselinestretch}{1.125}", tex)
        # Centered small-caps chapters, fancyhdr heads, symbol footnotes.
        self.assertIn("\\usepackage[center,sc]{titlesec}", tex)
        self.assertIn("\\fancyhead[LE,RO]{\\thepage}", tex)
        self.assertIn("\\fancyhead[CE]{\\itshape Test \\& Book :"
                      " A sub<title>}", tex)
        self.assertIn("\\markboth{Chapter \\thechapter. #1}{}", tex)
        self.assertIn("\\usepackage[symbol*]{footmisc}", tex)
        self.assertIn("\\MakePerPage{footnote}", tex)
        # memoir's own title-page environment and starred contents.
        self.assertIn("\\begin{titlingpage}", tex)
        self.assertIn("{\\scshape\\Huge Test \\& Book\\par}", tex)
        self.assertIn("{\\itshape\\large by\\par}", tex)
        self.assertIn("\\tableofcontents*", tex)
        self.assertIn("\\frontmatter", tex)

    def test_memoir_off_default_leading_computes_linespread(self):
        tex = render(theme="memoir", line_height="1.5")
        self.assertIn("\\renewcommand{\\baselinestretch}{1.25}", tex)
        self.assertNotIn("{1.125}", tex)

    def test_polimi_uses_real_memoir_veelo(self):
        tex = render(theme="polimi")
        # The thesis's own setup: xelatex, 12pt A4 memoir on its untouched
        # default page (no stock/margin lines), veelo chapters, and the
        # companion-copied fancyheads page style.
        self.assertTrue(tex.startswith("% !TEX program = xelatex"))
        self.assertIn("\\documentclass[12pt, a4paper, twoside, openright, "
                      "oldfontcommands]{memoir}", tex)
        self.assertIn("\\chapterstyle{veelo}", tex)
        self.assertIn("\\copypagestyle{fancyheads}{companion}", tex)
        self.assertIn("\\makeoddhead{fancyheads}"
                      "{\\sffamily\\rightmark}{}{\\thepage}", tex)
        self.assertIn("\\pagestyle{fancyheads}", tex)
        self.assertNotIn("\\setstocksize", tex)
        # The TikZ section bar and the white-on-black caption boxes.
        self.assertIn("\\titleformat{\\section}{\\large\\bfseries\\sffamily}"
                      "{\\titlebar}{0.1cm}{}", tex)
        self.assertIn("\\captionsetup{format=figure,labelfont=white,"
                      "textfont=white,margin=0pt,font={bf,small,sf}}", tex)
        # The thesis faces, falling back to TeX Gyre kin by file name.
        self.assertIn("\\IfFontExistsTF{Minion Pro}", tex)
        self.assertIn("texgyretermes", tex)
        # The memoir-class front matter and the cover-voice title.
        self.assertIn("\\begin{titlingpage}", tex)
        self.assertIn("\\MakeTextUppercase{Test \\& Book}", tex)
        self.assertIn("\\tableofcontents*", tex)
        self.assertIn("\\frontmatter", tex)

    def test_polimi_off_a4_imposes_the_scaled_adaptation(self):
        tex = render(theme="polimi", trim="6x9")
        self.assertIn("\\setstocksize{9in}{6in}", tex)
        self.assertIn("\\setlrmarginsandblock{1.067in}{1.087in}{*}", tex)

    def test_polimi_off_default_leading_computes_baselinestretch(self):
        tex = render(theme="polimi", line_height="1.45")
        self.assertIn("\\renewcommand{\\baselinestretch}{1.2}", tex)
        self.assertNotIn("\\baselinestretch", render(theme="polimi"))

    def test_polimi_no_chapter_numbers_lowers_maxsecnumdepth_too(self):
        # memoir's \mainmatter restores secnumdepth from maxsecnumdepth,
        # so -1 alone would be undone at the start of the body.
        tex = render(theme="polimi", chapter_numbers=False)
        self.assertIn("\\setcounter{secnumdepth}{-1}", tex)
        self.assertIn("\\setcounter{maxsecnumdepth}{-1}", tex)

    def test_polimi_openers_stay_recto_whatever_the_start_option(self):
        # The one-sided source has recto openers only; openany would sink
        # the veelo bar into the gutter on verso openers.
        self.assertIn("openright", render(theme="polimi",
                                          chapter_start="any"))

    def test_no_chapter_numbers(self):
        tex = render(chapter_numbers=False)
        self.assertIn("\\setcounter{secnumdepth}{-1}", tex)

    def test_no_toc(self):
        tex = render(toc=False)
        self.assertNotIn("\\tableofcontents", tex)

    def test_chapter_start_any(self):
        tex = render(chapter_start="any")
        self.assertIn("openany", tex)

    def test_leading_brackets_cannot_read_as_optional_args(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "book.tex")
            write_latex(support.make_book([Chapter(
                title="Brackets", html=BRACKETS_HTML)]), path)
            with open(path, encoding="utf-8") as fh:
                tex = fh.read()
        self.assertIn("\\item {[}sic] an item", tex)
        self.assertIn("{[}a] & x \\\\", tex)
        self.assertIn("{[}b] & y \\\\", tex)


class ReferencesTests(unittest.TestCase):
    def _cited(self):
        import datetime
        from bookformatter import apacite
        return {"https://example.com/ref": apacite.Citation(
            url="https://example.com/ref", title="The Reference",
            author="Jane Q. Doe", date=datetime.datetime(2024, 6, 3),
            site_name="Ref Site")}

    def test_references_section_emitted(self):
        tex = render(references=True, link_citations=self._cited())
        self.assertIn(r"\chapter*{References}", tex)
        self.assertIn(r"\addcontentsline{toc}{chapter}{References}", tex)
        self.assertIn(r"\emph{The Reference}", tex)   # APA italic title
        self.assertIn("Doe, J. Q.", tex)
        self.assertIn(r"\hangindent", tex)            # APA hanging indent

    def test_chapter_sources_listed_for_web_chapters(self):
        b = support.make_book([Chapter(
            title="From the web", html="<p>Body.</p>",
            source="https://blog.example/post", author="Web Writer")])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.tex")
            write_latex(b, path, references=True)
            tex = open(path).read()
        self.assertIn(r"\section*{Chapter sources}", tex)
        self.assertIn("blog.example", tex)

    def test_no_references_when_disabled(self):
        tex = render(references=False, link_citations=self._cited())
        self.assertNotIn(r"\chapter*{References}", tex)

    def test_footnote_in_heading_is_protected(self):
        # \footnote in a sectioning command's moving argument is fragile.
        b = support.make_book([Chapter(
            title="C", html='<h2>Head<span class="footnote">n</span></h2><p>x</p>')])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "b.tex")
            write_latex(b, path)
            tex = open(path).read()
        self.assertIn(r"\protect\footnote", tex)


@unittest.skipUnless(shutil.which("latexmk"), "latexmk not installed")
class CompileTests(unittest.TestCase):
    def _compile(self, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "book.tex")
            b = book()
            write_latex(b, path, **kwargs)
            extract_link_assets(b, tmp)
            pdf = compile_pdf(path)
            self.assertTrue(os.path.exists(pdf))
            with open(pdf, "rb") as fh:
                self.assertEqual(fh.read(5), b"%PDF-")
            # latexmk -c swept the aux clutter.
            self.assertFalse(os.path.exists(os.path.join(tmp, "book.aux")))

    def test_generic_compiles(self):
        self._compile()

    def test_references_page_compiles(self):
        import datetime
        from bookformatter import apacite
        self._compile(references=True, link_citations={
            "https://example.com/ref": apacite.Citation(
                url="https://example.com/ref", title="The Reference",
                author="Jane Q. Doe", date=datetime.datetime(2024, 6, 3),
                site_name="Ref Site")})

    def test_classicthesis_compiles(self):
        self._compile(theme="classicthesis")

    def test_memoir_compiles(self):
        self._compile(theme="memoir")

    def test_polimi_compiles(self):
        self._compile(theme="polimi")

    def test_error_reports_first_tex_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.tex")
            with open(path, "w") as fh:
                fh.write("% !TEX program = pdflatex\n"
                         "\\documentclass{book}\n\\begin{document}\n"
                         "\\undefinedmacro\n\\end{document}\n")
            with self.assertRaises(LatexError) as ctx:
                compile_pdf(path)
            self.assertIn("Undefined control sequence", str(ctx.exception))


class CliTests(unittest.TestCase):
    def test_tex_format_writes_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "ms.md")
            with open(src, "w") as fh:
                fh.write("# Alpha\n\nHello there.\n\n# Beta\n\nAgain.\n")
            out = os.path.join(tmp, "out")
            code = cli_main([src, "-t", "Tex Trial", "-a", "A. Author",
                             "-o", out, "-f", "tex", "--no-link-citations"])
            self.assertEqual(code, 0)
            path = os.path.join(out, "tex-trial.tex")
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as fh:
                tex = fh.read()
            self.assertIn("\\chapter{Alpha}", tex)
            self.assertIn("\\end{document}", tex)


if __name__ == "__main__":
    unittest.main()
