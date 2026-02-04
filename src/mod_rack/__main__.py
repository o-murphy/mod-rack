import sys
import subprocess
import os
from pathlib import Path
import argparse

from mod_rack.logger import logger


def main():
    parser = argparse.ArgumentParser("mod-rack")

    subparsers = parser.add_subparsers(dest="command", help="Commands")
    subparsers.add_parser("config", help="Generate config")
    subparsers.add_parser("headless", help="Run headless service")
    subparsers.add_parser("gui", help="Run gui")

    ns, command_args = parser.parse_known_args()
    command = ns.command

    base_path = Path(__file__).parent

    if command == "headless" or (
        sys.platform == "linux" and not os.environ.get("DISPLAY")
    ):
        target_script = base_path / "service.py"
        mode_name = "SERVICE (Headless)"
    elif command == "gui":
        target_script = base_path / "gui.py"
        mode_name = "GUI"
    elif command == "config":
        target_script = base_path / "config_gen.py"
        mode_name = "CONFIG GEN"
    else:
        parser.error("unknown command")

    if not target_script.exists():
        logger.error("%s not found in %s", target_script.name, base_path)
        sys.exit(1)

    logger.info("--- Starting MOD Rack in %s mode ---", mode_name)

    cmd = [sys.executable, str(target_script)] + command_args

    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        # Ctrl+C handling
        pass
    except subprocess.CalledProcessError as err:
        logger.error("Process finished with error code: %s", err)
        sys.exit(err.returncode)


if __name__ == "__main__":
    main()
