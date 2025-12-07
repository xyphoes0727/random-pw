import logging
import os
from logging.handlers import RotatingFileHandler
from colorama import Fore, Style, init

# initialize colorama
init(autoreset=True)

service_name = "backend"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, "app.log")


# ---- Custom color formatter ----
class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.GREEN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"


def get_logger(name: str = None):
    full_name = f"{service_name}.{name}" if name else service_name
    logger = logging.getLogger(full_name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # ---- Console Handler (Colored) ----
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)

        console_formatter = ColorFormatter(
            '[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler.setFormatter(console_formatter)

        # ---- File Handler (Plain Text) ----
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)

        file_formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(file_formatter)

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    logger.propagate = True
    return logger
