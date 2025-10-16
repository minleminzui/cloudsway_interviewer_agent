# nocache_server.py
import http.server, socketserver, argparse, os

class NoCacheRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--dir", default=".")
    args = ap.parse_args()
    os.chdir(args.dir)
    with socketserver.TCPServer(("127.0.0.1", args.port), NoCacheRequestHandler) as httpd:
        print(f"Serving on http://127.0.0.1:{args.port} (no cache)")
        httpd.serve_forever()

if __name__ == "__main__":
    main()
