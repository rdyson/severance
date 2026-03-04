"""Entry point for running Severance."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import uvicorn

from severance import __version__
from severance.config import load_config
from severance.server import app, configure, mount_static


def main():
    parser = argparse.ArgumentParser(
        prog="severance",
        description="Track what you pay the things replacing you.",
    )
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to config.yaml (default: ./config.yaml or $SEVERANCE_CONFIG)",
    )
    parser.add_argument(
        "--host", default=None, help="Override server host"
    )
    parser.add_argument(
        "--port", "-p", type=int, default=None, help="Override server port"
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch data from providers and exit (no server)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of history to fetch on refresh (default: 30)",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"severance {__version__}"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    configure(config)

    if args.refresh:
        from severance.scheduler import refresh_data

        results = asyncio.run(refresh_data(config, days_back=args.days))
        print(f"Refresh complete: {results['total_records']} records")
        for name, info in results["providers"].items():
            print(f"  {name}: {info['records']} records ({info['status']})")
        sys.exit(0)

    mount_static()

    host = args.host or config.server.host
    port = args.port or config.server.port

    print(f"\n💀 Severance v{__version__}")
    print(f"   Track what you pay the things replacing you.\n")
    print(f"   Dashboard: http://{host}:{port}")
    print(f"   Health:    http://{host}:{port}/api/health\n")

    # Schedule periodic refresh
    from apscheduler.schedulers.background import BackgroundScheduler
    from severance.scheduler import refresh_data

    scheduler = BackgroundScheduler()

    def _refresh_job():
        asyncio.run(refresh_data(config))

    scheduler.add_job(
        _refresh_job,
        "interval",
        hours=config.refresh.interval_hours,
        id="refresh",
        name="Provider data refresh",
    )
    scheduler.start()

    # Run initial refresh in background
    import threading

    threading.Thread(target=_refresh_job, daemon=True).start()

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info" if not args.debug else "debug",
    )


if __name__ == "__main__":
    main()
