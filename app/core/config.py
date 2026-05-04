from pydantic_settings import BaseSettings, SettingsConfigDict

from app.compat import data_dir


def _default_keys_file() -> str:
    return str(data_dir() / "api_keys.json")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_version: str = "1.0.0"

    api_keys_file: str = ""  # resolved below if empty

    max_upload_size_mb: int = 2000

    cors_origins: str = "http://localhost:8000"
    jwt_secret: str = "dev-secret-change-me-min-32-chars-long"

    # Stripe (leave empty to disable billing)
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_pro_price_id: str = ""
    stripe_business_price_id: str = ""

    # Whether to expose /pricing — independent of Stripe availability so the
    # SaaS deployment can run a "Coming Soon" pricing page during the window
    # between launch and Stripe live-mode activation. Self-hosters default
    # to off (no commercial offer to advertise).
    pricing_page_enabled: bool = False

    # Transactional email (leave smtp_host empty to disable sending — dev mode)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "FileMorph"
    smtp_reply_to: str = ""

    # Public base URL used when building links in outbound emails.
    app_base_url: str = "http://localhost:8000"

    # Optional cross-origin base for heavy upload POSTs (convert/compress,
    # single + batch). Empty string keeps uploads same-origin — the only
    # reason to set this is when the main site sits behind a proxy that
    # caps request bodies (e.g. Cloudflare Free at 100 MB) and uploads
    # need to bypass it via a separate tunnel subdomain like
    # `https://api.example.com`. All non-upload API calls (formats, auth,
    # billing) stay same-origin regardless.
    api_base_url: str = ""

    def model_post_init(self, __context) -> None:
        if not self.api_keys_file:
            self.api_keys_file = _default_keys_file()

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",")]


settings = Settings()
