from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from conductor.domain.trading_mode import TradingMode

LlmBackendName = Literal["none", "claude_code_headless", "anthropic_api"]


class Settings(BaseSettings):
    """Environment-driven settings. Missing/invalid required values fail at startup."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Safety: defaults to paper. Anything other than dry_run/live is rejected.
    trading_mode: TradingMode = TradingMode.DRY_RUN

    # R1: one-time principal. Required, never defaulted.
    principal_usd: Decimal = Field(gt=Decimal(0))

    # SQLite only (ADR-0009). Required, never defaulted.
    database_url: str

    freqtrade_api_url: AnyHttpUrl = AnyHttpUrl("http://freqtrade:8080")
    # Same variable names as .env / Freqtrade's own config.
    freqtrade_username: SecretStr = Field(
        validation_alias=AliasChoices("FREQTRADE__API_SERVER__USERNAME", "freqtrade_username"),
    )
    freqtrade_password: SecretStr = Field(
        validation_alias=AliasChoices("FREQTRADE__API_SERVER__PASSWORD", "freqtrade_password"),
    )

    # Name under which this Freqtrade instance's trades are stored in the ledger.
    freqtrade_instance_name: str = Field(default="primary", min_length=1)

    # R3. The cap's value is TBD (Phase 3, docs/02-requirements.md): no default is
    # invented. Unset => the fence job fences nothing and logs a warning.
    daily_profit_cap_usd: Decimal | None = Field(default=None, ge=Decimal(0))
    # R3 draft value (docs/02-requirements.md AC3.1), final value TBD (Phase 3).
    manual_move_threshold_usd: Decimal = Field(default=Decimal(25), gt=Decimal(0))

    # R4 second layer + R7 (draft values, docs/02-requirements.md). Percentages: 3 = 3%.
    daily_loss_limit_pct: Decimal = Field(default=Decimal(3), gt=Decimal(0))
    max_drawdown_pct: Decimal = Field(default=Decimal(10), gt=Decimal(0))
    consecutive_loss_limit: int = Field(default=3, ge=1)
    # R7: every whitelisted pair is one exposure group. Keep equal to Freqtrade's max_open_trades.
    max_concurrent_positions: int = Field(default=2, ge=1)
    risk_check_interval_seconds: int = Field(default=60, ge=15)

    # Telegram (3A-4). The token reaches this container only. Both or neither: a bot
    # without an allowlist, or an allowlist without a bot, is a misconfiguration.
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_chat_ids: Annotated[tuple[int, ...], NoDecode] = ()
    # false = alerts only, no polling. Lets a second Conductor (dev/test) send alerts without
    # fighting the real one over getUpdates (one token can be polled by one process only).
    telegram_commands_enabled: bool = True

    scheduler_enabled: bool = True
    ingest_interval_seconds: int = Field(default=300, ge=30)
    heartbeat_interval_seconds: int = Field(default=300, ge=30)
    healthchecks_ping_url: AnyHttpUrl | None = None  # unused until 3A-5

    llm_backend: LlmBackendName = "none"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    @field_validator("daily_profit_cap_usd", mode="before")
    @classmethod
    def _blank_cap_is_unset(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator(
        "principal_usd",
        "daily_profit_cap_usd",
        "manual_move_threshold_usd",
        "daily_loss_limit_pct",
        "max_drawdown_pct",
    )
    @classmethod
    def _finite(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and not v.is_finite():
            raise ValueError("must be a finite number")
        return v

    @field_validator("telegram_bot_token", mode="before")
    @classmethod
    def _blank_token_is_unset(cls, v: Any) -> Any:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("telegram_allowed_chat_ids", mode="before")
    @classmethod
    def _parse_chat_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            parts = [p.strip() for p in v.split(",") if p.strip()]
            try:
                return tuple(int(p) for p in parts)
            except ValueError:
                raise ValueError("must be comma-separated integer chat IDs") from None
        return v

    @model_validator(mode="after")
    def _telegram_consistent(self) -> "Settings":
        if self.telegram_bot_token is not None and not self.telegram_allowed_chat_ids:
            raise ValueError("TELEGRAM_ALLOWED_CHAT_IDS is required when TELEGRAM_BOT_TOKEN is set")
        if self.telegram_bot_token is None and self.telegram_allowed_chat_ids:
            raise ValueError("TELEGRAM_BOT_TOKEN is required when TELEGRAM_ALLOWED_CHAT_IDS is set")
        return self

    @property
    def telegram_enabled(self) -> bool:
        return self.telegram_bot_token is not None

    @field_validator("database_url")
    @classmethod
    def _sqlite_only(cls, v: str) -> str:
        if not v.startswith("sqlite:///"):
            raise ValueError("DATABASE_URL must be a sqlite:/// URL (ADR-0009)")
        return v

    @field_validator("freqtrade_username", "freqtrade_password")
    @classmethod
    def _non_empty(cls, v: SecretStr) -> SecretStr:
        if not v.get_secret_value().strip():
            raise ValueError("must not be empty")
        return v


def load_settings() -> Settings:
    """Load settings from the environment (raises pydantic.ValidationError)."""
    return Settings()
