import unittest

from jobseeker.crawler.html_text import html_to_text


class HtmlTextTests(unittest.TestCase):
    def test_text_cleanup_handles_carriage_returns(self):
        self.assertEqual(html_to_text("<p>A</p>\r\n\r\n\r\n\u200b\r\n<p>B</p>"), "A\n\nB")
