"""Install the packed TypeScript SDK in a clean project and compile a consumer."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: smoke_typescript_sdk.py <package.tgz>")
    archive = Path(sys.argv[1]).resolve()
    if not archive.is_file():
        raise SystemExit(f"package does not exist: {archive}")
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise SystemExit("pnpm is required")
    with tempfile.TemporaryDirectory(prefix="memkit-ts-consumer-") as directory:
        root = Path(directory)
        (root / "package.json").write_text(
            json.dumps({"name": "memkit-sdk-smoke", "private": True, "type": "module"}) + "\n"
        )
        (root / "tsconfig.json").write_text(
            json.dumps(
                {
                    "compilerOptions": {
                        "module": "NodeNext",
                        "moduleResolution": "NodeNext",
                        "strict": True,
                        "noEmit": True,
                    },
                    "include": ["index.ts"],
                }
            )
            + "\n"
        )
        (root / "index.ts").write_text(
            'import { createMemkitClient } from "@memkit/sdk";\n'
            "const client = createMemkitClient({ "
            'baseUrl: "http://localhost:8077", apiKey: "secret" });\n'
            "void client;\n"
        )
        subprocess.run(  # noqa: S603
            [pnpm, "add", str(archive), "typescript@~5.9.2"],
            cwd=root,
            check=True,
        )
        subprocess.run(  # noqa: S603
            [pnpm, "exec", "tsc"],
            cwd=root,
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
