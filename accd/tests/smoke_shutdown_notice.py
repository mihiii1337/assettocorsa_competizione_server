#!/usr/bin/env python3
"""
Smoke test: three drivers join and accd gets SIGTERM. Every driver
must receive the "Server is shutting down" notice (0x2b from "Server",
chat type 4) before its connection closes, and accd must exit 0.
Invoked from `make test`. Exits 0 on success, non-zero on any failure.
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

NOTICE = "Server is shutting down, you will be disconnected"
DRIVERS = 3


def join(steam, race_number):
    body = bytes([0x09])
    body += struct.pack("<H", ACCD_PROTOCOL_VERSION)
    body += wstr_a("")
    body += build_driver_info(steam=steam)
    body += bytes(8)
    body += build_car_info(race_number=race_number)
    return struct.pack("<H", len(body)) + body


def notices(buf):
    """Return the (sender, text, chat type) of every 0x2b in buf."""
    out = []
    while len(buf) >= 2:
        n = struct.unpack_from("<H", buf)[0]
        if len(buf) < 2 + n:
            break
        pkt = buf[2 : 2 + n]
        buf = buf[2 + n :]
        if pkt and pkt[0] == 0x2B:
            r = Reader(pkt)
            r.u8()
            sender = r.fmt_a()
            text = r.fmt_a()
            r.u32()
            out.append((sender, text, r.u8()))
    return out


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    accd_bin = os.path.join(os.path.dirname(script_dir), "accd")
    if not os.access(accd_bin, os.X_OK):
        fail(f"accd binary not found at {accd_bin}")

    with tempfile.TemporaryDirectory(prefix="accd-shutdown-") as tmp:
        write_cfg(tmp)
        proc = subprocess.Popen(
            [accd_bin, tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        socks = []
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

            for i in range(DRIVERS):
                sock = socket.create_connection(("127.0.0.1", TCP_PORT), timeout=2)
                sock.sendall(join(f"S7656119900000000{i}", 90 + i))
                socks.append(sock)
            time.sleep(0.5)

            proc.send_signal(signal.SIGTERM)
            bufs = {sock: b"" for sock in socks}
            open_socks = set(socks)
            end = time.monotonic() + 5.0
            while open_socks and time.monotonic() < end:
                ready, _, _ = select.select(
                    list(open_socks), [], [], end - time.monotonic()
                )
                for sock in ready:
                    try:
                        chunk = sock.recv(65536)
                    except ConnectionResetError:
                        chunk = b""
                    if chunk:
                        bufs[sock] += chunk
                    else:
                        open_socks.discard(sock)
            if open_socks:
                fail("accd did not close every connection within 5s")
            for i, sock in enumerate(socks):
                if ("Server", NOTICE, 4) not in notices(bufs[sock]):
                    fail(f"driver {i} got no shutdown notice")
            try:
                status = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fail("accd did not exit after SIGTERM")
            if status != 0:
                fail(f"accd exited with status {status}")
            print("PASS: every driver gets the shutdown notice")
        finally:
            for sock in socks:
                sock.close()
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()


if __name__ == "__main__":
    main()
