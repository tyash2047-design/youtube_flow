import os
import sys
import argparse
import yaml

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Load environment variables
load_dotenv()

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    console = Console()
except ImportError:
    class DummyConsole:
        def print(self, *args, **kwargs):
            import re
            cleaned = re.sub(r'\[/?(?:bold|cyan|green|yellow|red|magenta|dim)[^\]]*\]', '', str(args[0]))
            print(cleaned)
    console = DummyConsole()
    Panel = None
    Table = None

from utils.logger import logger
from utils.ffmpeg_helper import get_ffmpeg_path

def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        console.print(f"[bold red]Config file not found at: {config_path}[/bold red]")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def cmd_check(config: dict):
    """Performs an environment and health audit for the pipeline."""
    from database.db import Database
    console.print(Panel.fit("[bold cyan]System & Environment Health Check[/bold cyan]") if Panel else "=== System & Environment Health Check ===")
    
    if Table:
        table = Table(title="Dependency Audit", show_header=True, header_style="bold magenta")
        table.add_column("Component", style="dim", width=25)
        table.add_column("Status", width=15)
        table.add_column("Details", width=50)
    else:
        table = None

    # 1. FFmpeg
    try:
        ffmpeg_exe = get_ffmpeg_path()
        table.add_row("FFmpeg", "[green]INSTALLED[/green]", ffmpeg_exe)
    except Exception as e:
        table.add_row("FFmpeg", "[red]MISSING[/red]", "Run: winget install Gyan.FFmpeg")

    # 2. Gemini API Key
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and len(gemini_key) > 8:
        table.add_row("Gemini API Key", "[green]CONFIGURED[/green]", f"{gemini_key[:4]}...{gemini_key[-4:]}")
    else:
        table.add_row("Gemini API Key", "[yellow]MISSING[/yellow]", "Add GEMINI_API_KEY to your .env file")

    # 3. YouTube Secrets
    paths = config.get("paths", {})
    client_secrets = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", paths.get("client_secrets_file", "./client_secrets.json"))
    token_file = paths.get("token_file", "./data/youtube_token.json")
    if os.path.exists(client_secrets):
        table.add_row("OAuth Secrets JSON", "[green]FOUND[/green]", client_secrets)
    else:
        table.add_row("OAuth Secrets JSON", "[yellow]MISSING[/yellow]", f"File not found at '{client_secrets}'")

    if os.path.exists(token_file):
        table.add_row("YouTube Auth Token", "[green]AUTHENTICATED[/green]", token_file)
    else:
        table.add_row("YouTube Auth Token", "[yellow]NOT AUTHED[/yellow]", "Run 'python main.py auth' to log in")

    # 4. Database
    db_path = paths.get("database_file", "./data/pipeline.db")
    if os.path.exists(db_path):
        table.add_row("SQLite Database", "[green]READY[/green]", db_path)
    else:
        table.add_row("SQLite Database", "[green]READY (auto-create)[/green]", db_path)

    console.print(table)

def cmd_auth(config: dict):
    """Runs the interactive YouTube OAuth2 flow and saves the refresh token."""
    from uploader.youtube_auth import YouTubeAuth
    paths = config.get("paths", {})
    client_secrets = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", paths.get("client_secrets_file", "./client_secrets.json"))
    token_file = paths.get("token_file", "./data/youtube_token.json")

    auth = YouTubeAuth(client_secrets_file=client_secrets, token_file=token_file)
    try:
        creds = auth.get_credentials(allow_browser=True)
        if creds and creds.valid:
            console.print("[bold green]YouTube OAuth2 authentication successful! Token cached for 24/7 background refresh.[/bold green]")
        else:
            console.print("[bold red]Authentication failed or credentials invalid.[/bold red]")
    except Exception as e:
        console.print(f"[bold red]OAuth Flow Error:[/bold red] {e}")

def cmd_status(config: dict):
    """Displays pipeline metrics, queued clips, and daily upload counts."""
    from database.db import Database
    db_path = config.get("paths", {}).get("database_file", "./data/pipeline.db")
    db = Database(db_path)
    stats = db.get_stats()
    max_uploads = config.get("uploader", {}).get("max_daily_uploads", 4)

    console.print(Panel.fit("[bold green]YouTube Shorts Automation Pipeline Status[/bold green]"))

    table = Table(title="Daily Metrics", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold yellow")
    table.add_row("Source Videos Processed", str(stats["total_sources"]))
    uploads_str = f"{stats['today_uploads']} (Unlimited - No Limit)" if max_uploads <= 0 else f"{stats['today_uploads']} / {max_uploads} max daily"
    table.add_row("Today's Uploads", uploads_str)
    table.add_row("Today's Estimated API Quota", f"{stats['today_quota_used']} / 10,000 units")
    console.print(table)

    clips_table = Table(title="Clips by Status", show_header=True)
    clips_table.add_column("Status", style="magenta")
    clips_table.add_column("Count", style="bold green")
    for status, count in stats["clips_by_status"].items():
        clips_table.add_row(status, str(count))
    console.print(clips_table)

    # Show recent uploads
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, youtube_url, uploaded_at FROM clips WHERE status = 'UPLOADED' ORDER BY id DESC LIMIT 5")
        recent = cursor.fetchall()
        if recent:
            recent_table = Table(title="Recent Published YouTube Shorts", show_header=True)
            recent_table.add_column("ID", width=6)
            recent_table.add_column("Title", width=40)
            recent_table.add_column("Shorts URL", width=35)
            recent_table.add_column("Uploaded At", width=20)
            for r in recent:
                recent_table.add_row(str(r["id"]), r["title"], r["youtube_url"], str(r["uploaded_at"]))
            console.print(recent_table)

def cmd_process_url(url: str, config: dict, upload: bool = False):
    """Processes a single URL manually end-to-end."""
    console.print(f"[bold cyan]Processing single video:[/bold cyan] {url}")
    import yt_dlp
    from scheduler.runner import PipelineRunner
    runner = PipelineRunner(config)
    
    with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        video_info = {
            "video_id": info.get("id"),
            "title": info.get("title", "Manual Test"),
            "url": url,
            "channel": info.get("channel") or info.get("uploader") or "Unknown",
            "duration": int(info.get("duration") or 0),
            "view_count": int(info.get("view_count") or 0)
        }

    rendered_count = runner.process_single_source(video_info)
    console.print(f"[bold green]Finished processing! Generated {rendered_count} 9:16 Shorts.[/bold green]")

    if upload and rendered_count > 0:
        console.print("[cyan]Uploading highest-ranked clip to YouTube Shorts...[/cyan]")
        runner.execute_scheduled_upload()

def cmd_discover(config: dict, query: str = None):
    """Scans configured channels or search keywords and prints candidates."""
    from database.db import Database
    from downloader.scraper import ContentScraper
    db = Database(config.get("paths", {}).get("database_file", "./data/pipeline.db"))
    scraper = ContentScraper(config, db)

    console.print(Panel.fit("[bold cyan]Scanning for Viral Candidates[/bold cyan]") if Panel else "=== Scanning for Viral Candidates ===")
    
    candidates = []
    if query:
        candidates = scraper.search_candidates_by_keywords(query, max_results=5)
    else:
        for ch in config.get("sources", {}).get("channels", [])[:3]:
            candidates.extend(scraper.fetch_candidates_from_channel(ch))
            if len(candidates) >= 5:
                break
        if len(candidates) < 5:
            for kw in config.get("sources", {}).get("keywords", [])[:2]:
                candidates.extend(scraper.search_candidates_by_keywords(kw, max_results=3))

    if not candidates:
        console.print("[yellow]No new candidate videos found.[/yellow]")
        return

    if Table:
        t = Table(title="Viral Candidates Ready for Clipping", show_header=True)
        t.add_column("Video ID", style="cyan", width=12)
        t.add_column("Title", style="bold white", width=42)
        t.add_column("Channel", style="yellow", width=22)
        t.add_column("Duration", width=10)
        t.add_column("Views", width=12)
        for c in candidates[:8]:
            mins = c['duration'] // 60
            secs = c['duration'] % 60
            views_str = f"{c['view_count']:,}" if c.get('view_count') else "N/A"
            t.add_row(c['video_id'], c['title'], c['channel'], f"{mins}m {secs}s", views_str)
        console.print(t)
    else:
        for c in candidates:
            print(f"[{c['video_id']}] {c['title']} ({c['channel']}) - {c['url']}")

def cmd_upload(config: dict, limit: int = None):
    """Uploads queued rendered clips to YouTube Shorts."""
    from database.db import Database
    from uploader.youtube_uploader import YouTubeShortsUploader
    db = Database(config.get("paths", {}).get("database_file", "./data/pipeline.db"))
    uploader = YouTubeShortsUploader(config, db)
    
    ready_clips = db.get_ready_to_upload_clips(limit=limit or 10)
    if not ready_clips:
        console.print("[yellow]No rendered clips waiting in queue to upload.[/yellow]")
        return
    
    console.print(f"[bold cyan]Found {len(ready_clips)} rendered clip(s) waiting to upload.[/bold cyan]")
    for clip in ready_clips:
        console.print(f"\n[bold yellow]Uploading Short #{clip['id']}:[/bold yellow] {clip['title']}")
        res = uploader.upload_short(clip)
        if res:
            console.print(f"[bold green]Successfully uploaded! URL: {res['url']}[/bold green]")
        else:
            console.print(f"[bold red]Failed to upload clip #{clip['id']}. Check logs.[/bold red]")

def main():
    parser = argparse.ArgumentParser(description="Autonomous 24/7 YouTube Shorts Creation & Auto-Upload Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: run (24/7 Daemon)
    subparsers.add_parser("run", help="Start the persistent 24/7 autonomous daemon")

    # Command: check
    subparsers.add_parser("check", help="Audit dependencies, FFmpeg, and API credentials")

    # Command: auth
    subparsers.add_parser("auth", help="Perform one-time YouTube OAuth2 login and cache tokens")

    # Command: status
    subparsers.add_parser("status", help="Display pipeline queue, upload quota, and metrics")

    # Command: upload
    p_up = subparsers.add_parser("upload", help="Upload all currently rendered shorts to YouTube")
    p_up.add_argument("--limit", type=int, default=None, help="Maximum number of clips to upload")

    # Command: discover
    p_disc = subparsers.add_parser("discover", help="Scan channels and find viral candidate videos")
    p_disc.add_argument("--query", type=str, default=None, help="Custom search query keyword")

    # Command: process-url
    p_url = subparsers.add_parser("process-url", help="Process a single video URL into 9:16 Shorts immediately")
    p_url.add_argument("url", type=str, help="YouTube video URL")
    p_url.add_argument("--upload", action="store_true", help="Upload the rendered clip immediately")

    args = parser.parse_args()

    config = load_config()

    if args.command == "run":
        from scheduler.runner import PipelineRunner
        runner = PipelineRunner(config)
        runner.start_24_7()
    elif args.command == "check":
        cmd_check(config)
    elif args.command == "auth":
        cmd_auth(config)
    elif args.command == "status":
        cmd_status(config)
    elif args.command == "upload":
        cmd_upload(config, limit=args.limit)
    elif args.command == "discover":
        cmd_discover(config, query=args.query)
    elif args.command == "process-url":
        cmd_process_url(args.url, config, upload=args.upload)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
