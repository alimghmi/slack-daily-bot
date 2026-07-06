from __future__ import annotations

import sys

from dailybot.app import main as app_main
from dailybot.healthcheck import main as healthcheck_main


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "healthcheck":
        healthcheck_main()
        return
    app_main()


if __name__ == "__main__":
    main()
