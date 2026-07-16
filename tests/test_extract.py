import unittest

from bookformatter.extract import clean_fragment, extract_article, plain_text_to_html
from bookformatter.footnotes import inline_footnotes

BLOG_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<title>How I Learned to Bind Books | Craft Weekly</title>
<meta property="og:title" content="How I Learned to Bind Books">
<meta property="og:site_name" content="Craft Weekly">
<meta name="author" content="Sam Rivera">
<meta property="article:published_time" content="2024-03-14T09:00:00Z">
</head>
<body>
<header class="site-header"><a href="/">Craft Weekly</a>
  <nav><a href="/about">About</a><a href="/archive">Archive</a></nav>
</header>
<div class="layout">
  <aside class="sidebar">
    <ul><li><a href="/p1">Popular post one</a></li><li><a href="/p2">Popular post two</a></li></ul>
  </aside>
  <article class="post-content">
    <h1>How I Learned to Bind Books</h1>
    <p>The first thing nobody tells you about bookbinding is that the paper
    grain matters more than almost anything else, and you will ruin three
    notebooks before you believe it.</p>
    <p>My teacher, a retired conservator, made me fold sixteen signatures
    before she let me near a needle. The fold, she said, is the book.</p>
    <figure><img src="/images/press.jpg" alt="A nipping press"><figcaption>The press.</figcaption></figure>
    <p>When the sewing finally starts, everything clicks: kettle stitch at
    the head and tail, a straight pass through the middle, and a gentle,
    even tension you can feel in your shoulders.</p>
    <div class="share-buttons"><a href="#">Tweet</a><a href="#">Share</a></div>
  </article>
  <section class="comments">
    <h2>Comments</h2>
    <p>First! Great post, love it, subscribe to my channel for more stuff.</p>
  </section>
</div>
<footer><p>Copyright Craft Weekly. <a href="/privacy">Privacy</a></p></footer>
<script>analytics.track("pageview");</script>
</body>
</html>
"""


class ExtractTests(unittest.TestCase):
    def test_extracts_article_content(self):
        doc = extract_article(BLOG_PAGE, base_url="https://craftweekly.example/posts/binding")
        self.assertEqual(doc.title, "How I Learned to Bind Books")
        self.assertEqual(doc.author, "Sam Rivera")
        self.assertIsNotNone(doc.date)
        self.assertEqual(doc.date.year, 2024)
        self.assertIn("paper", doc.html)
        self.assertIn("kettle stitch", doc.html)

    def test_drops_boilerplate(self):
        doc = extract_article(BLOG_PAGE, base_url="https://craftweekly.example/x")
        self.assertNotIn("Popular post one", doc.html)
        self.assertNotIn("subscribe to my channel", doc.html)
        self.assertNotIn("analytics", doc.html)
        self.assertNotIn("Tweet", doc.html)
        self.assertNotIn("Privacy", doc.html)

    def test_title_not_duplicated_in_body(self):
        doc = extract_article(BLOG_PAGE, base_url="https://craftweekly.example/x")
        self.assertNotIn("<h1>", doc.html)

    def test_absolutizes_urls(self):
        doc = extract_article(BLOG_PAGE, base_url="https://craftweekly.example/posts/binding")
        self.assertIn('src="https://craftweekly.example/images/press.jpg"', doc.html)

    def test_site_suffix_stripped_from_title_tag(self):
        page = BLOG_PAGE.replace('<meta property="og:title" content="How I Learned to Bind Books">', "")
        doc = extract_article(page, base_url="https://craftweekly.example/x")
        self.assertEqual(doc.title, "How I Learned to Bind Books")

    def test_lazy_images(self):
        page = """<html><body><article>
        <p>%s</p>
        <img src="data:image/gif;base64,R0lGOD" data-src="https://cdn.example/real.jpg" alt="x">
        <p>%s</p></article></body></html>""" % ("Long enough paragraph text, with commas, " * 4,
                                                 "Another long paragraph of prose text here, truly, " * 4)
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn('src="https://cdn.example/real.jpg"', doc.html)

    def test_falls_back_to_body(self):
        doc = extract_article("<html><body><p>short page</p></body></html>")
        self.assertIn("short page", doc.html)

    def test_main_column_named_sidebar_survives(self):
        # Bootstrap-style themes (e.g. Strange Horizons) name the wide main
        # content column with a layout word like "sidebar":
        # `col-md-8 col-md-push-4 index-right-sidebar`. The article body must
        # survive even though the class carries the word "sidebar", while a
        # real, link-dense sidebar is still dropped.
        prose = ("The tour guide toweled him off and recited the welcome "
                 "script, all Fear Not and You are a citizen, while the pod "
                 "hissed and dripped onto the polished floor. " * 4)
        page = f"""<!DOCTYPE html><html><head><title>Utopia</title></head><body>
        <div class="row">
          <div class="col-md-4 col-md-pull-8 index-left-sidebar">
            <ul><li><a href="/a">Recent one</a></li><li><a href="/b">Recent two</a></li></ul>
          </div>
          <div class="col-md-8 col-md-push-4 index-right-sidebar">
            <div class="content"><p>{prose}</p><p>{prose}</p></div>
          </div>
        </div></body></html>"""
        doc = extract_article(page, base_url="https://strangehorizons.example/x")
        self.assertIn("toweled him off", doc.html)
        self.assertNotIn("Recent one", doc.html)

    def test_clean_fragment_wraps_stray_text(self):
        out = clean_fragment("plain leading text<p>then a paragraph</p>")
        self.assertTrue(out.startswith("<p>plain leading text</p>"))

    def test_clean_fragment_absolutizes(self):
        out = clean_fragment('<p><a href="/rel">link</a></p>', base_url="https://b.example/post/1")
        self.assertIn('href="https://b.example/rel"', out)

    def test_footnote_anchors_preserved_and_dangling_links_unwrapped(self):
        filler = "A reasonably long paragraph, with commas, to win the scoring pass. " * 3
        page = f"""<html><body><article>
        <p>{filler}</p>
        <p>See note <a href="#f1">[1]</a> and a dangling one <a href="#gone">[2]</a>.</p>
        <p><a name="f1"></a>[1] The note text itself. {filler}</p>
        </article></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn('<a href="#f1">[1]</a>', doc.html)
        self.assertIn('id="f1"', doc.html)
        self.assertNotIn('href="#gone"', doc.html)
        self.assertIn("[2]", doc.html)  # link text kept, wrapper removed

    def test_substack_footnote_defs_become_canonical_list(self):
        # Substack renders each note as its own <div class="footnote"> with the
        # text in a sibling <div class="footnote-content">, not an <ol>/<li>.
        # Extraction must regroup these before the div-unwrapping pass orphans
        # the note text from its landing anchor.
        filler = "A reasonably long paragraph, with commas, to win the scoring pass. " * 3
        page = f"""<html><head><title>Post</title></head><body>
        <article class="post"><div class="body markup">
        <p>{filler}Cited here.<a class="footnote-anchor" id="footnote-anchor-1"
           href="#footnote-1">1</a></p>
        <p>{filler}</p>
        <div class="footnote" data-component-name="FootnoteToDOM">
          <a class="footnote-number" href="#footnote-anchor-1" id="footnote-1">1</a>
          <div class="footnote-content"><p>The actual note text.</p></div>
        </div>
        </div></article></body></html>"""
        doc = extract_article(page, base_url="https://x.substack.example/")
        # The note is regrouped as an <li> carrying the referenced anchor id,
        # holding the note prose (not the bare "1" marker).
        self.assertIn('<li id="footnote-1"><p>The actual note text.</p></li>', doc.html)
        self.assertNotIn('class="footnote-content"', doc.html)
        # And it inlines to a page-bottom footnote span with the real text.
        out = inline_footnotes(doc.html)
        self.assertIn('<span class="footnote">The actual note text.</span>', out)
        self.assertNotIn("<li", out)

    def test_plain_text_paragraphs(self):
        out = plain_text_to_html("Para one\nstill one.\n\nPara two & <tag>.")
        self.assertEqual(
            out,
            "<p>Para one still one.</p>\n<p>Para two &amp; &lt;tag&gt;.</p>",
        )


if __name__ == "__main__":
    unittest.main()
