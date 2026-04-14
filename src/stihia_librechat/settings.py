"""Application settings loaded from environment variables."""

from importlib.metadata import version

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


def get_package_version() -> str:
    """Get the version of the Stihia LibreChat package."""
    return version("stihia-librechat")


class Settings(BaseSettings):
    """Proxy configuration.

    All values come from environment variables (or a ``.env`` file).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Stihia
    STIHIA_API_KEY: str = ""
    STIHIA_API_URL: str = "https://api.stihia.ai"
    STIHIA_PROJECT_KEY: str = "librechat"
    STIHIA_LIBRECHAT_VERSION: str = Field(default_factory=get_package_version)
    STIHIA_INPUT_SENSOR: str = "default-input-think"
    STIHIA_OUTPUT_SENSOR: str = "default-output"
    STIHIA_SEND_FULL_HISTORY: bool = True

    # Upstream allowlist (comma-separated hostnames).
    ALLOWED_UPSTREAM_HOSTS: str = "api.openai.com"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 4005
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "local"
