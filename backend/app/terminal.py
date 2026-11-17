from __future__ import annotations

import queue
import subprocess
import threading
from typing import Final


_SENTINEL: Final = object()


class TerminalSession:
    """Bridge one browser WebSocket to one Docker shell process."""

    def __init__(self, container_name: str) -> None:
        self.output: queue.Queue[bytes | object] = queue.Queue()
        self.process = subprocess.Popen(
            ["docker", "exec", "-i", container_name, "sh", "-i"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        try:
            for chunk in iter(lambda: self.process.stdout.read(4096), b""):
                self.output.put(chunk)
        finally:
            self.output.put(_SENTINEL)

    def write(self, command: str) -> None:
        if self.process.poll() is not None:
            raise RuntimeError("terminal session is closed")
        if self.process.stdin is None:
            raise RuntimeError("terminal input is unavailable")
        self.process.stdin.write((command.rstrip("\n") + "\n").encode())
        self.process.stdin.flush()

    def drain(self) -> list[bytes]:
        chunks: list[bytes] = []
        while True:
            try:
                item = self.output.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                continue
            chunks.append(item)
        return chunks

    def close(self) -> None:
        if self.process.poll() is None:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.process.stdout:
            self.process.stdout.close()
