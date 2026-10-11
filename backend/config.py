"""
mdAgent — Configuration
Загрузка переменных окружения и констант приложения.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем .env из корня проекта
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


# --- Gemini ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_CASCADE_MODELS: list[str] = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
]
GEMINI_MODEL: str = GEMINI_CASCADE_MODELS[0]

# --- HydraAI ---
HYDRA_API_KEY: str = os.getenv("HYDRA_API_KEY", "")
HYDRA_BASE_URL: str = os.getenv("HYDRA_BASE_URL", "https://api.hydraai.ru/v1")
HYDRA_MODEL: str = os.getenv("HYDRA_MODEL", "gpt-5.6-luna")

# --- Tilda ---
TILDA_EMAIL: str = os.getenv("TILDA_EMAIL", "")
TILDA_PASSWORD: str = os.getenv("TILDA_PASSWORD", "")
TILDA_LOGIN_URL: str = "https://tilda.cc/login/"
TILDA_PROJECTS_URL: str = "https://tilda.cc/projects/"

# --- Server ---
HOST: str = os.getenv("HOST", "127.0.0.1")
PORT: int = int(os.getenv("PORT", "8000"))

# --- Browser & Storage ---
BROWSER_HEADLESS: bool = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
BROWSER_DATA_DIR: Path = PROJECT_ROOT / "playwright-data"
SCREENSHOT_DIR: Path = PROJECT_ROOT / "screenshots"
DATA_DIR: Path = PROJECT_ROOT / "data"
SETTINGS_FILE: Path = DATA_DIR / "settings.json"

# Создаём директории если нужно
BROWSER_DATA_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

