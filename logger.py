"""
Logging configuration.
All modules import logger from here.
"""

import logging
import sys
from datetime import datetime


def setup_logger(name: str = "pipeline", level: int = logging.INFO) -> logging.Logger:
    """
    Create a logger that writes to both console and a daily log file.
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger  # Already configured
    
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (daily rotation by filename)
    log_filename = f"pipeline_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger