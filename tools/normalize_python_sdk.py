"""Apply Memkit's API-key contract to openapi-python-client output."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "sdk" / "python" / "memkit_client" / "client.py"
README = ROOT / "sdk" / "python" / "README.md"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"generator output changed; expected text absent from {path}")
    path.write_text(text.replace(old, new, 1))


def main() -> int:
    replace_once(CLIENT, 'prefix: str = "Bearer"', 'prefix: str = ""')
    replace_once(
        CLIENT,
        'auth_header_name: str = "Authorization"',
        'auth_header_name: str = "X-API-Key"',
    )
    marker = "`AuthenticatedClient` sends the token in Memkit's required `X-API-Key` header."
    readme = README.read_text()
    if marker not in readme:
        needle = 'client = AuthenticatedClient(base_url="https://api.example.com", token="SuperSecretToken")\n```'
        if needle not in readme:
            raise RuntimeError("generator README template changed")
        README.write_text(readme.replace(needle, f"{needle}\n\n{marker}", 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
