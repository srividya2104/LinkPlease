import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    API_KEY: str = os.getenv(
        "PSEUDOGRAM_API_KEY", os.getenv("API_KEY", "")
    ).strip()
    PSEUDOGRAM_BASE_URL: str = os.getenv(
        "PSEUDOGRAM_BASE_URL", "https://pseudogram-api.onrender.com"
    ).rstrip("/")
    VERIFY_WEBHOOK_SIGNATURE: bool = (
        os.getenv("VERIFY_WEBHOOK_SIGNATURE", "true").lower() == "true"
    )
    DATABASE_PATH: str = os.getenv("DATABASE_PATH", "linkplease.db")
    WORKER_POLL_INTERVAL: float = float(os.getenv("WORKER_POLL_INTERVAL", "0.5"))
    RECONCILE_POLL_INTERVAL: float = float(os.getenv("RECONCILE_POLL_INTERVAL", "1.0"))
    MAX_SEND_PER_MINUTE: int = int(os.getenv("MAX_SEND_PER_MINUTE", "9"))


settings = Settings()
