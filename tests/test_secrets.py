import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_credentials_in_trackable_files():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "check_no_secrets.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_env_example_has_placeholders_only():
    text = open(os.path.join(ROOT, ".env.example"), encoding="utf-8").read()
    for line in text.splitlines():
        if line.startswith(("LLM_API_KEY=", "LLM_BASE_URL=", "LLM_MODEL=")):
            assert line.split("=", 1)[1] == "", line


def test_dotenv_is_ignored():
    r = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", ".env"])
    assert r.returncode == 0
