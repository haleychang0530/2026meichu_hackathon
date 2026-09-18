from __future__ import annotations

import uvicorn

from .config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "core_api.app:app",
        host=settings.host,
        port=settings.port,
        workers=1,
        reload=False,
    )


if __name__ == "__main__":
    main()
