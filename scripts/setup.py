from __future__ import annotations

import secrets
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
ENV_FILE = ROOT / ".env"

PLACEHOLDER_VALUES = {
    "replace-with-a-long-random-password": "POSTGRES_PASSWORD",
    "replace-with-a-long-random-token": "NETLAB_WORKER_TOKEN",
    "replace-with-a-long-random-bootstrap-token": "NETLAB_BOOTSTRAP_TOKEN",
}


def random_secret() -> str:
    return secrets.token_urlsafe(32)


def setup() -> bool:
    if not ENV_EXAMPLE.is_file():
        print("Missing .env.example", file=sys.stderr)
        return False

    if ENV_FILE.exists():
        print(".env already exists; leaving its values unchanged")
        return True

    content = ENV_EXAMPLE.read_text(encoding="utf-8")
    replacements: dict[str, str] = {}
    for placeholder, name in PLACEHOLDER_VALUES.items():
        if placeholder in content:
            replacements[placeholder] = random_secret()

    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)

    ENV_FILE.write_text(content, encoding="utf-8")
    ENV_FILE.chmod(0o600)
    print(".env created with cryptographically random local secrets")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if setup() else 1)
