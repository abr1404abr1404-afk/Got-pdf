import unittest

from request_limits import SlidingWindowRateLimiter


class SlidingWindowRateLimiterTests(unittest.TestCase):
    def test_allows_up_to_limit_and_blocks_next_request(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("client", 2, 60, now=10))
        self.assertTrue(limiter.allow("client", 2, 60, now=11))
        self.assertFalse(limiter.allow("client", 2, 60, now=12))

    def test_expired_events_are_removed(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("client", 1, 10, now=1))
        self.assertFalse(limiter.allow("client", 1, 10, now=5))
        self.assertTrue(limiter.allow("client", 1, 10, now=11))

    def test_keys_are_isolated(self):
        limiter = SlidingWindowRateLimiter()
        self.assertTrue(limiter.allow("a", 1, 60, now=1))
        self.assertTrue(limiter.allow("b", 1, 60, now=1))

    def test_key_storage_is_bounded(self):
        limiter = SlidingWindowRateLimiter(max_keys=2)
        for index in range(10):
            self.assertTrue(limiter.allow(f"client-{index}", 1, 60, now=1))
        self.assertLessEqual(len(limiter._events), 2)

    def test_invalid_limits_are_rejected(self):
        limiter = SlidingWindowRateLimiter()
        with self.assertRaises(ValueError):
            limiter.allow("client", 0, 60, now=1)


if __name__ == "__main__":
    unittest.main()
