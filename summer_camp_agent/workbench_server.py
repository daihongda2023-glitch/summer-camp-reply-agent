from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer

from .workbench_api import WorkbenchApiState, create_handler


def create_server(port: int = 8765) -> tuple[ThreadingHTTPServer, str]:
    state = WorkbenchApiState()
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(state))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="夏令营 Agent 本地能力服务")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    server, url = create_server(args.port)
    print(f"WORKBENCH_API_URL={url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
