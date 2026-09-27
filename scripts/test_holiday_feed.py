import datetime as dt
import unittest
import update_holidays as feed


class HolidayFeedTest(unittest.TestCase):
    def xml(self, rows, total=None):
        items = ''.join(f'<item><locdate>{date}</locdate><dateName>{name}</dateName><isHoliday>{flag}</isHoliday></item>' for date, name, flag in rows)
        return f'<response><header><resultCode>00</resultCode></header><body><totalCount>{len(rows) if total is None else total}</totalCount><items>{items}</items></body></response>'.encode()

    def test_rejects_truncated_and_non_holiday_years(self):
        self.assertIsNone(feed.parse_year(self.xml([('20290101', '새해', 'N')]), 2029))
        with self.assertRaises(ValueError):
            feed.parse_year(self.xml([('20290101', '새해', 'Y')], 20), 2029)
        self.assertIsNone(feed.parse_year(self.xml([('20290101', '새해', 'Y')]), 2029))

    def test_unavailable_future_never_deletes_known_year(self):
        previous = {'schema': 1, 'revision': 1, 'checkedAt': '2026-09-27', 'years': [2026],
                    'holidays': [{'date': '2026-01-01', 'name': '새해'}]}
        self.assertEqual(previous, feed.build(previous, {2026: None, 2028: None}, dt.date(2026, 9, 27)))
        result = feed.build(previous, {2028: {'2028-01-01': '새해'}}, dt.date(2026, 9, 27))
        self.assertEqual([2026, 2028], result['years'])
        self.assertGreater(result['revision'], previous['revision'])

    def test_api_error_does_not_become_empty_feed(self):
        with self.assertRaises(ValueError):
            feed.parse_year(b'<response><header><resultCode>30</resultCode></header></response>', 2026)


if __name__ == '__main__':
    unittest.main()
