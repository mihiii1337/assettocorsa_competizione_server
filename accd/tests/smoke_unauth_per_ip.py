#!/usr/bin/env python3
"""
Smoke test: one address may hold only two connections that have not
sent a handshake. A third idle connect from it is closed at once, a
driver from another loopback address still joins while the two are
pending, and once they close the first address can join again.
Invoked from `make test`. Exits 0 on success, non-zero on any
failure.
"""

import os
import signal
import socket
import subprocess
import tempfile
import time

from fake_client import build_handshake, recv_framed
from smoke_handshake import TCP_PORT, fail, write_cfg


def connect(src):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.bind((src, 0))
    sock.connect(("127.0.0.1", TCP_PORT))
    return sock


def closed_by_server(sock):
    try:
        return sock.recv(1) == b""
    except TimeoutError:
        return False
    except ConnectionResetError:
        return True


def joins(src):
    with connect(src) as sock:
        sock.sendall(build_handshake())
        welcome, _ = recv_framed(sock)
        return welcome[:1] == b"\x0b"


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-unauth-") as tmp:
        write_cfg(tmp)
        proc = subprocess.Popen(
            [accd_bin, tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        idle = []
        try:
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", TCP_PORT), timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                fail(f"accd did not listen on {TCP_PORT} within 3s")
            # Let the server reap the probe connection.
            time.sleep(0.2)

            idle = [connect("127.0.0.1") for _ in range(2)]
            time.sleep(0.2)
            for sock in idle:
                sock.settimeout(0.3)
                if closed_by_server(sock):
                    fail("an idle connection within the limit was closed")
            with connect("127.0.0.1") as third:
                third.settimeout(1)
                if not closed_by_server(third):
                    fail("third idle connection from one address kept open")

            try:
                other = joins("127.0.0.2")
            except OSError:
                other = None
                print("SKIP: 127.0.0.2 not usable as a source address")
            if other is False:
                fail("driver from another address refused")

            for sock in idle:
                sock.close()
            idle = []
            time.sleep(0.2)
            if not joins("127.0.0.1"):
                fail("address refused after its idle connections closed")
            print("PASS: pending handshakes capped per address")
        finally:
            for sock in idle:
                sock.close()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


if __name__ == "__main__":
    main()
