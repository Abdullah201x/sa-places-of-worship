import http.server
import ssl
import sys
import os

PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS and disable cache for local development
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

Handler.extensions_map.update({
    '.geojson': 'application/geo+json',
    '.json': 'application/json',
    '.js': 'application/javascript',
})

def run(port=PORT):
    cert_path = os.path.join(os.path.dirname(__file__), "cert.pem")
    key_path = os.path.join(os.path.dirname(__file__), "key.pem")

    if not os.path.exists(cert_path) or not os.path.exists(key_path):
        print(f"[ERROR] SSL certificates not found: {cert_path} or {key_path}")
        sys.exit(1)

    server_address = ('localhost', port)
    httpd = http.server.HTTPServer(server_address, Handler)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    httpd.socket = context.wrap_socket(httpd.socket, server_side=True)

    print(f"\n[HTTPS] Local server running at:", flush=True)
    print(f"URL: https://localhost:{port}/", flush=True)
    print(f"Press Ctrl+C to stop.\n", flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.", flush=True)
        sys.exit(0)

if __name__ == '__main__':
    p = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run(p)
