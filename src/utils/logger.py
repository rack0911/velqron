import logging
import os
from logging.handlers import TimedRotatingFileHandler


def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        formatter = logging.Formatter("%(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler (Daily rotation, keep 7 days)
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, "velqron.log"), when="midnight", interval=1, backupCount=7
        )
        file_formatter = logging.Formatter("%(asctime)s - %(levelname)s - [%(name)s] - %(message)s")
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger
