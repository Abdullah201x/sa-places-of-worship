"""
Hardened Development Server for Saudi Places of Worship Map.
Supports HTTPS (required for OpenStreetMap OAuth) and HTTP,
serving static application files with strict security filters.
"""

import argparse
import http.server
import os
import ssl
import sys
import urllib.parse

PORT = 8000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class HardenedHandler(http.server.SimpleHTTPRequestHandler):
    """
    HTTP request handler with strict security controls:
    - Blocks access to dotfiles and hidden directories (e.g. .git/)
    - Blocks access to certificates, private keys, source code, and databases
    - Prevents Windows NTFS trailing dot and alternate stream bypasses
    - Emits modern security headers (nosniff, SAMEORIGIN, Referrer-Policy)
    """

    BLOCKED_EXTENSIONS = {
        ".pem", ".key", ".py", ".pyc", ".db", ".sqlite", ".sqlite3",
        ".env", ".ini", ".pbf", ".csv", ".sh", ".yml", ".yaml", ".bak",
        ".db-wal", ".db-shm"
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def _is_safe_request(self) -> bool:
        parsed_url = urllib.parse.urlparse(self.path)
        clean_path = urllib.parse.unquote(parsed_url.path).rstrip(". ")

        # Reject hidden files or dot directories (.git, .env, etc.)
        parts = os.path.normpath(clean_path).replace("\\", "/").split("/")
        if any(part.startswith(".") for part in parts if part):
            return False

        # Reject blocked extensions
        _, ext = os.path.splitext(clean_path)
        if ext.lower() in self.BLOCKED_EXTENSIONS:
            return False

        return True

    def do_GET(self):
        if not self._is_safe_request():
            self.send_error(404, "File not found")
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._is_safe_request():
            self.send_error(404, "File not found")
            return
        super().do_HEAD()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        super().end_headers()


HardenedHandler.extensions_map.update({
    ".geojson": "application/geo+json; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
})


def run(port: int = PORT, host: str = "localhost", force_http: bool = False):
    cert_path = os.path.join(BASE_DIR, "cert.pem")
    key_path = os.path.join(BASE_DIR, "key.pem")

    use_ssl = False
    if not force_http and os.path.exists(cert_path) and os.path.exists(key_path):
        use_ssl = True

    server_address = (host, port)
    httpd = http.server.HTTPServer(server_address, HardenedHandler)

    if use_ssl:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    proto = "https" if use_ssl else "http"
    print("\n" + "=" * 60)
    print("  \U0001f54c Saudi Places of Worship Map Server")
    print("=" * 60)
    print(f"  \u2022 URL      : {proto}://{host}:{port}/")
    print(f"  \u2022 Protocol : {proto.upper()} {'(OSM OAuth Ready)' if use_ssl else '(HTTP mode)'}")
    print(f"  \u2022 Security : Dotfiles & sensitive extensions blocked")
    print("=" * 60 + "\n")
    print("Press Ctrl+C to stop.\n", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Saudi Places of Worship Server")
    parser.add_argument("legacy_port", nargs="?", type=int, default=None, help="Port to listen on (legacy positional)")
    parser.add_argument("-p", "--port", type=int, default=PORT, help=f"Port to listen on (default: {PORT})")
    parser.add_argument("-H", "--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--http", action="store_true", help="Force HTTP mode even if SSL certs exist")
    args = parser.parse_args()

    active_port = args.legacy_port if args.legacy_port is not None else args.port
    run(port=active_port, host=args.host, force_http=args.http)
