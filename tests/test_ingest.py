import base64
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from bookformatter import fetch
from bookformatter.ingest import (IngestOptions, PER_HOST_FETCHES,
                                  _fetch_parallel, _host,
                                  _looks_like_index_url, _match_feed_item,
                                  ingest)
from bookformatter.feeds import FeedItem

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

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

    def test_remote_images_download_into_assets(self):
        html = """<html><body><article><p>%s</p>
        <img src="https://imgs.example/pic.png"></article></body></html>""" % PROSE

        def fake_fetch(url, timeout=30.0):
            if url == "https://imgs.example/pic.png":
                return PNG_1PX, "image/png", url
            raise fetch.FetchError(f"could not fetch {url}: HTTP Error 404: Not Found")

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "post.html", html)
            with mock.patch.object(fetch, "fetch", fake_fetch):
                result = ingest([path], IngestOptions())
        self.assertEqual(len(result.assets), 1)
        self.assertIn("images/img-", result.chapters[0].html)
        self.assertEqual(result.warnings, [])

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
  <content:encoded><![CDATA[<p>%s</p><p>%s</p>]]></content:encoded>
  <pubDate>Mon, 04 Mar 2024 10:00:00 +0000</pubDate></item>
<item><title>Second Post</title><link>https://blog.example/posts/second</link>
  <content:encoded><![CDATA[<p>%s</p><p>%s</p>]]></content:encoded>
  <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate></item>
</channel></rss>""" % (PROSE, PROSE, PROSE, PROSE)


class _FakeWeb:
    """Serve canned (text, content_type) responses through fetch.fetch_text,
    recording every requested URL; unknown URLs 404. A three-value entry
    (text, content_type, final_url) simulates a redirect."""

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
        if len(entry) == 3:
            return entry
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

    def test_curated_link_list_imports_each_post(self):
        # A "start here" page: a list whose items each lead to one of the
        # site's posts, wrapped in a blurb. Import the posts, not the list.
        blurb = "A short note on why this one is worth reading. " * 2
        items = "".join(
            f'<li><a href="/blog/post-{n}">Reasons to read post {n}</a> — {blurb}</li>'
            for n in range(1, 7)
        )
        page = f"""<html><head><title>Best Of — Example Blog</title></head>
        <body><main><p>I have a lot of posts, so here is where to start.</p>
        <ul>{items}</ul></main></body></html>"""
        post = lambda n: (f"<html><head><title>Post {n}</title></head>"
                          f"<body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>")
        fake = _FakeWeb({"https://blog.example/best": (page, "text/html"),
                         **{f"https://blog.example/blog/post-{n}": (post(n), "text/html")
                            for n in range(1, 7)}})
        result = self._ingest(fake, "https://blog.example/best")
        self.assertEqual([c.title for c in result.chapters],
                         [f"Post {n}" for n in range(1, 7)])
        self.assertIn("scores well in extraction", result.chapters[0].html)
        self.assertEqual(result.title_hint, "Best Of — Example Blog")

    def test_link_list_respects_max_items_in_document_order(self):
        blurb = "A short note on why this one is worth reading. " * 2
        items = "".join(
            f'<li><a href="/blog/post-{n}">Reasons to read post {n}</a> — {blurb}</li>'
            for n in range(1, 7)
        )
        page = f"""<html><head><title>Best Of</title></head>
        <body><main><ul>{items}</ul></main></body></html>"""
        post = lambda n: (f"<html><head><title>Post {n}</title></head>"
                          f"<body><article><p>{PROSE}</p></article></body></html>")
        fake = _FakeWeb({"https://blog.example/best": (page, "text/html"),
                         **{f"https://blog.example/blog/post-{n}": (post(n), "text/html")
                            for n in range(1, 7)}})
        result = self._ingest(fake, "https://blog.example/best", max_items=2)
        self.assertEqual([c.title for c in result.chapters], ["Post 1", "Post 2"])

    def test_article_with_related_links_is_not_crawled(self):
        # A real post that ends with a short "related" list of its own posts:
        # the prose dominates, so it stays one chapter and nothing is fetched.
        page = f"""<html><head><title>An Essay — Example Blog</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p><p>{PROSE}</p>
        <ul><li><a href="/blog/other-one">See also my other post</a></li>
        <li><a href="/blog/other-two">And this earlier one</a></li></ul>
        </article></body></html>"""
        fake = _FakeWeb({"https://blog.example/essays/one": (page, "text/html")})
        result = self._ingest(fake, "https://blog.example/essays/one")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("An Essay", result.chapters[0].title)
        self.assertNotIn("https://blog.example/blog/other-one", fake.requested)

    def test_link_list_ignores_off_site_links(self):
        # A roundup that links out to other sites is not a list of *our* posts;
        # the same-site filter leaves it as a single chapter.
        blurb = "Some commentary on an external piece worth your time. " * 2
        items = "".join(
            f'<li><a href="https://other{n}.example/x">External piece {n}</a> — {blurb}</li>'
            for n in range(1, 7)
        )
        page = f"""<html><head><title>Weekly Links</title></head>
        <body><main><ul>{items}</ul></main></body></html>"""
        fake = _FakeWeb({"https://blog.example/links": (page, "text/html")})
        result = self._ingest(fake, "https://blog.example/links")
        self.assertEqual(len(result.chapters), 1)
        self.assertNotIn("https://other1.example/x", fake.requested)

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
        # Short items must not trigger doomed page fetches: Medium 403s them.
        self.assertNotIn("https://medium.com/@ana/the-story-0123abcd4567?source=rss",
                         fake.requested)

    def test_lesswrong_429_imports_from_greaterwrong_mirror(self):
        post = ("https://www.lesswrong.com/posts/abc123/"
                "rubys-ultimate-guide-to-thoughtful-gifts")
        mirror = ("https://www.greaterwrong.com/posts/abc123/"
                  "rubys-ultimate-guide-to-thoughtful-gifts")
        blocked = fetch.FetchError(
            f"could not fetch {post}: HTTP Error 429: Too Many Requests")
        page = (f"<html><head><title>Ruby's Guide</title></head>"
                f"<body><article><h1>Ruby's Guide</h1><p>{PROSE}</p></article></body></html>")
        fake = _FakeWeb({post: blocked, mirror: (page, "text/html")})
        result = self._ingest(fake, post)
        self.assertEqual([c.title for c in result.chapters], ["Ruby's Guide"])
        # The canonical LessWrong URL stays the source, not the mirror.
        self.assertEqual(result.chapters[0].source, post)
        self.assertTrue(any("GreaterWrong" in w for w in result.warnings))

    # A multi-sentence excerpt (~250 chars) that is still well under
    # SUMMARY_LEN — pins the threshold above "a couple of sentences".
    TEASER = ("A teaser that says just enough about the essay to make you "
              "want to click through and read the whole thing on the site. " * 2 +
              "It never gets to the argument itself.")

    def _summary_feed(self, description=TEASER):
        return """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>https://blog.example/</link>
        <item><title>First Post</title><link>https://blog.example/posts/first</link>
          <description>%s</description></item>
        </channel></rss>""" % description

    def test_summary_only_feed_fetches_full_posts(self):
        # joecarlsmith.com-style feed: items carry only an excerpt, so each
        # post's page is fetched automatically for the full text.
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual([c.title for c in result.chapters], ["First Post"])
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_summary_kept_when_page_fetch_fails(self):
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("never gets to the argument", result.chapters[0].html)
        # One aggregate warning naming the first failure, not one per item.
        kept = [w for w in result.warnings if "kept their feed text" in w]
        self.assertEqual(len(kept), 1)
        self.assertIn("1 of 1", kept[0])
        self.assertIn("posts/first", kept[0])

    def test_boilerplate_page_does_not_replace_summary(self):
        # The post page extracts to a short subscribe pitch — byte-longer
        # than the excerpt, but not an article. Keep the feed's excerpt.
        page = """<html><head><title>First Post</title></head><body>
        <p>Subscribe to the newsletter to keep reading, and tell your
        friends about it too!</p></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("never gets to the argument", result.chapters[0].html)
        self.assertNotIn("Subscribe", result.chapters[0].html)

    def test_image_only_item_keeps_its_image(self):
        # Photo/comic feeds: the <img> is the post. A text-only page
        # extraction must not replace it.
        feed_xml = self._summary_feed(
            '<![CDATA[<img src="https://imgs.example/strip-2931.png">]]>')
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("strip-2931.png", result.chapters[0].html)

    def test_style_block_does_not_hide_a_truncated_item(self):
        # Newsletter-style feeds pad items with <style>; that text is code,
        # not content, and must not defeat the truncation check.
        css = "p { margin: 0 0 1em 0; color: #222222; line-height: 1.55; } " * 12
        feed_xml = self._summary_feed(
            "<![CDATA[<style>%s</style><p>One-line teaser only.</p>]]>" % css)
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_link_blog_items_are_not_fetched_from_other_sites(self):
        # On a link blog the item's link is someone else's article; the
        # item's own commentary is the post and must survive.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Links</title>
        <link>https://blog.example/</link>
        <item><title>Neat Essay</title><link>https://elsewhere.example/essay</link>
          <description>Sharp piece; the section on drafts is the keeper.</description></item>
        </channel></rss>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("section on drafts", result.chapters[0].html)
        self.assertNotIn("https://elsewhere.example/essay", fake.requested)

    def test_tracking_pixel_does_not_block_full_text(self):
        # WordPress.com/FeedBurner append a 1x1 pixel to every item; that
        # img is not content and must not keep the teaser in place.
        feed_xml = self._summary_feed(
            '<![CDATA[<p>%s</p><img src="https://pixel.wp.example/b.gif" '
            'height="1" width="1">]]>' % self.TEASER)
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_uppercase_img_item_keeps_its_image(self):
        feed_xml = self._summary_feed(
            '<![CDATA[<IMG SRC="https://imgs.example/strip-2931.png">]]>')
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("strip-2931.png", result.chapters[0].html)

    def test_title_only_item_uses_page_even_for_a_short_post(self):
        # No description at all: any real extraction beats nothing, even
        # below the article-length bar.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>https://blog.example/</link>
        <item><title>First Post</title><link>https://blog.example/posts/first</link></item>
        </channel></rss>"""
        page = """<html><head><title>First Post</title></head><body><article>
        <p>A short note, complete in a couple of sentences, that still
        deserves its place as a chapter in the collected blog.</p>
        </article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("short note", result.chapters[0].html)

    def test_unparseable_channel_link_falls_back_to_feed_host(self):
        # Hand-rolled feeds ship channel links like "/" or "blog.example/";
        # the feed's own host still identifies the site.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title><link>/</link>
        <item><title>First Post</title><link>https://blog.example/posts/first</link>
          <description>%s</description></item>
        </channel></rss>""" % self.TEASER
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_subdomain_split_still_counts_as_same_site(self):
        # Channel link on the apex domain, posts on a blog. subdomain.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>https://example.test/</link>
        <item><title>First Post</title><link>https://blog.example.test/posts/first</link>
          <description>%s</description></item>
        </channel></rss>""" % self.TEASER
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://example.test/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example.test/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://example.test/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_aggregate_warning_counts_all_failures(self):
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>https://blog.example/</link>
        <item><title>One</title><link>https://blog.example/posts/one</link>
          <description>%s</description></item>
        <item><title>Two</title><link>https://blog.example/posts/two</link>
          <description>%s</description></item>
        </channel></rss>""" % (self.TEASER, self.TEASER)
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 2)
        kept = [w for w in result.warnings if "kept their feed text" in w]
        self.assertEqual(len(kept), 1)
        self.assertIn("2 of 2", kept[0])

    def test_js_shell_post_page_keeps_teaser_and_warns(self):
        page = """<html><head><title>First Post</title></head>
        <body><div id="app"></div></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("never gets to the argument", result.chapters[0].html)
        self.assertTrue(any("no readable article" in w for w in result.warnings))

    def test_progress_callback_reports_page_fetches(self):
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        messages = []
        self._ingest(fake, "https://blog.example/feed", progress=messages.append)
        self.assertTrue(any("1/1" in m for m in messages))

    def test_item_link_pointing_at_feed_is_not_fetched(self):
        # Some broken feeds set every item's link to the feed itself;
        # "fetching the full text" from it would yield feed-XML junk.
        feed_xml = self._summary_feed().replace(
            "https://blog.example/posts/first", "https://blog.example/feed")
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("never gets to the argument", result.chapters[0].html)
        self.assertEqual(fake.requested, ["https://blog.example/feed"])

    def test_redirected_feed_matches_final_host(self):
        # A feed URL that 301s to another host: item links live on the
        # landing host, and that's the host that must count as the site.
        feed_xml = self._summary_feed().replace(
            "<link>https://blog.example/</link>", "<link>/</link>")
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://old.example/feed":
                (feed_xml, "application/rss+xml", "https://blog.example/feed"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://old.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_pixel_only_stub_still_gets_full_text(self):
        # A FeedBurner-style 1×1 pixel is not content; it must not trigger
        # the image-only protection and pin the stub in place.
        feed_xml = self._summary_feed(
            '<![CDATA[<img src="https://feeds.example/~r/Blog/~4/xyz" '
            'height="1" width="1">]]>')
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_share_link_junk_does_not_inflate_item_length(self):
        # Feedflare-style blocks of share links are stripped by cleaning;
        # the truncation check must measure the cleaned item, or a teaser
        # padded with link junk never gets its full text.
        links = "".join(
            f'<a href="https://blog.example/share/{i}">Share this wonderful '
            f'post with service number {i} right away</a> ' for i in range(8))
        feed_xml = self._summary_feed(
            "<![CDATA[<p>A one-line teaser only, honestly not the post.</p>"
            "<div>%s</div>]]>" % links)
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("reasonably long paragraph", result.chapters[0].html)

    def test_no_fetch_full_keeps_feed_text(self):
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (self._summary_feed(), "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed", fetch_full=False)
        self.assertEqual(len(result.chapters), 1)
        self.assertIn("never gets to the argument", result.chapters[0].html)
        self.assertEqual(fake.requested, ["https://blog.example/feed"])

    def test_off_domain_feed_uses_items_common_host(self):
        # FeedPress-style: the feed and its channel link live on the feed
        # service's domain, every item links to the blog itself, and the
        # items carry no text of their own.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>https://feedpress.example/exampleblog</link>
        <item><title>One</title><link>https://blog.example/posts/one</link></item>
        <item><title>Two</title><link>https://blog.example/posts/two</link></item>
        </channel></rss>"""
        page = f"""<html><head><title>Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://feedpress.example/exampleblog": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/one": (page, "text/html"),
            "https://blog.example/posts/two": (page, "text/html"),
        })
        result = self._ingest(fake, "https://feedpress.example/exampleblog")
        self.assertEqual(len(result.chapters), 2)
        for chapter in result.chapters:
            self.assertIn("reasonably long paragraph", chapter.html)

    def test_single_source_commentary_blog_keeps_its_own_words(self):
        # A commentary blog whose every item links one external site has
        # the same shape as an off-domain feed — but its item text is the
        # post, and must never be swapped for the linked site's articles.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Reading the Times</title>
        <link>https://blog.example/</link>
        <item><title>One</title><link>https://elsewhere.example/a1</link>
          <description>%s</description></item>
        <item><title>Two</title><link>https://elsewhere.example/a2</link>
          <description>%s</description></item>
        </channel></rss>""" % (self.TEASER, self.TEASER)
        page = f"""<html><body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://elsewhere.example/a1": (page, "text/html"),
            "https://elsewhere.example/a2": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 2)
        for chapter in result.chapters:
            self.assertIn("never gets to the argument", chapter.html)
        self.assertEqual(fake.requested, ["https://blog.example/feed"])

    def test_fetch_parallel_caps_concurrency_per_host(self):
        lock = threading.Lock()
        active = {"now": 0, "peak": 0}

        def slow_fetch(u):
            with lock:
                active["now"] += 1
                active["peak"] = max(active["peak"], active["now"])
            time.sleep(0.02)
            with lock:
                active["now"] -= 1
            return u

        urls = [f"https://one.example/p{i}" for i in range(12)]
        results = _fetch_parallel(urls, slow_fetch, "x", IngestOptions())
        self.assertEqual(len(results), 12)
        self.assertLessEqual(active["peak"], PER_HOST_FETCHES)

    def test_host_normalization(self):
        self.assertEqual(_host("https://www.Example.com/feed"), "example.com")
        self.assertEqual(_host("https://münchen.example/x"),
                         _host("https://xn--mnchen-3ya.example/"))
        self.assertEqual(_host("http://[2001:db8::1/post"), "")

    def test_malformed_item_and_channel_links_do_not_crash(self):
        # Broken IPv6 literals and template placeholders show up in real
        # feeds; a bad link must cost that item its upgrade, not the build.
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>Example Blog</title>
        <link>http://[2001:db8::1/</link>
        <item><title>Bad Link</title><link>http://[2001:db8::1/posts/bad</link>
          <description>%s</description></item>
        <item><title>First Post</title><link>https://blog.example/posts/first</link>
          <description>%s</description></item>
        </channel></rss>""" % (self.TEASER, self.TEASER)
        page = f"""<html><head><title>First Post</title></head>
        <body><article><p>{PROSE}</p><p>{PROSE}</p></article></body></html>"""
        fake = _FakeWeb({
            "https://blog.example/feed": (feed_xml, "application/rss+xml"),
            "https://blog.example/posts/first": (page, "text/html"),
        })
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual([c.title for c in result.chapters],
                         ["Bad Link", "First Post"])
        self.assertIn("reasonably long paragraph", result.chapters[1].html)

    def test_full_content_feed_items_are_not_refetched(self):
        fake = _FakeWeb({"https://blog.example/feed": (FEED_XML, "application/rss+xml")})
        result = self._ingest(fake, "https://blog.example/feed")
        self.assertEqual(len(result.chapters), 2)
        self.assertEqual(fake.requested, ["https://blog.example/feed"])

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


class FetchCacheTests(unittest.TestCase):
    def test_ingest_starts_with_a_fresh_fetch_cache(self):
        # Long-lived hosts (the web server) reuse the process across builds;
        # a surviving cache would grow without bound and serve last build's
        # feed content forever.
        fetch._cache["https://stale.example/"] = (b"x", "text/html",
                                                 "https://stale.example/")
        ingest([])
        self.assertEqual(fetch._cache, {})


if __name__ == "__main__":
    unittest.main()
