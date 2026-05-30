from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    agent_url: str = "https://test-agent-prev-ai-777.edilnet.it/invoke_agent"
    agent_user_id: str = "test-user-001"
    agent_username: str = "Test Client"
    max_concurrent: int = 10
    db_path: str = "simulations.db"
    agent_timeout_connect: float = 10.0
    agent_timeout_read: float = 300.0
    agent_max_retries: int = 2
    delay_min_ms: int = 2000
    delay_max_ms: int = 6000


settings = Settings()
