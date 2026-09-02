"""CLI entry point: `python3 -m webtx [options]`."""

from __future__ import annotations

import argparse
import json
import logging
import os
import ssl
import sys

from aiohttp import web

from .config import Config, ConfigError
from .server import create_app


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webtx", description="rpitx_webtx low-latency transmitter server"
    )
    parser.add_argument("--config", help="path to a JSON configuration file")
    parser.add_argument("--host", help="override the listen host")
    parser.add_argument("--port", type=int, help="override the listen port")
    parser.add_argument("--no-tls", action="store_true",
                         help="serve plain HTTP instead of HTTPS (getUserMedia then "
                              "requires http://localhost)")
    parser.add_argument("--sink", choices=("auto", "webtx_iq", "sendiq", "null"),
                         help="override sink.kind")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
                         help="override log.level")
    parser.add_argument("--dry-run", action="store_true",
                         help="force the null sink regardless of sink.kind (no RF output)")
    parser.add_argument("--print-config", action="store_true",
                         help="print the effective configuration as JSON and exit")
    return parser


def main(argv=None) -> int:
    args = _build_arg_parser().parse_args(argv)

    try:
        cfg = Config.load(cli_path=args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1

    cfg.apply_overrides(
        host=args.host, port=args.port, no_tls=args.no_tls,
        sink_kind=args.sink, log_level=args.log_level, dry_run=args.dry_run,
    )
    try:
        cfg.validate()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1

    if args.print_config:
        print(json.dumps(cfg.data, indent=2))
        return 0

    log_cfg = cfg.data["log"]
    handlers = [logging.StreamHandler()]
    if log_cfg.get("file"):
        handlers.append(logging.FileHandler(log_cfg["file"]))
    logging.basicConfig(
        level=getattr(logging, log_cfg.get("level", "INFO")),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    logger = logging.getLogger("webtx.main")

    ssl_context = None
    tls_cfg = cfg.data["tls"]
    if tls_cfg.get("enabled"):
        cert = tls_cfg.get("cert", "")
        key = tls_cfg.get("key", "")
        if not (os.path.isfile(cert) and os.path.isfile(key)):
            logger.error(
                "TLS is enabled but cert (%s) or key (%s) was not found. Browsers "
                "require HTTPS (or http://localhost) for microphone access. Generate "
                "a certificate (see README.md, 'Certificates' section) or pass --no-tls "
                "to serve plain HTTP for local/loopback testing only.", cert, key,
            )
            return 1
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ssl_context.load_cert_chain(cert, key)
        except ssl.SSLError as exc:
            logger.error("failed to load TLS certificate/key: %s", exc)
            return 1

    app = create_app(cfg)
    logger.info(
        "listening on %s://%s:%d",
        "https" if ssl_context else "http", cfg.data["host"], cfg.data["port"],
    )
    web.run_app(app, host=cfg.data["host"], port=cfg.data["port"], ssl_context=ssl_context,
                print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
