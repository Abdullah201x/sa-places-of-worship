"""
Server runner for Saudi Places of Worship Map.
Delegates to the hardened development server.
"""

from serve_ssl import run, PORT
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Saudi Places of Worship Server")
    parser.add_argument("-p", "--port", type=int, default=PORT, help=f"Port to listen on (default: {PORT})")
    parser.add_argument("-H", "--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--http", action="store_true", help="Force HTTP mode even if SSL certs exist")
    args = parser.parse_args()

    run(port=args.port, host=args.host, force_http=args.http)
