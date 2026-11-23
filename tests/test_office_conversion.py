import unittest

from office_conversion import InvalidPdfOutput, OutputTooLarge, read_limited_pdf_response


class FakeStreamingResponse:
    def __init__(self, chunks, content_length=None):
        self.chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)

    async def aiter_bytes(self):
        for chunk in self.chunks:
            yield chunk


class OfficeConversionResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_reads_valid_pdf_in_chunks(self):
        response = FakeStreamingResponse([b"%PDF-", b"1.7\nbody"])
        self.assertEqual(await read_limited_pdf_response(response, 64), b"%PDF-1.7\nbody")

    async def test_rejects_oversized_content_length_before_reading(self):
        response = FakeStreamingResponse([b"%PDF-1.7"], content_length=100)
        with self.assertRaises(OutputTooLarge):
            await read_limited_pdf_response(response, 32)

    async def test_rejects_stream_that_exceeds_limit(self):
        response = FakeStreamingResponse([b"%PDF-1234", b"56789"])
        with self.assertRaises(OutputTooLarge):
            await read_limited_pdf_response(response, 12)

    async def test_rejects_non_pdf_response(self):
        response = FakeStreamingResponse([b"not a pdf"])
        with self.assertRaises(InvalidPdfOutput):
            await read_limited_pdf_response(response, 64)


if __name__ == "__main__":
    unittest.main()
