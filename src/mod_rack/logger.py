import logging

__all__ = (
    "logger",
    "truncate",
    "ColorPrint",
)


class ANSIColorCodes:
    GREY = "\x1b[38;20m"
    BLUE = "\x1b[34m"
    CYAN = "\x1b[36m"
    YELLOW = "\x1b[33m"
    RED = "\x1b[31m"

    BOLD_RED = "\x1b[1;31m"
    RESET = "\x1b[0m"


COLOR_MAP = {
    logging.CRITICAL: ANSIColorCodes.BOLD_RED,
    logging.ERROR: ANSIColorCodes.RED,
    logging.WARNING: ANSIColorCodes.YELLOW,
    logging.INFO: ANSIColorCodes.CYAN,
    logging.DEBUG: ANSIColorCodes.BLUE,
}


CLI_LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"
FILE_LOG_FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"


class ColoredFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt=None, style="%"):
        super().__init__(fmt, datefmt, style)
        self.fmt = fmt
        if "(levelname)" not in fmt:
            raise ValueError("Formatter must contain '(levelname)' placeholder.")

    def format(self, record):
        log_color = COLOR_MAP.get(record.levelno, ANSIColorCodes.RESET)
        colored_levelname = f"{log_color}{record.levelname}{ANSIColorCodes.RESET}"
        original_levelname = record.levelname
        record.levelname = colored_levelname
        formatted_message = super().format(record)
        record.levelname = original_levelname

        return formatted_message


cpnsole_formatter = ColoredFormatter(CLI_LOG_FORMAT)
console_handler = logging.StreamHandler()
console_handler.setFormatter(cpnsole_formatter)
console_handler.setLevel(logging.DEBUG)  # Lowest level for console

logger: logging.Logger = logging.getLogger("mod-rack")
logger.addHandler(console_handler)
logger.setLevel(logging.INFO)


def truncate(obj, max_len: int = 100) -> str:
    """Return truncated repr of object for logging."""
    s = repr(obj).replace("\n", "")
    return s[:max_len] + "..." if len(s) > max_len else s


# # File handler (optional, added dynamically)
# file_handler: logging.FileHandler | None = None


class ColorPrint:
    def __init__(self, logger):
        self.logger: logging.Logger = logger

    def green(self, msg, level: int = logging.DEBUG):
        print(f"\033[32m{msg}\033[0m")
        self.logger.log(level, msg)

    def blue(self, msg, level: int = logging.DEBUG):
        print(f"\033[34m{msg}\033[0m")
        self.logger.log(level, msg)

    def red(self, msg, level: int = logging.DEBUG):
        print(f"\033[31m{msg}\033[0m")
        self.logger.log(level, msg)

    def yellow(self, msg, level: int = logging.DEBUG):
        print(f"\033[33m{msg}\033[0m")
        self.logger.log(level, msg)
