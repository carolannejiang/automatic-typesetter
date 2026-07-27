import unittest

from bookformatter.feeds import discover_feed_urls, looks_like_feed, parse_feed

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel>
  <title>Field Notes</title>
  <link>https://fieldnotes.example</link>
  <description>A blog about walking</description>
  <item>
    <title>The Long Ridge</title>
    <link>https://fieldnotes.example/ridge</link>
    <description>Short teaser only</description>
    <content:encoded><![CDATA[<p>Full <strong>ridge</strong> content.</p>]]></content:encoded>
    <dc:creator>Ada Walker</dc:creator>
    <pubDate>Tue, 05 Mar 2024 10:00:00 +0000</pubDate>
  </item>
  <item>
    <title>River Crossing</title>
    <link>https://fieldnotes.example/river</link>
    <description><![CDATA[<p>River content from description.</p>]]></description>
    <pubDate>Mon, 04 Mar 2024 10:00:00 +0000</pubDate>
  </item>
</channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Notebook</title>
  <link rel="alternate" href="https://nb.example"/>
  <author><name>Kit Ono</name></author>
  <entry>
    <title>Entry One</title>
    <link rel="alternate" href="https://nb.example/1"/>
    <published>2023-01-10T08:00:00Z</published>
    <content type="html">&lt;p&gt;First entry body.&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>Entry Two</title>
    <link rel="alternate" href="https://nb.example/2"/>
    <published>2023-02-11T08:00:00Z</published>
    <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Second <em>body</em>.</p></div></content>
  </entry>
</feed>
"""


class FeedTests(unittest.TestCase):
    def test_detects_feeds(self):
        self.assertTrue(looks_like_feed(RSS))
        self.assertTrue(looks_like_feed(ATOM))
        self.assertFalse(looks_like_feed("<!DOCTYPE html><html></html>"))
        self.assertTrue(looks_like_feed("", "application/rss+xml"))

    def test_rss_basics(self):
        feed = parse_feed(RSS)
        self.assertEqual(feed.title, "Field Notes")
        self.assertEqual(len(feed.items), 2)

    def test_rss_prefers_content_encoded(self):
        feed = parse_feed(RSS)
        ridge = feed.items[0]
        self.assertIn("<strong>ridge</strong>", ridge.html)
        self.assertEqual(ridge.author, "Ada Walker")
        self.assertEqual(ridge.date.day, 5)

    def test_rss_falls_back_to_description(self):
        feed = parse_feed(RSS)
        self.assertIn("River content", feed.items[1].html)

    def test_atom_html_and_xhtml_content(self):
        feed = parse_feed(ATOM)
        self.assertEqual(feed.title, "Notebook")
        self.assertEqual(feed.items[0].author, "Kit Ono")
        self.assertIn("<p>First entry body.</p>", feed.items[0].html)
        self.assertIn("<em>body</em>", feed.items[1].html)
        self.assertEqual(feed.items[1].link, "https://nb.example/2")

    def test_bad_xml_raises(self):
        with self.assertRaises(ValueError):
            parse_feed("<rss><unclosed>")

    def test_html_encoded_titles_unescaped(self):
        # Tumblr double-encodes titles: the XML text still holds "&rsquo;".
        rss = RSS.replace("<title>The Long Ridge</title>",
                          "<title>Where&amp;rsquo;s that comment?</title>", 1)
        feed = parse_feed(rss)
        self.assertEqual(feed.items[0].title, "Where’s that comment?")

    def test_zoneless_dates_become_aware_utc(self):
        # Feeds mix zoned and zone-less date formats; zone-less ones count as
        # UTC so ordering can sort item dates without a naive/aware TypeError.
        rss = RSS.replace("Mon, 04 Mar 2024 10:00:00 +0000",
                          "04 Mar 2024 09:00:00", 1)
        atom = ATOM.replace("2023-01-10T08:00:00Z", "2023-01-10T08:00:00", 1)
        for feed in (parse_feed(rss), parse_feed(atom)):
            dates = [item.date for item in feed.items]
            self.assertTrue(all(d.tzinfo is not None for d in dates))
            self.assertEqual(len(sorted(dates)), 2)  # sortable, no TypeError

    def test_discover_feed_urls(self):
        page = """<html><head>
        <link rel="alternate" type="application/rss+xml" href="/feed">
        <link rel="alternate" type="application/rss+xml"
              href="https://blog.example/comments/feed/">
        <link rel="alternate" type="application/atom+xml" href="/atom.xml">
        <link rel="alternate" type="application/rss+xml" href="/feed">
        <link rel="alternate" type="text/html" href="/mobile">
        <link rel="stylesheet" href="/style.css">
        </head><body></body></html>"""
        urls = discover_feed_urls(page, "https://blog.example/post/1")
        self.assertEqual(urls, ["https://blog.example/feed",
                                "https://blog.example/atom.xml"])


if __name__ == "__main__":
    unittest.main()
