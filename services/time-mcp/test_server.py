import unittest
from datetime import UTC, datetime

from server import convert_timestamp, current_time


class TimeToolTests(unittest.TestCase):
    def test_current_time_uses_requested_zone(self) -> None:
        result = current_time("Europe/Moscow", now=datetime(2026, 8, 17, 9, 30, tzinfo=UTC))
        self.assertEqual(result["timestamp"], "2026-08-17T12:30:00+03:00")
        self.assertEqual(result["utc_offset_seconds"], 10800)

    def test_converts_naive_local_time(self) -> None:
        result = convert_timestamp("2026-08-17T12:30:00", "Europe/Moscow", "UTC")
        self.assertEqual(result["timestamp"], "2026-08-17T09:30:00+00:00")

    def test_converts_explicit_offset(self) -> None:
        result = convert_timestamp(
            "2026-08-17T12:30:00+03:00", "Europe/Moscow", "America/New_York"
        )
        self.assertEqual(result["timestamp"], "2026-08-17T05:30:00-04:00")

    def test_rejects_ambiguous_local_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            convert_timestamp("2026-11-01T01:30:00", "America/New_York", "UTC")

    def test_rejects_nonexistent_local_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "not a valid"):
            convert_timestamp("2026-03-08T02:30:00", "America/New_York", "UTC")

    def test_rejects_unknown_zone(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown IANA timezone"):
            current_time("Mars/Olympus_Mons")


if __name__ == "__main__":
    unittest.main()
