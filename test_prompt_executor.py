import subprocess
import unittest
from unittest.mock import patch

from PromptExecutor import PromptExecutionError, run_codex


class RunCodexTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_empty_output(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch("PromptExecutor.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(PromptExecutionError, "empty response"):
                await run_codex("Do something")

    async def test_rejects_nonzero_exit(self):
        completed = subprocess.CompletedProcess([], 1, stdout="", stderr="failure")
        with patch("PromptExecutor.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(PromptExecutionError, "exit code 1"):
                await run_codex("Do something")

    async def test_returns_completed_output(self):
        def completed_run(command, **kwargs):
            self.assertNotIn("--full-auto", command)
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            output_path = command[command.index("--output-last-message") + 1]
            with open(output_path, "w") as output_file:
                output_file.write("finished response")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch("PromptExecutor.subprocess.run", side_effect=completed_run):
            self.assertEqual(await run_codex("Do something"), "finished response")


if __name__ == "__main__":
    unittest.main()
