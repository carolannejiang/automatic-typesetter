import datetime
import unittest

from bookformatter.models import Book, BookMeta, Chapter, copyright_lines
from bookformatter.printbook import build_print_html


class CopyrightLinesTests(unittest.TestCase):
    def test_full_meta(self):
        book = Book(meta=BookMeta(title="T", author="A. Author",
                                  rights="CC BY-SA 4.0", date="2024-05-01",
                                  source_url="https://blog.example"))
        self.assertEqual(copyright_lines(book), [
            "Copyright © 2024 A. Author. All rights reserved.",
            "CC BY-SA 4.0",
            "Originally published at https://blog.example.",
            "Produced with bookformatter.",
        ])

    def test_missing_date_falls_back_to_current_year(self):
        # The print writer used to render "Copyright ©  Author" (empty year)
        # while EPUB/IDML used the current year; all three now share this.
        book = Book(meta=BookMeta(title="T", author="A. Author"))
        year = str(datetime.date.today().year)
        self.assertEqual(copyright_lines(book)[0],
                         f"Copyright © {year} A. Author. All rights reserved.")

    def test_print_html_carries_shared_lines(self):
        book = Book(meta=BookMeta(title="T", author="A & B", date="2024-05-01"),
                    chapters=[Chapter(title="One", html="<p>x</p>")])
        page = build_print_html(book)
        self.assertIn("Copyright © 2024 A &amp; B. All rights reserved.", page)


if __name__ == "__main__":
    unittest.main()
