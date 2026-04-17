from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "YGO Collection API"
    environment: str = "development"
    api_prefix: str = "/api"

    database_url: str = "postgresql+asyncpg://ygo_user:ygo_password@db:5432/ygo_collection"
    redis_url: str = "redis://redis:6379/0"

    cors_origins: str = "http://localhost:3000"
    frontend_origin: str = "http://localhost:3000"

    media_root: str = "/app/media"
    cards_image_subdir: str = "cards"

    price_provider: str = "ygoprodeck"
    card_data_provider: str = "ygoprodeck"
    image_provider: str = "ygoprodeck"

    ygoprodeck_api_base_url: str = "https://db.ygoprodeck.com/api/v7"
    request_timeout_seconds: int = 20
    cardmarket_offer_sample_size: int = 5
    cardmarket_low_outlier_ratio_vs_next: float = 0.5
    cardmarket_low_outlier_ratio_vs_cluster: float = 0.4
    cardmarket_playwright_timeout_seconds: int = 90
    sync_batch_size: int = 50

    price_monitor_night_window_start_hour: int = 1
    price_monitor_night_window_end_hour: int = 6
    price_monitor_max_requests_per_minute: int = 6
    price_monitor_max_requests_per_hour: int = 40
    price_monitor_max_parallel_jobs: int = 1
    price_monitor_scheduler_batch_size: int = 50
    price_monitor_jitter_seconds: int = 90
    price_monitor_min_interval_hours: int = 6
    price_monitor_default_interval_hours: int = 24
    price_monitor_volatile_interval_hours: int = 12
    price_monitor_stable_interval_hours: int = 48
    price_monitor_very_stable_interval_hours: int = 96
    price_monitor_max_interval_hours: int = 96
    price_monitor_low_value_threshold: float = 4.0
    price_monitor_stable_change_threshold: float = 3.0
    price_monitor_watch_change_threshold: float = 10.0
    price_monitor_volatile_change_threshold: float = 20.0
    price_monitor_high_volatility_change_threshold: float = 35.0
    price_monitor_new_priority: int = 100
    price_monitor_manual_priority: int = 100
    price_monitor_high_volatility_priority: int = 90
    price_monitor_volatile_priority: int = 70
    price_monitor_watch_priority: int = 50
    price_monitor_stable_priority: int = 30
    price_monitor_low_value_priority: int = 20
    price_monitor_retry_priority: int = 60
    price_monitor_low_value_checks_for_very_stable: int = 3

    price_sync_interval_minutes: int = 360
    image_sync_interval_minutes: int = 720
    trend_sync_interval_minutes: int = 180
    card_data_sync_interval_minutes: int = 1440
    sync_worker_poll_seconds: int = 3
    sync_worker_max_parallel_jobs: int = 4
    sync_scheduler_poll_seconds: int = 30
    sync_job_running_timeout_minutes: int = 30
    sync_job_pending_warning_minutes: int = 5

    cardmarket_app_token: str | None = None
    cardmarket_app_secret: str | None = None
    cardmarket_access_token: str | None = None
    cardmarket_access_secret: str | None = None

    ygo_omega_directory: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def media_root_path(self) -> Path:
        return Path(self.media_root)

    @property
    def cards_media_path(self) -> Path:
        return self.media_root_path / self.cards_image_subdir


settings = Settings()
