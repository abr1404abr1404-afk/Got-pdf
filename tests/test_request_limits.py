import unittest

from request_limits import SlidingWindowRateLimiter, validate_pixel_dimensions


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

    def test_pixel_dimensions_are_checked_before_decoding(self):
        self.assertEqual(validate_pixel_dimensions(100, 100, 10000), 10000)
        with self.assertRaises(ValueError):
            validate_pixel_dimensions(101, 100, 10000)
        with self.assertRaises(ValueError):
            validate_pixel_dimensions(0, 100, 10000)


if __name__ == "__main__":
    unittest.main()

class RequestBodyLimitMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def scope(headers=(), method="POST", scope_type="http"):
        return {
            "type": scope_type,
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": "/upload",
            "raw_path": b"/upload",
            "query_string": b"",
            "headers": list(headers),
            "client": ("127.0.0.1", 12345),
            "server": ("example.test", 443),
        }

    async def invoke(self, chunks, *, limit=5, headers=(), scope_type="http"):
        messages = []
        iterator = iter(chunks)
        app_called = False

        async def receive():
            try:
                body = next(iterator)
                return {"type": "http.request", "body": body, "more_body": True}
            except StopIteration:
                return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        async def app(scope, inner_receive, inner_send):
            nonlocal app_called
            app_called = True
            while True:
                message = await inner_receive()
                if not message.get("more_body", False):
                    break
            await inner_send({
                "type": "http.response.start",
                "status": 200,
                "headers": [],
            })
            await inner_send({"type": "http.response.body", "body": b"ok"})

        middleware = RequestBodyLimitMiddleware(app, max_body_bytes=limit)
        await middleware(self.scope(headers=headers, scope_type=scope_type), receive, send)
        return messages, app_called

    async def test_rejects_content_length_before_calling_application(self):
        messages, app_called = await self.invoke(
            [b"ignored"],
            headers=[(b"content-length", b"6")],
        )
        self.assertFalse(app_called)
        self.assertEqual(messages[0]["status"], 413)
        self.assertIn(b"no-store", dict(messages[0]["headers"])[b"cache-control"])

    async def test_rejects_chunked_body_without_content_length(self):
        messages, app_called = await self.invoke([b"123", b"456"])
        self.assertTrue(app_called)
        self.assertEqual(messages[0]["status"], 413)
        self.assertEqual(messages[-1]["type"], "http.response.body")

    async def test_accepts_body_exactly_at_limit(self):
        messages, app_called = await self.invoke([b"12", b"345"])
        self.assertTrue(app_called)
        self.assertEqual(messages[0]["status"], 200)

    async def test_passes_non_http_scopes_through(self):
        messages, app_called = await self.invoke(
            [],
            scope_type="lifespan",
        )
        self.assertTrue(app_called)
        self.assertEqual(messages, [])


