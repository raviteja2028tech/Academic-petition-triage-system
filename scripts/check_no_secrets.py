"""Fail if tracked/untracked-but-not-ignored files contain credential-looking strings, or .env is not ignored.

Usage: python scripts/check_no_secrets.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = {
    "OpenAI-style key": r"sk-[A-Za-z0-9_-]{20,}",
    "Groq key": r"gsk_[A-Za-z0-9]{20,}",
    "Google API key": r"AIza[0-9A-Za-z_-]{30,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "assigned secret": r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9/+_-]{20,}",
}
SKIP_EXT = (".pdf", ".png", ".jpg", ".sqlite3")
SELF = os.path.join("scripts", "check_no_secrets.py")


def files() -> list[str]:
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-co", "--exclude-standard", "--", "."],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and not f.lower().endswith(SKIP_EXT) and f.replace("\\", "/") != SELF.replace("\\", "/")]


def main() -> int:
    bad = []
    listing = files()
    ignored = subprocess.run(["git", "-C", ROOT, "check-ignore", "-q", ".env"], capture_output=True).returncode == 0
    if not ignored:
        bad.append(".env is not git-ignored")
    if any(os.path.basename(f) == ".env" for f in listing):
        bad.append(".env would be committed")
    for rel in listing:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for name, rx in PATTERNS.items():
            m = re.search(rx, text)
            if m:
                bad.append(f"{rel}: {name}")
    for b in bad:
        print("SECRET-CHECK FAIL:", b)
    if not bad:
        print(f"secret check ok ({len(listing)} files scanned)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
