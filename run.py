"""Unified launcher for LegalEase FastAPI backend and Streamlit frontend."""

import argparse
from pathlib import Path
import subprocess
import sys
import time


ROOT_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch LegalEase backend and frontend.")
    parser.add_argument("--backend-only", action="store_true", help="Start only the FastAPI server.")
    parser.add_argument("--frontend-only", action="store_true", help="Start only the Streamlit UI.")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--ui-port", type=int, default=8501)
    args = parser.parse_args()

    procs: list[subprocess.Popen] = []
    try:
        if not args.frontend_only:
            backend_cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.main:app",
                "--host",
                args.api_host,
                "--port",
                str(args.api_port),
            ]
            print(f"Starting FastAPI backend on http://{args.api_host}:{args.api_port} ...")
            procs.append(subprocess.Popen(backend_cmd, cwd=str(ROOT_DIR)))
            time.sleep(1.5)

        if not args.backend_only:
            frontend_cmd = [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT_DIR / "frontend" / "app.py"),
                "--server.port",
                str(args.ui_port),
            ]
            print(f"Starting Streamlit frontend on http://localhost:{args.ui_port} ...")
            procs.append(subprocess.Popen(frontend_cmd, cwd=str(ROOT_DIR)))

        while procs:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    return ret
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down LegalEase...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

