#!/usr/bin/env python3
"""
Smoke test: two drivers join, one sends player chat, and both must get
the 0x2b relay with the message unchanged.

Covers a short message, one past the 35 code points accd used to cut
at, non-ASCII text, and the 254 code point ceiling of the str_a
writer. Invoked from `make test`. Exits 0 on success, non-zero on
any failure.
"""

import os
import select
import signal
import socket
import struct
import subprocess
import tempfile
import time

from fake_client import Reader, build_car_info, build_driver_info, wstr_a
from smoke_handshake import ACCD_PROTOCOL_VERSION, TCP_PORT, fail, write_cfg

SAMPLES = [
    "Hello",
    "A message longer than thirty-five characters must remain intact.",
    "Unicode stays intact: äöü ÄÖÜ ß",
    "x" * 254,
]


def frame(body):
    return struct.pack("<H", len(body)) + body


def join(steam, race_number):
    body = bytes([0x09])
    body += struct.pack("<H", ACCD_PROTOCOL_VERSION)
    body += wstr_a("")
    body += build_driver_info(steam=steam)
    body += bytes(8)
    body += build_car_info(race_number=race_number)
    return frame(body)


def collect(proc, socks, bufs, duration):
    """Read frames for `duration` seconds, return (sock, text) per 0x2b."""
    got = []
    end = time.monotonic() + duration
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return got
        if proc.poll() is not None:
            fail(f"accd exited with status {proc.returncode}")
        ready, _, _ = select.select(socks, [], [], left)
        for sock in ready:
            chunk = sock.recv(65536)
            if not chunk:
                fail("server closed a client connection")
            bufs[sock] += chunk
            while len(bufs[sock]) >= 2:
                n = struct.unpack_from("<H", bufs[sock])[0]
                if len(bufs[sock]) < 2 + n:
                    break
                pkt = bufs[sock][2 : 2 + n]
                bufs[sock] = bufs[sock][2 + n :]
                if pkt and pkt[0] == 0x2B:
                    r = Reader(pkt)
                    r.u8()
                    r.fmt_a()  # sender
                    got.append((sock, r.fmt_a()))


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-chat-") as tmp:
        write_cfg(tmp)
        proc = subprocess.Popen(
            [accd_bin, tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        socks = []
        bufs = {}
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

            for i in range(2):
                sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
                socks.append(sock)
                bufs[sock] = b""
                sock.sendall(join(f"S7656119900000000{i}", 90 + i))
                collect(proc, socks, bufs, 0.2)

            for text in SAMPLES:
                msg = bytes([0x2A]) + wstr_a(text) + struct.pack("<i", 0)
                socks[0].sendall(frame(msg))
                got = collect(proc, socks, bufs, 0.3)
                ok = {sock for sock, body in got if body == text}
                if ok != set(socks):
                    fail(f"{len(text)} code point message not relayed intact")
            print("PASS: chat relayed intact to both clients")
        finally:
            for sock in socks:
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
