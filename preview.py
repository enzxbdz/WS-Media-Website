"""Serve the static site locally with its deployment headers and media ranges."""

import argparse
import re
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


SITE = Path(__file__).resolve().parent / "site"
HEADERS = [
    tuple(line.strip().split(": ", 1))
    for line in (SITE / "_headers").read_text(encoding="utf-8").splitlines()
    if line.startswith("  ")
]


class PreviewHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".avif": "image/avif",
        ".css": "text/css",
        ".js": "text/javascript",
        ".mp4": "video/mp4",
        ".vtt": "text/vtt",
    }

    def end_headers(self):
        for name, value in HEADERS:
            self.send_header(name, value)
        if urlsplit(self.path).path.endswith(".mp4"):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def list_directory(self, path):
        self.send_error(404, "File not found")
        return None

    def send_head(self):
        self.media_range = None
        requested = self.headers.get("Range")
        path = Path(self.translate_path(self.path))
        if not requested or path.suffix != ".mp4" or not path.is_file():
            return super().send_head()

        size = path.stat().st_size
        bounds = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
        start, end = 0, -1
        if bounds:
            first, last = bounds.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif last:
                start, end = max(0, size - int(last)), size - 1

        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None

        stream = path.open("rb")
        self.media_range = start, end - start + 1
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self.media_range[1]))
        self.end_headers()
        return stream

    def copyfile(self, source, outputfile):
        if self.media_range is None:
            return super().copyfile(source, outputfile)

        start, remaining = self.media_range
        source.seek(start)
        while remaining:
            chunk = source.read(min(remaining, 64 * 1024))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4174)
    arguments = parser.parse_args()
    handler = partial(PreviewHandler, directory=SITE)
    with ThreadingHTTPServer((arguments.bind, arguments.port), handler) as server:
        print(f"Preview running at http://{arguments.bind}:{server.server_port}/", flush=True)
        server.serve_forever()
