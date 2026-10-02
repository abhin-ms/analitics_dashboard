import os
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
    )

    DATABASE_URL: str = "mysql+aiomysql://root@localhost:3306/bp_analytics"
    JWT_SECRET_KEY: str = ""
    TOKEN_ENCRYPTION_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SECURE_COOKIES: bool = False
    GOOGLE_SERVICE_ACCOUNT_JSON_PATH: str = ""
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:8001,http://localhost:8000,http://127.0.0.1:8000,http://0.0.0.0:8000"
    BASE_REPORTING_CURRENCY: str = "INR"
    # Shared secret the third-party website sends with each paid booking
    # (X-Api-Key header or ?key=). Empty = website webhook disabled.
    WEBSITE_WEBHOOK_KEY: str = ""
    # Meta Lead Ads webhook (Facebook/Instagram lead forms). App secret signs
    # each webhook call; the verify token is what you type in Meta → Webhooks;
    # the system-user token (never expires) reads the lead details.
    META_APP_SECRET: str = ""
    META_VERIFY_TOKEN: str = ""
    META_ACCESS_TOKEN: str = ""
    META_PAGE_ID: str = ""
    META_GRAPH_VERSION: str = "v26.0"
    SMARTSERVICE_MCP_URL: str = "https://smartserviceapitemp.azurewebsites.net/mcp"
    SMARTSERVICE_CLIENT_ID: str = "Abhin"
    SMARTSERVICE_CLIENT_SECRET: str = ""
    SMARTSERVICE_SCOPE: str = "mcp.read"
    SMARTSERVICE_TOKEN_URL: str = "https://smartserviceapitemp.azurewebsites.net/connect/token"
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    SMTP_FROM: str = ""
    FRONTEND_URL: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
