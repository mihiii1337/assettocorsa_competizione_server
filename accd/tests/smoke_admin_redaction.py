#!/usr/bin/env python3
"""
Smoke test: /admin attempts must not leave the password in the log.

One driver joins, sends /admin with a wrong password, then with the
right one, then a plain chat line. The right password must elevate,
neither password may appear in the server output and the plain line
must still be logged. Invoked from `make test`. Exits 0 on success,
non-zero on any failure.
"""

import json
import os
import signal
import socket
import struct
import subprocess
import tempfile
import time

from fake_client import build_handshake, recv_framed, wstr_a
from smoke_handshake import TCP_PORT, fail, write_cfg

SECRET = "smoke-admin-secret"
WRONG = "smoke-admin-wrong"
PLAIN = "smoke plain chat"


def chat(text):
    body = bytes([0x2A]) + wstr_a(text) + struct.pack("<i", 0)
    return struct.pack("<H", len(body)) + body


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-admin-") as tmp:
        write_cfg(tmp)
        settings = os.path.join(tmp, "settings.json")
        with open(settings) as f:
            cfg = json.load(f)
        cfg["adminPassword"] = SECRET
        with open(settings, "w") as f:
            json.dump(cfg, f)

        log_path = os.path.join(tmp, "server.log")
        with open(log_path, "wb") as log:
            proc = subprocess.Popen(
                [accd_bin, tmp],
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    sock = socket.create_connection(
                        ("127.0.0.1", TCP_PORT), timeout=0.2
                    )
                    break
                except OSError:
                    time.sleep(0.05)
            else:
                fail(f"accd did not listen on {TCP_PORT} within 3s")

            with sock:
                sock.settimeout(2)
                sock.sendall(build_handshake())
                welcome, _ = recv_framed(sock)
                if welcome[:1] != b"\x0b":
                    fail("handshake rejected")
                # /admin attempts are throttled to one per second per IP.
                sock.sendall(chat("/admin " + WRONG))
                time.sleep(1.1)
                sock.sendall(chat("/admin " + SECRET))
                time.sleep(0.2)
                sock.sendall(chat(PLAIN))
                time.sleep(0.2)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        with open(log_path, errors="replace") as f:
            text = f.read()
        if "elevated to admin" not in text:
            fail("right password did not elevate")
        if SECRET in text:
            fail("right password found in the log")
        if WRONG in text:
            fail("wrong password found in the log")
        if PLAIN not in text:
            fail("plain chat no longer logged")
        print("PASS: /admin passwords kept out of the log, plain chat logged")


if __name__ == "__main__":
    main()
