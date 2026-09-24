#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path

from runtime_manager import (
    RuntimeManager,
    RuntimeErrorBase,
)


DEFAULT_ROOT = (
    Path.home()
    / ".local"
    / "share"
    / "local-ai-runtime"
    / "runtime"
    / "llama"
)


def dump(value):
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(
        prog="local-ai-runtime-runtime"
    )

    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser("status")

    install = sub.add_parser("install")
    install.add_argument(
        "--manifest",
        required=True,
    )
    install.add_argument(
        "--version",
    )

    sub.add_parser("rollback")

    args = parser.parse_args()

    manager = RuntimeManager(args.root)

    try:
        if args.command == "status":
            dump(manager.status())
            return 0

        if args.command == "install":
            dump(
                manager.install(
                    args.manifest,
                    args.version,
                )
            )
            return 0

        if args.command == "rollback":
            dump(manager.rollback())
            return 0

    except RuntimeErrorBase as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
