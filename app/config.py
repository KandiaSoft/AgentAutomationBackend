from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    agent_url: str = "https://test-agent-prev-ai-777.edilnet.it/invoke_agent"
    agent_url_local: str = "http://localhost:8001/invoke_agent"
    agent_use_local: bool = False
    agent_user_id: str = "test-user-001"
    agent_username: str = "Test Client"
    agent_company_id: str = "100"
    # Security header validation on the agent endpoint. When SECRET_VALIDATION=1,
    # requests must carry X-User-Key / X-User-Secret headers.
    secret_validation: int = 0
    agent_user_key: str = ""
    agent_user_secret: str = ""
    max_concurrent: int = 10
    db_path: str = "simulations.db"
    agent_timeout_connect: float = 10.0
    agent_timeout_read: float = 300.0
    agent_max_retries: int = 2
    delay_min_ms: int = 2000
    delay_max_ms: int = 6000
    # Max turns in advisor mode before forcing the client to request the quote.
    advisor_max_turns: int = 5

    @property
    def effective_agent_url(self) -> str:
        return self.agent_url_local if self.agent_use_local else self.agent_url

    @property
    def security_headers(self) -> dict[str, str]:
        if self.secret_validation == 1:
            return {
                "X-User-Key": self.agent_user_key,
                "X-User-Secret": self.agent_user_secret,
            }
        return {}


settings = Settings()
