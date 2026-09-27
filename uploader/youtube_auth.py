import os
import json
from typing import Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build, Resource
from utils.logger import logger

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

class YouTubeAuth:
    def __init__(self, client_secrets_file: str = "./client_secrets.json", token_file: str = "./data/youtube_token.json"):
        self.client_secrets_file = client_secrets_file
        self.token_file = token_file
        os.makedirs(os.path.dirname(os.path.abspath(token_file)), exist_ok=True)

        # Auto-restore credentials from environment variables if deployed to cloud (e.g., Render)
        secrets_env = os.getenv("YOUTUBE_CLIENT_SECRETS_JSON")
        if secrets_env and not os.path.exists(self.client_secrets_file):
            try:
                base_dir = os.path.dirname(os.path.abspath(self.client_secrets_file))
                if base_dir:
                    os.makedirs(base_dir, exist_ok=True)
                with open(self.client_secrets_file, "w", encoding="utf-8") as f:
                    f.write(secrets_env)
                logger.info(f"Restored {self.client_secrets_file} from YOUTUBE_CLIENT_SECRETS_JSON.")
            except Exception as e:
                logger.warning(f"Could not write client secrets from environment variable: {e}")

        token_env = os.getenv("YOUTUBE_TOKEN_JSON")
        if token_env and not os.path.exists(self.token_file):
            try:
                os.makedirs(os.path.dirname(os.path.abspath(self.token_file)), exist_ok=True)
                with open(self.token_file, "w", encoding="utf-8") as f:
                    f.write(token_env)
                logger.info(f"Restored {self.token_file} from YOUTUBE_TOKEN_JSON.")
            except Exception as e:
                logger.warning(f"Could not write token from environment variable: {e}")

    def get_credentials(self, allow_browser: bool = False) -> Optional[Credentials]:
        """
        Retrieves or refreshes YouTube OAuth credentials.
        If allow_browser is True, will trigger interactive browser auth if no token exists.
        """
        creds = None

        # 1. Load saved token
        if os.path.exists(self.token_file):
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, YOUTUBE_SCOPES)
            except Exception as e:
                logger.warning(f"Could not load saved YouTube token: {e}")

        # 2. Check if valid or needs refresh
        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired YouTube OAuth token in background...")
            try:
                creds.refresh(Request())
                with open(self.token_file, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                logger.info("Successfully refreshed and cached YouTube OAuth token.")
                return creds
            except Exception as e:
                logger.error(f"Failed to refresh YouTube OAuth token: {e}")

        # 3. Interactive flow if allowed
        if allow_browser:
            if not os.path.exists(self.client_secrets_file):
                raise FileNotFoundError(
                    f"Google OAuth Client Secrets file not found at: '{self.client_secrets_file}'.\n"
                    "Please download it from Google Cloud Console (APIs & Services > Credentials) and save it here."
                )

            logger.info("Launching YouTube OAuth2 consent browser flow...")
            flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, YOUTUBE_SCOPES)
            creds = flow.run_local_server(port=0)
            
            with open(self.token_file, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
            logger.info(f"YouTube credentials saved successfully to {self.token_file}")
            return creds

        logger.warning(
            "No valid YouTube credentials found. Run 'python main.py auth' once to authenticate."
        )
        return None

    def get_service(self, allow_browser: bool = False) -> Optional[Resource]:
        """Returns authenticated YouTube API Resource service."""
        creds = self.get_credentials(allow_browser=allow_browser)
        if not creds:
            return None
        return build("youtube", "v3", credentials=creds, cache_discovery=False)
