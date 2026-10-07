"""Docker entrypoint: migrate then start API."""

import subprocess
import sys


def main() -> None:
    print("Running migrations...", flush=True)
    subprocess.check_call([sys.executable, "-m", "alembic", "upgrade", "head"])
    print("Starting API...", flush=True)
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ]
    )


if __name__ == "__main__":
    main()
