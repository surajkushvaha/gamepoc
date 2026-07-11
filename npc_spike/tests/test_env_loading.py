import importlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class EnvLoadingTests(unittest.TestCase):
    def test_dotenv_is_loaded_from_global_secrets_file(self):
        env_path = Path.home() / ".secrets" / ".env"
        self.assertTrue(env_path.exists(), f"Expected env file at {env_path}")

        os.environ.pop("CEREBRAS_API_KEY", None)
        import llm

        importlib.reload(llm)

        with env_path.open("r", encoding="utf-8") as handle:
            expected = None
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if key == "CEREBRAS_API_KEY":
                    expected = value
                    break

        self.assertEqual(os.environ.get("CEREBRAS_API_KEY"), expected)


if __name__ == "__main__":
    unittest.main()
