#!/usr/bin/env python3
"""Run `dagger mcp` with a clean MCP stdout stream."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading


def main() -> int:
    cmd = ["dagger", "--silent", "mcp", "--stdio", *sys.argv[1:]]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def forward_signal(signum: int, _frame: object) -> None:
        if proc.poll() is None:
            proc.send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, forward_signal)

    def copy_stdin() -> None:
        try:
            while True:
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    break
                proc.stdin.write(chunk)
                proc.stdin.flush()
        finally:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass

    def copy_stderr() -> None:
        for line in proc.stderr:
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()

    threading.Thread(target=copy_stdin, daemon=True).start()
    threading.Thread(target=copy_stderr, daemon=True).start()

    marker = b'{"jsonrpc"'
    buffer = b""

    while True:
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            break
        buffer += chunk

        while buffer:
            json_start = buffer.find(marker)
            if json_start == -1:
                flush_len = max(0, len(buffer) - len(marker) + 1)
                if flush_len:
                    sys.stderr.buffer.write(buffer[:flush_len])
                    sys.stderr.buffer.flush()
                    buffer = buffer[flush_len:]
                break

            if json_start:
                sys.stderr.buffer.write(buffer[:json_start])
                sys.stderr.buffer.flush()
                buffer = buffer[json_start:]

            newline = buffer.find(b"\n")
            if newline == -1:
                break

            sys.stdout.buffer.write(buffer[: newline + 1])
            sys.stdout.buffer.flush()
            buffer = buffer[newline + 1 :]

    if buffer:
        if buffer.startswith(marker):
            sys.stdout.buffer.write(buffer)
            sys.stdout.buffer.flush()
        else:
            sys.stderr.buffer.write(buffer)
            sys.stderr.buffer.flush()

    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
