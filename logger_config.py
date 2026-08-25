"""Structured Logging Configuration"""
import logging
import logging.handlers
from pathlib import Path
from config import LOG_FORMAT, LOG_LEVEL, LOGS_DIR

def setup_logger(name: str) -> logging.Logger:
    """Setup logger with file + console handlers"""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    
    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(console)
    
    # File handler (rotating)
    log_file = LOGS_DIR / f"{name}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger("pdf_mitra_pro")
