#!/usr/bin/env python3
"""Verify admin-password log exposure with a synthetic credential only."""

import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))
from fake_client import build_handshake, recv_framed, write_cfg, wstr_a  # noqa: E402


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-redacted", action="store_true")
    args = parser.parse_args()
    secret = "AUDIT-SYNTHETIC-NOT-REAL-63b4d2"
    wrong = "AUDIT-SYNTHETIC-BAD-796e17"
    tcp_port = free_port(socket.SOCK_STREAM)
    udp_port = free_port(socket.SOCK_DGRAM)
    with tempfile.TemporaryDirectory(prefix="accd-secret-audit-") as tmp:
        write_cfg(tmp, tcp_port, udp_port)
        settings_path = os.path.join(tmp, "settings.json")
        with open(settings_path, encoding="utf-8") as f:
            settings = json.load(f)
        settings["adminPassword"] = secret
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f)
        log_path = os.path.join(tmp, "server.log")
        with open(log_path, "wb") as log:
            proc = subprocess.Popen(
                [os.path.abspath("accd"), tmp], cwd=tmp, stdout=log,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 5
                while True:
                    try:
                        sock = socket.create_connection(("127.0.0.1", tcp_port), timeout=0.2)
                        break
                    except OSError:
                        if proc.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError("disposable server failed to listen")
                        time.sleep(0.05)
                with sock:
                    sock.sendall(build_handshake())
                    welcome, _ = recv_framed(sock)
                    if welcome[:1] != b"\x0b":
                        raise RuntimeError("synthetic handshake rejected")
                    for attempted in (wrong, secret):
                        body = b"\x2a" + wstr_a("/admin " + attempted) + struct.pack("<i", 0)
                        sock.sendall(struct.pack("<H", len(body)) + body)
                        time.sleep(1.1)
                    normal = b"\x2a" + wstr_a("AUDIT-NORMAL-CHAT") + struct.pack("<i", 0)
                    sock.sendall(struct.pack("<H", len(normal)) + normal)
                    time.sleep(0.2)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=3)
        with open(log_path, "r", errors="replace") as f:
            log_text = f.read()
        exposed = secret in log_text
        wrong_exposed = wrong in log_text
        elevated = "elevated to admin" in log_text
        normal_logged = "AUDIT-NORMAL-CHAT" in log_text
        print("synthetic_admin_login_succeeded=" + str(elevated))
        print("synthetic_admin_password_in_log=" + str(exposed))
        print("synthetic_failed_password_in_log=" + str(wrong_exposed))
        print("normal_chat_still_logged=" + str(normal_logged))
        if args.expect_redacted:
            return 0 if elevated and normal_logged and not exposed and not wrong_exposed else 1
        return 2 if exposed and wrong_exposed and elevated and normal_logged else 1


if __name__ == "__main__":
    raise SystemExit(main())
