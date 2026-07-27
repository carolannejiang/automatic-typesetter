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

    def test_breakpoint_classes_are_not_content_hints(self):
        # Wix stamps the wrapper around the whole page with responsive
        # breakpoint utilities like "gt-740 lte-w980 lte-banner-w1564". The
        # word "banner" inside such a token must not drop the wrapper — but a
        # real cookie banner still must.
        prose = ("This is the post I wish someone had sent me earlier, with "
                 "commas, and enough length to win the scoring pass easily. " * 4)
        page = f"""<!DOCTYPE html><html><head><title>Advice</title></head><body>
        <div class="cookie-banner"><p>We use cookies, please accept them, thanks.</p></div>
        <div class="md lt-lg gt-740 lte-w980 lte-banner-w1564 lte-banner-w980 urt2wh">
          <div class="post-body"><p>{prose}</p><p>{prose}</p></div>
        </div></body></html>"""
        doc = extract_article(page, base_url="https://wixsite.example/post/advice")
        self.assertIn("someone had sent me", doc.html)
        self.assertNotIn("We use cookies", doc.html)

    def test_tailwind_utility_classes_are_not_content_hints(self):
        # Forethought (Tailwind) wraps the entire article in a section whose
        # scroll-margin utility references a CSS variable named
        # --scroll-nav-offset-y. The "nav" inside that arbitrary-value token
        # must not drop the section — but a real nav-classed menu still must.
        prose = ("Automating AI research could compress decades of progress, "
                 "with feedback loops, into a few short years of change. " * 4)
        page = f"""<!DOCTYPE html><html><head><title>Explosion</title></head><body>
        <div class="site-nav"><p>Research, About, Donate, Careers, Contact us now.</p></div>
        <section class="px-[30px] md:pt-[80px] bg-ft-offwhite scroll-mt-[var(--scroll-nav-offset-y)] group-hover:opacity-100">
          <div class="post-body"><p>{prose}</p><p>{prose}</p></div>
        </section></body></html>"""
        doc = extract_article(page, base_url="https://forethought.example/research/x")
        self.assertIn("compress decades of progress", doc.html)
        self.assertNotIn("Donate", doc.html)

    def test_per_paragraph_wrappers_still_find_whole_article(self):
        # Wix nests every paragraph in its own stack of divs (some one deep,
        # some three deep), so votes never accumulate on the real article
        # container when only the parent and grandparent are scored — a
        # comma-rich list inside the post, whose items all share one <ol>,
        # outscores it and the extractor returns just that list fragment.
        # With decaying votes up to five levels the whole post must win.
        prose = ("A reasonably long paragraph, with commas, that should count "
                 "toward the article container's score when votes decay. " * 2)
        shallow = "".join(f"<div><p>{prose}</p></div>" for _ in range(6))
        deep = "".join(
            f"<div><div><div><p>{prose}</p></div></div></div>" for _ in range(9)
        )
        items = "".join(
            f"<li>Advice item {i}: be able to point to relevant work, ask "
            f"crisp questions, follow up afterwards, and thank your mentors "
            f"for the time they spend on you.</li>"
            for i in range(8)
        )
        page = f"""<!DOCTYPE html><html><head><title>Post</title></head><body>
        <div class="uJ2mK"><div class="xR8wQ">
        {shallow}<ol>{items}</ol>{deep}
        </div></div></body></html>"""
        doc = extract_article(page, base_url="https://wixsite.example/post/x")
        self.assertIn("when votes decay", doc.html)
        self.assertIn("Advice item 0", doc.html)

    def test_article_split_across_sibling_wrappers(self):
        # Single-winner selection with no sibling merge: when a layout splits
        # one article across sibling wrapper divs (Medium sections, Wix column
        # rows, hero-intro-then-body themes), the wrapper holding the majority
        # of the text used to win outright and the rest was silently dropped.
        p1 = "First-half paragraph with plenty of text, commas, and length to vote strongly here. " * 3
        p2 = "Second-half paragraph, equally real content, that a reader would certainly miss badly. " * 3
        first = "".join(f"<p>{p1}</p>" for _ in range(6))
        second = "".join(f"<p>{p2}</p>" for _ in range(3))
        page = f"""<html><head><title>T</title></head><body>
        <div class="a1b2c"><div class="x9y8z">{first}</div><div class="q7w6e">{second}</div></div>
        </body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn("First-half", doc.html)
        self.assertIn("Second-half", doc.html)

    def test_article_split_at_two_levels(self):
        # Medium's article > section > div stacks can split at two levels at
        # once; reassembly must climb past the winner's immediate parent.
        p1 = "First-half paragraph with plenty of text, commas, and length to vote strongly here. " * 3
        p2 = "Second-half paragraph, equally real content, that a reader would certainly miss badly. " * 3
        first = "".join(f"<p>{p1}</p>" for _ in range(6))
        page = f"""<html><head><title>T</title></head><body><article>
        <section><div class="w1">{first}</div><div class="w2"><p>{p1}</p></div></section>
        <section><div class="w3"><p>{p2}</p></div></section>
        </article></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn("First-half", doc.html)
        self.assertIn("Second-half", doc.html)

    def test_heading_and_figure_in_own_sibling_wrappers(self):
        # A mid-article heading or figure often sits in its own wrapper div
        # between paragraph wrappers. Such wrappers never vote (headings and
        # figures score nothing), so sibling reassembly must count them as
        # content rather than strand them outside the winning container.
        p1 = "First-half paragraph with plenty of text, commas, and length to vote strongly here. " * 3
        p2 = "Second-half paragraph, equally real content, that a reader would certainly miss badly. " * 3
        first = "".join(f"<p>{p1}</p>" for _ in range(6))
        page = f"""<html><head><title>T</title></head><body><div class="outer">
        <div>{first}</div>
        <div><h2>A Mid-Article Heading</h2></div>
        <div><figure><img src="/pic.jpg" alt="pic"><figcaption>The picture.</figcaption></figure></div>
        <div><p>{p2}</p></div>
        </div></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn("Mid-Article Heading", doc.html)
        self.assertIn("https://x.example/pic.jpg", doc.html)
        self.assertIn("Second-half", doc.html)

    def test_sibling_reassembly_still_drops_junk(self):
        # Widening to siblings must not let link-dense boilerplate ride along:
        # an unhinted related-links list next to the article body stays out.
        p1 = "Article paragraph with plenty of text, commas, and length to vote strongly here. " * 3
        first = "".join(f"<p>{p1}</p>" for _ in range(6))
        links = "".join(f'<li><a href="/r{i}">Recommended piece number {i} you may enjoy</a></li>'
                        for i in range(8))
        page = f"""<html><head><title>T</title></head><body>
        <div class="outer"><div class="x9y8z">{first}</div><div class="q7w6e"><ul>{links}</ul></div></div>
        </body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn("Article paragraph", doc.html)
        self.assertNotIn("Recommended piece", doc.html)

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

    def test_self_anchored_reference_marker_becomes_footnote(self):
        # Some custom themes (joecarlsmith.com) invert the footnote convention:
        # the marker anchors *itself* (<sup id="ref-1"><a href="#ref-1">) and the
        # note lives in a separate CSS-grid container keyed by an unreferenced id.
        # Both the readability drop of that container and the self-anchor must be
        # handled so the note reaches the page-bottom footnote.
        filler = "A reasonably long paragraph, with commas, to win the scoring pass. " * 3
        page = f"""<html><head><title>Essay</title></head><body>
        <article><div class="single-essay__content">
        <p>{filler}A claim.<sup class="article-reference" id="ref-1">
           <a href="#ref-1">1</a></sup> More prose. {filler}</p>
        </div></article>
        <div class="single-essay__references">
          <div class="single-essay__references-item reference" id="reference-item-1">
            <a href="#ref-1" class="reference__index">1</a>
            <div class="reference__text"><p>The actual note text.</p></div>
          </div>
        </div>
        </body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        # The note is regrouped as an <li> keyed by the marker's id, and the
        # marker's self-anchor id is dropped so #ref-1 now names the note.
        self.assertIn('<li id="ref-1"><p>The actual note text.</p></li>', doc.html)
        self.assertNotIn('class="reference__text"', doc.html)
        self.assertIn('<a href="#ref-1">1</a>', doc.html)
        # And it inlines to a page-bottom footnote span with the real text.
        out = inline_footnotes(doc.html)
        self.assertIn('<span class="footnote">The actual note text.</span>', out)
        self.assertNotIn("<li", out)

    def test_blogger_noscript_body_survives(self):
        # Blogger's Dynamic Views themes ship the post body only inside
        # <noscript> (JS assembles the visible copy from a template), in
        # Google-Docs markup: bare divs and spans, never a <p>. The
        # "enable JavaScript" notice noscript must still drop.
        para = ("Since the very beginning, millions of people, writers and "
                "hobbyists alike, have expressed themselves here, at length, "
                "with care. " * 3)
        page = f"""<html><head><title>Post Title - My Blog</title></head><body>
        <noscript><style>.m{{color:red}}</style>
          <p>JavaScript must be enabled in order to use this site.<br/>
          Please enable JavaScript to continue.</p></noscript>
        <div class="widget Blog"><div class="post">
        <script type="text/template">template copy here</script>
        <noscript>
          <div dir="ltr"><span style="font-family: arial;">{para}</span></div>
          <div dir="ltr"><span style="font-family: arial;">{para}</span></div>
        </noscript>
        </div></div></body></html>"""
        doc = extract_article(page, base_url="https://example.blogspot.com/2020/05/x.html")
        self.assertIn("millions of people", doc.html)
        self.assertNotIn("enable JavaScript", doc.html)
        self.assertNotIn("template copy", doc.html)

    def test_lazy_image_noscript_replaces_placeholder(self):
        prose = "A paragraph long enough to win scoring, with commas, etc. " * 4
        page = f"""<html><body><article>
        <p>{prose}</p>
        <img src="data:image/gif;base64,R0lGOD" class="lazy" alt="x">
        <noscript><img src="https://cdn.example/real.jpg" alt="x"></noscript>
        <p>{prose}</p></article></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertEqual(doc.html.count("<img"), 1)
        self.assertIn('src="https://cdn.example/real.jpg"', doc.html)

    def test_noscript_tracking_pixel_dropped(self):
        prose = "A paragraph long enough to win scoring, with commas, etc. " * 4
        page = f"""<html><body><article>
        <p>{prose}</p>
        <noscript><img src="https://tracker.example/pixel" height="1" width="1"></noscript>
        </article></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertNotIn("tracker.example", doc.html)

    def test_jsonld_metadata_fills_gaps(self):
        # Squarespace/Wix publish author and date only as JSON-LD, and write
        # offsets without a colon ("-0400"), which fromisoformat rejects
        # before Python 3.11.
        prose = "Body prose with commas, long enough to extract cleanly here. " * 4
        page = f"""<html><head><title>Ways of Seeing — Studio</title>
        <script type="application/ld+json">{{"@context":"http://schema.org",
          "@graph":[{{"@type":"WebPage","name":"x"}},
                    {{"@type":"BlogPosting","headline":"Ways of Seeing",
                      "author":[{{"@type":"Person","name":"June Park"}}],
                      "datePublished":"2026-07-17T15:10:31-0400"}}]}}</script>
        </head><body><article><p>{prose}</p></article></body></html>"""
        doc = extract_article(page, base_url="https://studio.example/blog/ways")
        self.assertEqual(doc.author, "June Park")
        self.assertIsNotNone(doc.date)
        self.assertEqual((doc.date.year, doc.date.month, doc.date.day), (2026, 7, 17))

    def test_srcset_only_lazy_image(self):
        prose = "A paragraph long enough to win scoring, with commas, etc. " * 4
        page = f"""<html><body><article>
        <p>{prose}</p>
        <img srcset="https://cdn.example/a-640.jpg 640w, https://cdn.example/a-1280.jpg 1280w" alt="x">
        <p>{prose}</p></article></body></html>"""
        doc = extract_article(page, base_url="https://x.example/")
        self.assertIn('src="https://cdn.example/a-640.jpg"', doc.html)

    def test_plain_text_paragraphs(self):
        out = plain_text_to_html("Para one\nstill one.\n\nPara two & <tag>.")
        self.assertEqual(
            out,
            "<p>Para one still one.</p>\n<p>Para two &amp; &lt;tag&gt;.</p>",
        )


if __name__ == "__main__":
    unittest.main()
