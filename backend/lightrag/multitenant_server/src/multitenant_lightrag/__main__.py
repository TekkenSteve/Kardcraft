from __future__ import annotations

import uvicorn

from .app import app, settings


def main() -> None:
    uvicorn.run(
        app,
        host=settings.listen_host,
        port=settings.listen_port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
