"""Local management commands. Diagnostics intentionally omit credential values."""

import argparse
import asyncio
import json
import sys

from atp.config import Settings
from atp.providers import provision, readiness


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["doctor", "provision"])
    args = parser.parse_args()
    settings = Settings()
    if args.command == "doctor":
        results = await readiness(settings)
        for name, result in results.items():
            print(f"{'OK' if result['ok'] else 'FAIL'}  {name}: {result['detail']}")
        return 0 if all(r["ok"] for r in results.values()) else 1
    result = await provision(settings)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print(
            f"Setup failed ({type(exc).__name__}). Check provider permissions and configuration.",
            file=sys.stderr,
        )
        sys.exit(1)
