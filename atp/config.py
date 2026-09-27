import os
import secrets
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", case_sensitive=False)
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    eleven_api_key: str = ""
    eleven_voice_id: str = ""
    eleven_stt_model: str = "scribe_v2_realtime"
    eleven_tts_model: str = "eleven_flash_v2_5"
    eleven_vad_silence_seconds: float = Field(default=1.3, ge=0.5, le=3)
    turn_end_delay_seconds: float = Field(default=0.7, ge=0, le=3)
    incomplete_turn_delay_seconds: float = Field(default=1.8, ge=0, le=5)
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_sip_trunk_id: str = ""
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_phone_number: str = ""
    demo_payer_phone_number: str = ""  # Legacy insurer default
    insurer_phone_number: str = ""
    doctor_phone_number: str = ""
    slack_webhook_url: str = ""
    public_base_url: str = ""
    docupdates_base_url: str = "https://docupdates.vercel.app"
    app_demo_password: str = ""
    app_port: int = 8000
    database_path: str = "./.local/atp.sqlite3"
    demo_max_call_seconds: int = 600

    @property
    def db_path(self) -> Path:
        path = Path(self.database_path)
        return path if path.is_absolute() else ROOT / path

    def secret(self) -> str:
        path = ROOT / ".local" / "session-secret"
        path.parent.mkdir(exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return path.read_text().strip()
        value = secrets.token_urlsafe(48)
        with os.fdopen(fd, "w") as f:
            f.write(value)
        return value


settings = Settings()
