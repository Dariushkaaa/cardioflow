from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    llm_api_key: str = ""
    llm_model_name: str = "meta-llama/Llama-3-8b-chat-hf"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    backend_api_url: str = "http://localhost:8000/api/v1"
    request_timeout: float = 15.0
    # Каталог с утвержденными .txt материалами для RAG
    rag_docs_dir: str = str(BASE_DIR / "knowledge")
    # Часовой пояс для показа времени слотов пациенту
    timezone: str = "Europe/Moscow"
    app_name: str = "CardioFlow Agent Service"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
