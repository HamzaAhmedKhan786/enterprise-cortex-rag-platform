"""Internal-only Prometheus exporter. No customer IDs, prompts or content labels."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from cortex import store


def render():
    with store.connection() as db:
        rows = db.execute("SELECT status,COUNT(*),COALESCE(SUM(duration),0) FROM runs GROUP BY status").fetchall()
        counts = db.execute("SELECT COUNT(*) FROM datasets").fetchone()[0]
    lines = ["# HELP cortex_datasets Current dataset count", "# TYPE cortex_datasets gauge", f"cortex_datasets {counts}",
             "# HELP cortex_runs Current retained run count by result", "# TYPE cortex_runs gauge",
             "# HELP cortex_run_duration_seconds_sum Duration sum of retained runs", "# TYPE cortex_run_duration_seconds_sum gauge"]
    for status, count, duration in rows:
        if status in {"completed", "failed", "degraded"}:
            lines.extend([f'cortex_runs{{status="{status}"}} {count}', f'cortex_run_duration_seconds_sum{{status="{status}"}} {duration}'])
    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/metrics", "/health"}:
            self.send_error(404)
            return
        body = render().encode() if self.path == "/metrics" else b"ok\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    store.initialize()
    HTTPServer((os.getenv("METRICS_HOST", "127.0.0.1"), 9108), Handler).serve_forever()
