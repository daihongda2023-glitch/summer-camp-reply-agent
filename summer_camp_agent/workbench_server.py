from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer

from .rag_runtime import load_default_rag_answer_generator, load_default_semantic_analyzer
from .workbench_api import WorkbenchApiState, create_handler


def create_server(port: int = 8765, activity_id: str | None = None) -> tuple[ThreadingHTTPServer, str]:
    state_kwargs = {
        "rag_answer_generator": load_default_rag_answer_generator(),
        "semantic_analyzer": load_default_semantic_analyzer(),
    }
    if activity_id:
        state_kwargs["activity_id"] = activity_id
    state = WorkbenchApiState(**state_kwargs)
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(state))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    return server, url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="活动值守 Activity Desk 本地能力服务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--activity", default="summer-camp", help="活动包 ID")
    args = parser.parse_args(argv)

    server, url = create_server(args.port, activity_id=args.activity)
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
