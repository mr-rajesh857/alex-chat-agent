import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# Log Directory & File Path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

def setup_logging():
    """Configures application, Uvicorn, FastAPI, and SQLAlchemy loggers to write to a log file instead of terminal."""
    os.makedirs(LOG_DIR, exist_ok=True)

    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Rotating File Handler (10MB per file, 5 backup copies)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.INFO)

    # Configure Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)

    # Loggers to redirect away from terminal stdout/stderr
    target_loggers = [
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "fastapi",
        "sqlalchemy.engine",
        "asyncpg",
        "httpx"
    ]

    for logger_name in target_loggers:
        lg = logging.getLogger(logger_name)
        lg.handlers.clear()
        lg.addHandler(file_handler)
        lg.propagate = False

    logging.info(f"Logging initialized. All logs writing to file: {LOG_FILE}")

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
