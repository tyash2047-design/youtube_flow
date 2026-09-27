import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import yaml
from dotenv import load_dotenv
from scheduler.runner import PipelineRunner
from utils.logger import logger

load_dotenv()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "healthy", "service": "YouTube Shorts 24/7 Pipeline"}')

    def log_message(self, format, *args):
        pass  # Suppress health check access logs

def start_http_health_server(port: int):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        logger.info(f"Health check HTTP server listening on port {port} for Render")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Could not bind HTTP server to port {port}: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    # Start health check server on background thread so Render detects active web service
    http_thread = threading.Thread(target=start_http_health_server, args=(port,), daemon=True)
    http_thread.start()

    # Launch autonomous 24/7 YouTube Shorts pipeline
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    runner = PipelineRunner(config)
    runner.start_24_7()
