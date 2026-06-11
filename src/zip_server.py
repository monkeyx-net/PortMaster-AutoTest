#!/usr/bin/env python3
"""
zip_server.py — HTTP server that serves the latest zip file from a watched folder.

Usage:
    python zip_server.py [--host HOST] [--port PORT] [--folder FOLDER]

Defaults:
    host   : 0.0.0.0
    port   : 8765
    folder : ./serve_folder
"""

import argparse
from datetime import datetime
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def log(msg: str) -> None:
    print(f"[{datetime.now().isoformat()}] {msg}")

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST      = "0.0.0.0"
DEFAULT_PORT      = 8765
DEFAULT_FOLDER    = "./serve_folder"
DISCOVERY_PORT    = 8766
DISCOVERY_INTERVAL = 5  # seconds between UDP broadcasts

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "server.json")


def load_config() -> dict:
    defaults = {"host": DEFAULT_HOST, "port": DEFAULT_PORT, "folder": DEFAULT_FOLDER}
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as fh:
            return {**defaults, **json.load(fh)}
    with open(CONFIG_FILE, "w") as fh:
        json.dump(defaults, fh, indent=2)
        fh.write("\n")
    return defaults


def _broadcast_loop(http_port: int, discovery_port: int) -> None:
    payload = json.dumps({"port": http_port}).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        while True:
            try:
                sock.sendto(payload, ("255.255.255.255", discovery_port))
            except OSError as exc:
                log(f"[server] Broadcast error: {exc}")
            time.sleep(DISCOVERY_INTERVAL)
    finally:
        sock.close()


def find_latest_zip(folder: str) -> str | None:
    """Return the path to the most-recently modified zip in *folder*, or None."""
    try:
        entries = [
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if f.lower().endswith(".zip") and os.path.isfile(os.path.join(folder, f))
        ]
    except FileNotFoundError:
        return None

    if not entries:
        return None

    return max(entries, key=os.path.getmtime)


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------
class ZipHandler(BaseHTTPRequestHandler):

    # Injected by the server startup code
    serve_folder: str = DEFAULT_FOLDER

    # ---- GET /           → list available zip (or 404)
    # ---- GET /download   → stream the zip file
    # ---- GET /status     → JSON-like status line (plain text)
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        if path in ("", "/"):
            self._handle_index()
        elif path == "/download":
            self._handle_download()
        elif path == "/status":
            self._handle_status()
        else:
            self._send_text(404, "404 Not Found\n")

    # ------------------------------------------------------------------
    def _handle_index(self):
        zip_path = find_latest_zip(self.serve_folder)
        if zip_path is None:
            self._send_text(404, "No zip file available.\n")
            return
        name = os.path.basename(zip_path)
        size = os.path.getsize(zip_path)
        body = f"Available: {name} ({size} bytes)\nDownload : GET /download\n"
        self._send_text(200, body)

    def _handle_status(self):
        zip_path = find_latest_zip(self.serve_folder)
        if zip_path is None:
            self._send_text(200, json.dumps({"status": "none"}) + "\n")
            return
        name = os.path.basename(zip_path)
        size = os.path.getsize(zip_path)
        mtime = os.path.getmtime(zip_path)
        self._send_text(200, json.dumps({"status": "available", "name": name, "size": size, "mtime": round(mtime)}) + "\n")

    def _handle_download(self):
        zip_path = find_latest_zip(self.serve_folder)
        if zip_path is None:
            self._send_text(404, "No zip file available.\n")
            return

        filename = os.path.basename(zip_path)
        size     = os.path.getsize(zip_path)

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(size))
            self.end_headers()

            with open(zip_path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)  # 64 KB chunks
                    if not chunk:
                        break
                    self.wfile.write(chunk)

            log(f"[server] Sent {filename} ({size} bytes) to {self.client_address[0]}")

        except (BrokenPipeError, ConnectionResetError):
            log(f"[server] Client {self.client_address[0]} disconnected mid-transfer.")

    # ------------------------------------------------------------------
    def _send_text(self, code: int, body: str):
        encoded = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        log(f"[server] {self.client_address[0]} - {format % args}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    config = load_config()

    parser = argparse.ArgumentParser(description="Zip-file HTTP server")
    parser.add_argument("--host",   default=config["host"],   help=f"Bind address (default: {config['host']})")
    parser.add_argument("--port",   default=config["port"],   type=int, help=f"Port (default: {config['port']})")
    parser.add_argument("--folder", default=config["folder"], help=f"Folder to watch for zip files (default: {config['folder']})")
    args = parser.parse_args()

    # Ensure the folder exists
    os.makedirs(args.folder, exist_ok=True)

    # Inject config into the handler class
    ZipHandler.serve_folder = args.folder

    t = threading.Thread(target=_broadcast_loop, args=(args.port, DISCOVERY_PORT), daemon=True)
    t.start()
    log(f"[server] Broadcasting presence on UDP port {DISCOVERY_PORT} every {DISCOVERY_INTERVAL}s")

    server = HTTPServer((args.host, args.port), ZipHandler)
    log(f"[server] Listening on {args.host}:{args.port}")
    log(f"[server] Watching folder : {os.path.abspath(args.folder)}")
    log("[server] Endpoints       : GET /  |  GET /status  |  GET /download")
    log("[server] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("[server] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
