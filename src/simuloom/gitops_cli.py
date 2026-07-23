from __future__ import annotations

import argparse
import json
from pathlib import Path

from simuloom.core.gitops import read_snapshot


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        prog="simuloom-gitops", description="Validate and compare SimuLoom GitOps snapshots."
    )
    subcommands = command.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="Validate a snapshot and its integrity")
    validate.add_argument("snapshot", type=Path)
    diff = subcommands.add_parser("diff", help="Detect drift between two snapshots")
    diff.add_argument("expected", type=Path)
    diff.add_argument("actual", type=Path)
    return command


def main() -> None:
    arguments = parser().parse_args()
    try:
        if arguments.command == "validate":
            snapshot = read_snapshot(arguments.snapshot)
            print(json.dumps({"valid": True, "integrity": snapshot["integrity"]}))
            return
        expected = read_snapshot(arguments.expected)
        actual = read_snapshot(arguments.actual)
        drift = expected["integrity"] != actual["integrity"]
        print(
            json.dumps(
                {
                    "drift": drift,
                    "expected": expected["integrity"],
                    "actual": actual["integrity"],
                }
            )
        )
        if drift:
            raise SystemExit(1)
    except ValueError as exc:
        parser().error(str(exc))


if __name__ == "__main__":
    main()
