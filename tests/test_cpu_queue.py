import asyncio
import unittest

from fastapi import HTTPException

import main


class CpuQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_cpu_job_waits_for_available_processing_slot(self):
        original_semaphore = main._cpu_semaphore
        original_timeout = main.CPU_QUEUE_WAIT_SECONDS
        main._cpu_semaphore = asyncio.Semaphore(0)
        main.CPU_QUEUE_WAIT_SECONDS = 1

        async def release_slot():
            await asyncio.sleep(0.02)
            main._cpu_semaphore.release()

        try:
            release_task = asyncio.create_task(release_slot())
            result = await main._run_cpu(lambda: "processed")
            await release_task
            self.assertEqual(result, "processed")
        finally:
            main._cpu_semaphore = original_semaphore
            main.CPU_QUEUE_WAIT_SECONDS = original_timeout

    async def test_cpu_queue_returns_bounded_503_after_timeout(self):
        original_semaphore = main._cpu_semaphore
        original_timeout = main.CPU_QUEUE_WAIT_SECONDS
        main._cpu_semaphore = asyncio.Semaphore(0)
        main.CPU_QUEUE_WAIT_SECONDS = 0.01
        try:
            with self.assertRaises(HTTPException) as caught:
                await main._run_cpu(lambda: "should not run")
            self.assertEqual(caught.exception.status_code, 503)
        finally:
            main._cpu_semaphore = original_semaphore
            main.CPU_QUEUE_WAIT_SECONDS = original_timeout


if __name__ == "__main__":
    unittest.main()
