import os
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import yaml
from dotenv import load_dotenv
from scheduler.runner import PipelineRunner
from database.db import Database
from utils.logger import logger

load_dotenv()

# Global database reference for status server
_db_instance = None

def get_db():
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Viral Chaos • 24/7 YouTube Shorts Command Center</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090a0f;
            --card-bg: rgba(18, 20, 29, 0.7);
            --card-border: rgba(255, 255, 255, 0.08);
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --accent-red: #ff0055;
            --accent-purple: #8b5cf6;
            --accent-cyan: #06b6d4;
            --accent-green: #10b981;
            --glow-red: rgba(255, 0, 85, 0.25);
            --glow-green: rgba(16, 185, 129, 0.25);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(255, 0, 85, 0.12) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.12) 0px, transparent 50%);
            background-attachment: fixed;
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
            min-height: 100vh;
            padding: 24px;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }

        /* Top Header */
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 20px 24px;
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .logo-badge {
            width: 44px;
            height: 44px;
            border-radius: 12px;
            background: linear-gradient(135deg, var(--accent-red), var(--accent-purple));
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 20px;
            color: #fff;
            box-shadow: 0 4px 20px var(--glow-red);
        }

        .brand-text h1 {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.02em;
        }

        .brand-text p {
            font-size: 13px;
            color: var(--text-muted);
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 16px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 9999px;
            color: #34d399;
            font-size: 13px;
            font-weight: 600;
        }

        .pulse-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #10b981;
            box-shadow: 0 0 12px #10b981;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        /* Stats Grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
        }

        .stat-card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: transform 0.2s, border-color 0.2s;
        }

        .stat-card:hover {
            transform: translateY(-2px);
            border-color: rgba(255, 255, 255, 0.16);
        }

        .stat-label {
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            font-weight: 600;
        }

        .stat-val {
            font-size: 32px;
            font-weight: 800;
            color: #fff;
            letter-spacing: -0.02em;
        }

        /* Targets Card */
        .card {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 24px;
        }

        .card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
        }

        .card-title {
            font-size: 16px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .pill-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }

        .pill {
            padding: 6px 14px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            color: #e2e8f0;
            font-size: 13px;
            font-weight: 500;
            text-decoration: none;
            transition: all 0.2s;
        }

        .pill:hover {
            background: rgba(255, 0, 85, 0.15);
            border-color: var(--accent-red);
            color: #fff;
        }

        /* Uploads Table */
        .table-wrap {
            overflow-x: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            text-align: left;
        }

        th {
            padding: 12px 16px;
            color: var(--text-muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 1px solid var(--card-border);
        }

        td {
            padding: 14px 16px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }

        .viral-score {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 6px;
            background: rgba(139, 92, 246, 0.15);
            color: #c084fc;
            font-weight: 700;
            font-size: 12px;
        }

        .btn-link {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 12px;
            border-radius: 8px;
            background: linear-gradient(135deg, #e11d48, #be123c);
            color: #fff;
            text-decoration: none;
            font-size: 12px;
            font-weight: 600;
            transition: opacity 0.2s;
        }

        .btn-link:hover {
            opacity: 0.9;
        }

        /* Terminal Window */
        .terminal {
            background: #050608;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            font-family: 'JetBrains Mono', monospace;
        }

        .terminal-header {
            background: #0d0f15;
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .traffic-lights {
            display: flex;
            gap: 6px;
        }

        .tl-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }

        .tl-red { background: #ff5f56; }
        .tl-yellow { background: #ffbd2e; }
        .tl-green { background: #27c93f; }

        .terminal-title {
            font-size: 12px;
            color: var(--text-muted);
        }

        .terminal-body {
            padding: 16px;
            height: 380px;
            overflow-y: auto;
            color: #d1d5db;
            font-size: 12px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-break: break-all;
        }

        .log-info { color: #38bdf8; }
        .log-warn { color: #fbbf24; }
        .log-err { color: #f87171; }
        .log-success { color: #34d399; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Top Nav -->
        <header>
            <div class="brand">
                <div class="logo-badge">VC</div>
                <div class="brand-text">
                    <h1>Viral Chaos • YouTube Shorts Daemon</h1>
                    <p>Autonomous 24/7 Content Scraper, AI Highlight Engine & Publisher</p>
                </div>
            </div>
            <div class="status-badge">
                <div class="pulse-dot"></div>
                <span id="daemon-status">24/7 ACTIVE</span>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Candidate Sources Scanned</div>
                <div class="stat-val" id="stat-sources">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Shorts Rendered</div>
                <div class="stat-val" id="stat-rendered">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Shorts Uploaded Today</div>
                <div class="stat-val" id="stat-uploaded" style="color: #34d399;">--</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Target Channel</div>
                <div class="stat-val" style="font-size: 20px; padding-top: 6px;">
                    <a href="https://www.youtube.com/@ViralChaos-786" target="_blank" style="color: #f43f5e; text-decoration: none;">@ViralChaos-786 ↗</a>
                </div>
            </div>
        </div>

        <!-- Target Channels -->
        <div class="card">
            <div class="card-header">
                <div class="card-title">📡 Active Source Channels (Scraped Every 4h)</div>
            </div>
            <div class="pill-group" id="channel-pills">
                <a href="https://www.youtube.com/@MrBeastGaming" target="_blank" class="pill">@MrBeastGaming</a>
                <a href="https://www.youtube.com/@MrBeast" target="_blank" class="pill">@MrBeast</a>
                <a href="https://www.youtube.com/@whistlindiesel" target="_blank" class="pill">@whistlindiesel</a>
                <a href="https://www.youtube.com/@sshhuubb" target="_blank" class="pill">Shub (@sshhuubb)</a>
                <a href="https://www.youtube.com/@SlayyPop" target="_blank" class="pill">SlayyPop (@SlayyPop)</a>
                <a href="https://www.youtube.com/@AyushBhandari" target="_blank" class="pill">Ayush Bhandari (@AyushBhandari)</a>
            </div>
        </div>

        <!-- Recent Uploads -->
        <div class="card">
            <div class="card-header">
                <div class="card-title">🚀 Recent Uploaded Shorts</div>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>Short Title</th>
                            <th>Viral Score</th>
                            <th>Uploaded</th>
                            <th>Watch on YouTube</th>
                        </tr>
                    </thead>
                    <tbody id="uploads-table-body">
                        <tr>
                            <td colspan="4" style="text-align: center; color: var(--text-muted); padding: 24px;">
                                Loading recent uploads...
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Real-time Console Log Terminal -->
        <div class="terminal">
            <div class="terminal-header">
                <div class="traffic-lights">
                    <div class="tl-dot tl-red"></div>
                    <div class="tl-dot tl-yellow"></div>
                    <div class="tl-dot tl-green"></div>
                </div>
                <div class="terminal-title">DAEMON CONSOLE OUTPUT (LIVE AUTO-REFRESH 4S)</div>
                <div style="font-size: 11px; color: var(--text-muted);">
                    <label><input type="checkbox" id="auto-scroll" checked> Auto-Scroll</label>
                </div>
            </div>
            <div class="terminal-body" id="terminal-content">Connecting to pipeline log stream...</div>
        </div>
    </div>

    <script>
        async function fetchStats() {
            try {
                const res = await fetch('/api/stats');
                if (!res.ok) return;
                const data = await res.json();
                
                document.getElementById('stat-sources').innerText = data.total_sources || '0';
                
                const clipsByStatus = data.clips_by_status || {};
                const renderedCount = (clipsByStatus['RENDERED'] || 0) + (clipsByStatus['UPLOADED'] || 0);
                document.getElementById('stat-rendered').innerText = renderedCount;
                document.getElementById('stat-uploaded').innerText = data.today_uploads || '0';

                // Populate uploads table
                const tableBody = document.getElementById('uploads-table-body');
                if (data.recent_uploads && data.recent_uploads.length > 0) {
                    tableBody.innerHTML = data.recent_uploads.map(u => `
                        <tr>
                            <td style="font-weight: 600; color: #fff;">${escapeHtml(u.title || 'Untitled Short')}</td>
                            <td><span class="viral-score">${(u.viral_score || 0).toFixed(1)}/10</span></td>
                            <td style="color: var(--text-muted); font-size: 13px;">${u.uploaded_at ? new Date(u.uploaded_at).toLocaleTimeString() : 'Recently'}</td>
                            <td>
                                <a href="${u.youtube_url}" target="_blank" class="btn-link">
                                    Watch Short ↗
                                </a>
                            </td>
                        </tr>
                    `).join('');
                } else {
                    tableBody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 24px;">No shorts uploaded yet. Daemon is currently scanning and queuing!</td></tr>`;
                }
            } catch (err) {
                console.error("Stats fetch error:", err);
            }
        }

        async function fetchLogs() {
            try {
                const res = await fetch('/api/logs');
                if (!res.ok) return;
                const data = await res.json();
                const term = document.getElementById('terminal-content');
                if (data.logs) {
                    term.innerHTML = colorizeLogs(data.logs);
                    if (document.getElementById('auto-scroll').checked) {
                        term.scrollTop = term.scrollHeight;
                    }
                }
            } catch (err) {
                console.error("Logs fetch error:", err);
            }
        }

        function colorizeLogs(lines) {
            return lines.map(line => {
                let escaped = escapeHtml(line);
                if (escaped.includes('[ERROR]') || escaped.includes('ERROR:')) {
                    return `<span class="log-err">${escaped}</span>`;
                } else if (escaped.includes('[WARNING]') || escaped.includes('WARNING:')) {
                    return `<span class="log-warn">${escaped}</span>`;
                } else if (escaped.includes('Upload successful') || escaped.includes('SUCCESS')) {
                    return `<span class="log-success">${escaped}</span>`;
                } else if (escaped.includes('[INFO]')) {
                    return `<span class="log-info">${escaped}</span>`;
                }
                return escaped;
            }).join('\\n');
        }

        function escapeHtml(str) {
            return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }

        fetchStats();
        fetchLogs();
        setInterval(fetchStats, 5000);
        setInterval(fetchLogs, 4000);
    </script>
</body>
</html>
"""

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. API: Stats endpoint
        if path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                db = get_db()
                stats = db.get_stats()
                stats["recent_uploads"] = db.get_recent_uploads(limit=10)
                self.wfile.write(json.dumps(stats).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            return

        # 2. API: Live Logs endpoint
        if path == "/api/logs":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            log_lines = []
            log_path = "data/pipeline.log"
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        all_lines = f.readlines()
                        log_lines = [l.rstrip() for l in all_lines[-120:]]
                except Exception:
                    pass
            self.wfile.write(json.dumps({"logs": log_lines}).encode("utf-8"))
            return

        # 3. Dedicated JSON health check for Render or monitoring bots
        accept_header = self.headers.get("Accept", "")
        if path in ("/health", "/api/health") or "application/json" in accept_header or "format=json" in parsed.query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy", "service": "YouTube Shorts 24/7 Pipeline"}')
            return

        # 4. Web Dashboard for human browsers
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DASHBOARD_HTML.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress HTTP access spam in logs

def start_http_health_server(port: int):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        logger.info(f"Command Center Web Dashboard listening on port {port}")
        server.serve_forever()
    except Exception as e:
        logger.warning(f"Could not bind HTTP server to port {port}: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    # Start health & dashboard server on background thread
    http_thread = threading.Thread(target=start_http_health_server, args=(port,), daemon=True)
    http_thread.start()

    # Launch autonomous 24/7 YouTube Shorts pipeline
    with open("config.yaml", "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    runner = PipelineRunner(config)
    runner.start_24_7()
