import base64
import os
import tempfile
import unittest
from unittest import mock

from bookformatter import fetch
from bookformatter.ingest import (IngestOptions, _looks_like_index_url,
                                  _match_feed_item, ingest)
from bookformatter.feeds import FeedItem
from tests.conftest import PNG_1PX

MULTI_CHAPTER_MD = """# The Cellar Door

It began, as these things do, in the dark.

# The Stairs

Fourteen steps, and I counted every one.

# The Room Below

There was nothing there. That was the worst part.
"""

SINGLE_MD = """# A Lone Essay

Just one heading here, so the heading becomes the chapter title.

More prose follows in a second paragraph.
"""


class IngestTests(unittest.TestCase):
    def _write(self, tmp, name, content, mode="w"):
        path = os.path.join(tmp, name)
        with open(path, mode) as fh:
            fh.write(content)
        return path

    def test_markdown_auto_split_on_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "book.md", MULTI_CHAPTER_MD)
            result = ingest([path])
        self.assertEqual([c.title for c in result.chapters],
                         ["The Cellar Door", "The Stairs", "The Room Below"])
        self.assertIn("in the dark", result.chapters[0].html)
        self.assertNotIn("<h1>", result.chapters[0].html)

    def test_markdown_no_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "book.md", MULTI_CHAPTER_MD)
            result = ingest([path], IngestOptions(split="none"))
        self.assertEqual(len(result.chapters), 1)

    def test_single_h1_becomes_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "essay.md", SINGLE_MD)
            result = ingest([path])
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(result.chapters[0].title, "A Lone Essay")
        self.assertNotIn("<h1>", result.chapters[0].html)

    def test_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "my-old-journal.txt", "First para.\n\nSecond para.")
            result = ingest([path])
        self.assertEqual(result.chapters[0].title, "My Old Journal")
        self.assertEqual(result.chapters[0].html.count("<p>"), 2)

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0,
                     "chmod cannot make a file unreadable for root/Windows")
    def test_unreadable_file_warns_and_continues(self):
        # One bad input must not kill the batch: warn, keep going.
        with tempfile.TemporaryDirectory() as tmp:
            bad = self._write(tmp, "locked.md", "# Locked\n\nshut tight")
            good = self._write(tmp, "open.md", SINGLE_MD)
            os.chmod(bad, 0)
            result = ingest([bad, good])
        self.assertEqual([c.title for c in result.chapters], ["A Lone Essay"])
        self.assertTrue(any("locked.md" in w for w in result.warnings))

    def test_ingest_clears_fetch_cache(self):
        # The fetch cache is per run; a long-lived web server must not
        # accumulate fetched pages/images across builds.
        fetch._cache()["https://stale.example/page"] = (b"x", "text/html", "u")
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "essay.md", SINGLE_MD)
            ingest([path])
        self.assertEqual(fetch._cache(), {})

    def test_directory_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "02-b.md", "# Second\n\ntext two")
            self._write(tmp, "01-a.md", "# First\n\ntext one")
            self._write(tmp, "notes.json", "{}")  # ignored
            result = ingest([tmp])
        self.assertEqual([c.title for c in result.chapters], ["First", "Second"])

    def test_local_html_with_local_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pic.png", PNG_1PX, mode="wb")
            page = """<html><head><title>Local Page</title></head><body><article>
            <h1>Local Page</h1>
            <p>%s</p><img src="pic.png" alt="p">
            <p>%s</p></article></body></html>""" % (
                "A long paragraph, with commas, and plenty of words to score well. " * 3,
                "Another long paragraph, also with commas, for the scorer to like. " * 3,
            )
            path = self._write(tmp, "page.html", page)
            result = ingest([path])
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(len(result.assets), 1)
        self.assertTrue(result.assets[0].filename.startswith("images/img-"))
        self.assertIn(result.assets[0].filename, result.chapters[0].html)

    def test_images_strip_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "pic.png", PNG_1PX, mode="wb")
            path = self._write(tmp, "doc.md", "# T\n\nbody text\n\n![alt](pic.png)")
            result = ingest([path], IngestOptions(images="strip"))
        self.assertEqual(result.assets, [])
        self.assertNotIn("<img", result.chapters[0].html)

    def test_data_uri_image(self):
        uri = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "doc.md", f"# T\n\nbody\n\n![x]({uri})")
            result = ingest([path])
        self.assertEqual(len(result.assets), 1)
        self.assertEqual(result.assets[0].media_type, "image/png")

    def test_missing_input_warns(self):
        result = ingest(["/nonexistent/path.md"])
        self.assertEqual(result.chapters, [])
        self.assertTrue(result.warnings)


PROSE = ("A reasonably long paragraph, with commas, that scores well in "
         "extraction and stands in for real writing. " * 4)

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel><title>Example Blog</title><link>https://blog.example/</link>
<item><title>First Post</title><link>https://blog.example/posts/first</link>
  <content:encoded><![CDATA[<p>%s</p>]]></content:encoded>
  <pubDate>Mon, 04 Mar 2024 10:00:00 +0000</pubDate></item>
<item><title>Second Post</title><link>https://blog.example/posts/second</link>
  <content:encoded><![CDATA[<p>%s</p>]]></content:encoded>
  <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate></item>
</channel></rss>""" % (PROSE, PROSE)


class _FakeWeb:
    """Serve canned (text, content_type) responses through fetch.fetch_text,
    recording every requested URL; unknown URLs 404."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.requested: list = []

    def __call__(self, url, timeout=30.0):
        self.requested.append(url)
        if url not in self.pages:
            raise fetch.FetchError(f"could not fetch {url}: HTTP Error 404: Not Found")
        entry = self.pages[url]
        if isinstance(entry, Exception):
            raise entry
        text, content_type = entry
        return text, content_type, url


class UrlIngestTests(unittest.TestCase):
    def _ingest(self, fake, url, **opt_kwargs):
        opts = IngestOptions(images="link", **opt_kwargs)
        with mock.patch.object(fetch, "fetch_text", fake):
            return ingest([url], opts)

    def test_homepage_uses_advertised_feed(self):
        home = """<html><head><title>Example Blog</title>
        <link rel="alternate" type="application/rss+xml" href="/feed">
        </head><body><nav><a href="/posts/first">First Post</a>
        <a href="/posts/second">Second Post</a></nav></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/": (home, "text/html"),
            "https://blog.example/feed": (FEED_XML, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/")
        self.assertEqual([c.title for c in result.chapters],
                         ["First Post", "Second Post"])
        self.assertEqual(result.title_hint, "Example Blog")

    def test_index_url_guesses_common_feed_paths(self):
        # Hashnode (and others) advertise no <link rel=alternate> at all.
        home = """<html><head><title>Example Blog</title></head>
        <body><a href="/posts/first">First Post</a></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/": (home, "text/html"),
            "https://blog.example/rss.xml": (FEED_XML, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/")
        self.assertEqual(len(result.chapters), 2)
        # /feed was tried (and 404ed) before /rss.xml hit.
        self.assertIn("https://blog.example/feed", fake.requested)

    def test_rich_article_page_is_not_switched_to_feed(self):
        page = f"""<html><head><title>First Post — Example Blog</title>
        <link rel="alternate" type="application/rss+xml" href="/feed">
        </head><body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({"https://blog.example/posts/first": (page, "text/html")})
        result = self._ingest(fake, "https://blog.example/posts/first")
        self.assertEqual(len(result.chapters), 1)
        self.assertEqual(result.chapters[0].title, "First Post")
        self.assertNotIn("https://blog.example/feed", fake.requested)

    def test_thin_post_page_imports_matching_feed_item(self):
        # A page the extractor gets almost nothing from (JS-heavy theme)
        # advertising a feed that carries the post: import just that item.
        page = """<html><head><title>First Post</title>
        <link rel="alternate" type="application/rss+xml" href="/feed">
        </head><body><div id="app"></div></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/posts/first": (page, "text/html"),
            "https://blog.example/feed": (FEED_XML, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/posts/first")
        self.assertEqual([c.title for c in result.chapters], ["First Post"])
        self.assertTrue(any("feed" in w for w in result.warnings))

    def test_thin_post_page_without_feed_match_keeps_page(self):
        page = """<html><head><title>Elsewhere</title>
        <link rel="alternate" type="application/rss+xml" href="/feed">
        </head><body><article><p>A short note, barely a post, but real
        writing that belongs in the book all the same.</p></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/notes/elsewhere": (page, "text/html"),
            "https://blog.example/feed": (FEED_XML, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/notes/elsewhere")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("barely a post", result.chapters[0].html)

    def test_js_shell_page_warns_and_adds_nothing(self):
        page = """<html><head><title>Notion | Where work happens</title></head>
        <body><div id="notion-app"></div><script src="/app.js"></script></body></html>"""
        fake = _FakeWeb({"https://someone.notion.example/Post-abc123": (page, "text/html")})
        result = self._ingest(fake, "https://someone.notion.example/Post-abc123")
        self.assertEqual(result.chapters, [])
        self.assertTrue(any("JavaScript" in w for w in result.warnings))

    def test_medium_403_imports_story_from_feed(self):
        medium_feed = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><title>Stories by Ana on Medium</title>
        <item><title>The Story</title>
          <link>https://medium.com/@ana/the-story-0123abcd4567?source=rss</link>
          <content:encoded><![CDATA[<p>%s</p>]]></content:encoded>
          <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate></item>
        <item><title>Older</title>
          <link>https://medium.com/@ana/older-ffff0000aaaa</link>
          <content:encoded><![CDATA[<p>%s</p>]]></content:encoded></item>
        </channel></rss>""" % (PROSE, PROSE)
        blocked = fetch.FetchError(
            "could not fetch https://medium.com/@ana/the-story-0123abcd4567: "
            "HTTP Error 403: Forbidden")
        fake = _FakeWeb({
            "https://medium.com/@ana/the-story-0123abcd4567": blocked,
            "https://medium.com/feed/@ana": (medium_feed, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://medium.com/@ana/the-story-0123abcd4567")
        self.assertEqual([c.title for c in result.chapters], ["The Story"])
        self.assertEqual(result.title_hint, "The Story")
        self.assertTrue(any("Medium" in w for w in result.warnings))

    def test_index_url_detection(self):
        for url in ("https://a.example", "https://a.example/", "https://a.example/blog/",
                    "https://a.example/Archive", "https://a.example/index.html"):
            self.assertTrue(_looks_like_index_url(url), url)
        for url in ("https://a.example/blog/2024/post", "https://a.example/?p=123",
                    "https://a.example/a-standalone-essay"):
            self.assertFalse(_looks_like_index_url(url), url)

    def test_match_feed_item_ignores_tracking_but_keeps_permalink_query(self):
        items = [FeedItem(title="A", link="https://b.example/?p=123&utm_source=rss"),
                 FeedItem(title="B", link="https://b.example/?p=124")]
        self.assertEqual(_match_feed_item(items, "https://b.example/?p=124").title, "B")
        self.assertEqual(_match_feed_item(items, "http://b.example/?p=123").title, "A")
        self.assertIsNone(_match_feed_item(items, "https://b.example/?p=999"))

    def test_blocked_fetch_warns_with_feed_guidance(self):
        blocked = fetch.FetchError(
            "could not fetch https://walled.example/post: HTTP Error 403: Forbidden")
        fake = _FakeWeb({"https://walled.example/post": blocked})
        result = self._ingest(fake, "https://walled.example/post")
        self.assertEqual(result.chapters, [])
        self.assertTrue(any("RSS/Atom feed" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
