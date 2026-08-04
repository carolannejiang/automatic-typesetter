import datetime as dt
import unittest
from unittest import mock

from bookformatter import apacite, fetch
from bookformatter.apacite import Citation, format_authors
from bookformatter.htmldom import Node


def render(cite):
    span = Node("span")
    anchor = Node("a", {"class": "linknote-url", "href": cite.url})
    anchor.append(Node(text=cite.url))
    for node in apacite.citation_nodes(cite, anchor):
        span.append(node)
    from bookformatter.htmldom import inner_html
    return inner_html(span)


class FormatAuthorsTests(unittest.TestCase):
    def test_single_personal_name(self):
        self.assertEqual(format_authors("Jane Doe"), "Doe, J.")

    def test_middle_initial(self):
        self.assertEqual(format_authors("Jane Q. Doe"), "Doe, J. Q.")

    def test_hyphenated_given_name(self):
        self.assertEqual(format_authors("Jean-Paul Sartre"), "Sartre, J.-P.")

    def test_surname_particle_stays_with_surname(self):
        self.assertEqual(format_authors("Vincent van Gogh"), "van Gogh, V.")

    def test_lowercase_byline_kept_verbatim(self):
        self.assertEqual(format_authors("bell hooks"), "bell hooks")

    def test_by_prefix_stripped(self):
        self.assertEqual(format_authors("By Jane Doe"), "Doe, J.")

    def test_two_authors_with_and(self):
        self.assertEqual(format_authors("Jane Doe and John Smith"),
                         "Doe, J., & Smith, J.")

    def test_comma_separated_full_names(self):
        self.assertEqual(format_authors("Jane Doe, John Smith, Ada King"),
                         "Doe, J., Smith, J., & King, A.")

    def test_already_inverted_kept_verbatim(self):
        self.assertEqual(format_authors("Doe, Jane"), "Doe, Jane")

    def test_organization_kept_verbatim(self):
        self.assertEqual(format_authors("BBC News"), "BBC News")
        self.assertEqual(format_authors("Pew Research Center"),
                         "Pew Research Center")

    def test_long_name_kept_verbatim(self):
        self.assertEqual(format_authors("The New York Times Company"),
                         "The New York Times Company")

    def test_empty(self):
        self.assertIsNone(format_authors(None))
        self.assertIsNone(format_authors("  "))


class CitationNodesTests(unittest.TestCase):
    def test_full_citation(self):
        cite = Citation(url="https://cats.example/naps", title="How cats sleep",
                        author="Jane Q. Doe", date=dt.datetime(2024, 6, 3),
                        site_name="Cat Journal")
        out = render(cite)
        self.assertEqual(
            out,
            'Doe, J. Q. (2024, June 3). <i>How cats sleep</i>. Cat Journal. '
            '<a class="linknote-url" href="https://cats.example/naps">'
            'https://cats.example/naps</a>')

    def test_no_author_title_leads(self):
        cite = Citation(url="https://x.example/p", title="A page",
                        site_name="x.example")
        out = render(cite)
        self.assertEqual(
            out,
            '<i>A page</i>. (n.d.). x.example. '
            '<a class="linknote-url" href="https://x.example/p">'
            'https://x.example/p</a>')

    def test_org_author_is_site(self):
        cite = Citation(url="https://bbc.example/a", title="A report",
                        author="BBC News", date=dt.datetime(2023, 12, 25),
                        site_name="BBC News")
        out = render(cite)
        # The site is not repeated after the title.
        self.assertEqual(
            out,
            'BBC News. (2023, December 25). <i>A report</i>. '
            '<a class="linknote-url" href="https://bbc.example/a">'
            'https://bbc.example/a</a>')

    def test_title_with_terminal_punctuation(self):
        cite = Citation(url="https://x.example/p", title="Why sleep?",
                        author="Jane Doe", site_name="Sleep Site")
        out = render(cite)
        self.assertIn("<i>Why sleep?</i> Sleep Site.", out)
        self.assertIn("Doe, J. (n.d.).", out)


class FetchCitationTests(unittest.TestCase):
    def test_metadata_from_page(self):
        page = """<html><head><title>How cats sleep | Cat Journal</title>
        <meta property="og:site_name" content="Cat Journal">
        <meta name="author" content="Jane Doe">
        <meta property="article:published_time" content="2024-06-03T10:00:00Z">
        </head><body><article><p>%s</p></article></body></html>""" % ("Zzz. " * 60)
        fake = mock.Mock(return_value=(page, "text/html; charset=utf-8",
                                       "https://www.cats.example/naps"))
        with mock.patch.object(fetch, "fetch_text", fake):
            cite = apacite.fetch_citation("https://www.cats.example/naps#sec2")
        fake.assert_called_once_with("https://www.cats.example/naps", apacite.CITE_TIMEOUT)
        self.assertEqual(cite.title, "How cats sleep")
        self.assertEqual(cite.author, "Jane Doe")
        self.assertEqual(cite.date.date(), dt.date(2024, 6, 3))
        self.assertEqual(cite.site_name, "Cat Journal")
        self.assertEqual(cite.url, "https://www.cats.example/naps#sec2")

    def test_site_falls_back_to_host(self):
        page = ("<html><head><title>A post</title></head><body><article>"
                "<p>%s</p></article></body></html>" % ("Words. " * 60))
        fake = mock.Mock(return_value=(page, "text/html", ""))
        with mock.patch.object(fetch, "fetch_text", fake):
            cite = apacite.fetch_citation("https://www.blog.example/a-post")
        self.assertEqual(cite.site_name, "blog.example")

    def test_non_html_rejected(self):
        fake = mock.Mock(return_value=("%PDF-1.4 ...", "application/pdf", ""))
        with mock.patch.object(fetch, "fetch_text", fake):
            self.assertIsNone(apacite.fetch_citation("https://x.example/a.pdf"))

    def test_untyped_html_sniffed(self):
        page = ("<!DOCTYPE html><html><head><title>A post</title></head>"
                "<body><article><p>%s</p></article></body></html>" % ("Hm. " * 60))
        fake = mock.Mock(return_value=(page, "", ""))
        with mock.patch.object(fetch, "fetch_text", fake):
            cite = apacite.fetch_citation("https://x.example/a")
        self.assertEqual(cite.title, "A post")

    def test_fetch_error_gives_none(self):
        def boom(url, timeout):
            raise fetch.FetchError("could not fetch")
        with mock.patch.object(fetch, "fetch_text", boom):
            self.assertIsNone(apacite.fetch_citation("https://down.example/"))

    def test_no_title_gives_none(self):
        page = "<html><body><article><p>%s</p></article></body></html>" % ("Hi. " * 60)
        fake = mock.Mock(return_value=(page, "text/html", ""))
        with mock.patch.object(fetch, "fetch_text", fake):
            self.assertIsNone(apacite.fetch_citation("https://x.example/a"))


class CollectTests(unittest.TestCase):
    def test_collect_dedupes_and_skips_failures(self):
        calls = []

        def fake(url, timeout=None):
            calls.append(url)
            if "bad" in url:
                return None
            return Citation(url=url, title="T")

        with mock.patch.object(apacite, "fetch_citation", fake):
            out = apacite.collect([
                "https://a.example/", "https://bad.example/",
                "https://a.example/", ""])
        self.assertEqual(sorted(calls),
                         ["https://a.example/", "https://bad.example/"])
        self.assertEqual(set(out), {"https://a.example/"})
        self.assertEqual(out["https://a.example/"].title, "T")

    def test_collect_empty(self):
        self.assertEqual(apacite.collect([]), {})


if __name__ == "__main__":
    unittest.main()
