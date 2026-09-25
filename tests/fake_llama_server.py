#!/usr/bin/env python3

import argparse
import json
import os
import time
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from pathlib import Path


parser = argparse.ArgumentParser(
    add_help=False,
)

parser.add_argument(
    "-m",
    "--model",
    required=True,
)

parser.add_argument(
    "--host",
    default="127.0.0.1",
)

parser.add_argument(
    "--port",
    type=int,
    required=True,
)

args, unknown = parser.parse_known_args()

model_name = Path(
    args.model
).name


class Handler(BaseHTTPRequestHandler):
    def log_message(
        self,
        fmt,
        *args,
    ):
        pass

    def send_json(
        self,
        payload,
    ):
        body = json.dumps(
            payload
        ).encode()

        self.send_response(
            200
        )

        self.send_header(
            "Content-Type",
            "application/json",
        )

        self.send_header(
            "Content-Length",
            str(len(body)),
        )

        self.end_headers()
        self.wfile.write(
            body
        )

    def do_GET(self):
        if self.path == "/health":
            self.send_json(
                {
                    "status": "ok",
                    "model": model_name,
                    "pid": os.getpid(),
                }
            )
            return

        self.send_response(
            404
        )
        self.end_headers()

    def do_POST(self):
        if (
            self.path
            != "/v1/chat/completions"
        ):
            self.send_response(
                404
            )
            self.end_headers()
            return

        length = int(
            self.headers.get(
                "Content-Length",
                "0",
            )
        )

        payload = {}

        if length:
            payload = json.loads(
                self.rfile.read(
                    length
                )
            )

        if payload.get("stream") is True:
            self.send_response(
                200
            )
            self.send_header(
                "Content-Type",
                "text/event-stream",
            )
            self.send_header(
                "Cache-Control",
                "no-cache",
            )
            self.end_headers()

            events = (
                {
                    "id": "fake-stream",
                    "object": (
                        "chat.completion.chunk"
                    ),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": "first",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "fake-stream",
                    "object": (
                        "chat.completion.chunk"
                    ),
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": "second",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
            )

            for event in events:
                data = json.dumps(
                    event,
                    separators=(",", ":"),
                ).encode()

                self.wfile.write(
                    b"data: "
                    + data
                    + b"\n\n"
                )
                self.wfile.flush()
                time.sleep(1.0)

            self.wfile.write(
                b"data: [DONE]\n\n"
            )
            self.wfile.flush()
            return

        self.send_json(
            {
                "id": "fake-completion",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": (
                                "served:"
                                + model_name
                                + ":pid="
                                + str(
                                    os.getpid()
                                )
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )


server = ThreadingHTTPServer(
    (
        args.host,
        args.port,
    ),
    Handler,
)

server.serve_forever()
