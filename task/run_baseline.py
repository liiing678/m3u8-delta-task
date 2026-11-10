"""Run the unmodified upstream tests with their own local HTTP fixture."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]
PORT = 8112


def check_port() -> None:
    # Never attach to, or terminate, another process occupying the fixture port.
    addresses = socket.getaddrinfo("localhost", PORT, type=socket.SOCK_STREAM)
    for family, socktype, proto, _, address in addresses:
        with socket.socket(family, socktype, proto) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(address) == 0:
                raise RuntimeError(f"localhost:{PORT} is occupied; free it before running")
    # Also detect a bound socket which has not started listening yet.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # Match wsgiref's reuse policy; a finished run's TIME_WAIT is safe.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", PORT))


def main() -> int:
    check_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + str(ROOT / "tests")
    env["PYTHONUTF8"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    env["no_proxy"] = env["NO_PROXY"]
    opener = build_opener(ProxyHandler({}))
    expected = (ROOT / "tests/playlists/simple-playlist.m3u8").read_text().strip()
    with tempfile.TemporaryFile(mode="w+b") as server_output:
        server = subprocess.Popen(
            [sys.executable, "tests/m3u8server.py"],
            cwd=ROOT,
            env=env,
            stdout=server_output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                if server.poll() is not None:
                    raise RuntimeError("upstream HTTP fixture exited before becoming ready")
                try:
                    with opener.open(f"http://localhost:{PORT}/simple.m3u8", timeout=0.5) as reply:
                        content = reply.read().decode("utf-8").strip()
                    if content != expected:
                        raise RuntimeError("fixture health check returned unexpected content")
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError("upstream HTTP fixture did not become ready")
                    time.sleep(0.1)
            if server.poll() is not None:
                raise RuntimeError("upstream HTTP fixture exited during its health check")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests", "-q", *sys.argv[1:]],
                cwd=ROOT,
                env=env,
                check=False,
            )
            if result.returncode:
                server_output.seek(0)
                print(server_output.read().decode("utf-8", errors="replace"), file=sys.stderr)
            return result.returncode
        except BaseException:
            server_output.seek(0)
            print(server_output.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise
        finally:
            if server.poll() is None:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
