import tempfile
import unittest
from pathlib import Path

from app.process_lock import ProcessLock


class ProcessLockTests(unittest.TestCase):
    def test_rejects_second_instance_and_releases_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "aurum.lock"
            first, second = ProcessLock(path), ProcessLock(path)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
