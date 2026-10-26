"""
Unified server runner for Saudi Places of Worship Map.
Supports HTTPS (required for OpenStreetMap OAuth) and HTTP,
serving both the REST backend API and the frontend application.
"""

import argparse
import os
import ssl
import sys
from werkzeug.serving import run_simple

from common import configure_utf8_output
from backend import create_app
from backend.config import Config

configure_utf8_output()


def main():
    parser = argparse.ArgumentParser(description="Saudi Places of Worship Server")
    parser.add_argument("-p", "--port", type=int, default=Config.DEFAULT_PORT, help="Port to listen on (default: 8000)")
    parser.add_argument("-H", "--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--http", action="store_true", help="Force HTTP mode even if SSL certs exist")
    args = parser.parse_args()

    app = create_app()

    use_ssl = False
    ssl_context = None

    if not args.http:
        cert_exists = os.path.exists(Config.CERT_PATH)
        key_exists = os.path.exists(Config.KEY_PATH)

        if cert_exists and key_exists:
            try:
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ssl_context.load_cert_chain(certfile=Config.CERT_PATH, keyfile=Config.KEY_PATH)
                use_ssl = True
            except Exception as e:
                print(f"[WARN] Failed to configure SSL context: {e}. Falling back to HTTP.")
                use_ssl = False
        else:
            print("[INFO] SSL certificates (cert.pem, key.pem) not found. Running in HTTP mode.")

    proto = "https" if use_ssl else "http"
    url = f"{proto}://{args.host}:{args.port}/"
    docs_url = f"{proto}://{args.host}:{args.port}/api/docs"

    print("\n" + "=" * 65)
    print("  🕌 Saudi Places of Worship — Full Backend & Web Server")
    print("=" * 65)
    print(f"  • Frontend URL : {url}")
    print(f"  • REST API Docs: {docs_url}")
    print(f"  • Protocol     : {proto.upper()} {'(OSM OAuth Ready)' if use_ssl else ''}")
    print(f"  • Database     : SQLite ({Config.DB_PATH})")
    print("=" * 65 + "\n")

    run_simple(
        args.host,
        args.port,
        app,
        use_reloader=False,
        use_debugger=False,
        ssl_context=ssl_context,
    )


if __name__ == "__main__":
    main()
