"""Deployment image checks for local Python modules imported at startup."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerRuntimeFilesTests(unittest.TestCase):
    def test_all_local_main_modules_are_copied_into_both_images(self):
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        imported = set(re.findall(r"^from ([a-zA-Z_][a-zA-Z0-9_]*) import ", main_source, re.M))
        stdlib_and_external = {
            "__future__", "asyncio", "io", "json", "math", "os", "re", "shutil",
            "tempfile", "threading", "time", "collections", "typing", "httpx",
            "cv2", "numpy", "pytesseract", "pymupdf", "fastapi", "pydantic",
            "PIL", "starlette",
        }
        local_modules = imported - stdlib_and_external

        for dockerfile_name in ("Dockerfile", "Dockerfile.free"):
            dockerfile = (ROOT / dockerfile_name).read_text(encoding="utf-8")
            copied = set()
            for line in dockerfile.splitlines():
                if line.strip().startswith("COPY "):
                    copied.update(Path(token).name for token in line.split()[1:-1])
            with self.subTest(dockerfile=dockerfile_name):
                self.assertTrue(
                    local_modules.issubset(copied),
                    f"{dockerfile_name} is missing local modules: {sorted(local_modules - copied)}",
                )


if __name__ == "__main__":
    unittest.main()
