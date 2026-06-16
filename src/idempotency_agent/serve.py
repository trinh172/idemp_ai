"""
Serve — khởi động web UI bằng uvicorn.

Usage:
    idempotency-web                  # mặc định 127.0.0.1:8000
    HOST=0.0.0.0 PORT=9000 idempotency-web
"""
import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "idempotency_agent.web:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=bool(os.getenv("RELOAD")),
    )


if __name__ == "__main__":
    main()
