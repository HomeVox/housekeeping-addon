"""Dependency injection for Housekeeping."""

import json
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..housekeeper.engine import HousekeeperEngine
from ..housekeeper.ha_ws import HAWebSocketClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Components:
    ha: HAWebSocketClient
    engine: HousekeeperEngine


_components: Components | None = None


def _load_options() -> dict[str, object]:
    """Load options from /data/options.json."""
    try:
        path = Path("/data/options.json")
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return json.load(f) or {}
    except Exception as e:
        logger.warning("Failed to load options: %s", e)
    return {}


def _get_supervisor_token() -> str:
    """Get Supervisor token from environment or s6 container files."""
    # 1. Standard environment variable
    token = os.environ.get("SUPERVISOR_TOKEN", "")

    # 2. s6-overlay container environment files
    if not token:
        for s6_dir in ["/var/run/s6/container_environment", "/run/s6/container_environment"]:
            token_file = Path(s6_dir) / "SUPERVISOR_TOKEN"
            if token_file.exists():
                try:
                    token = token_file.read_text().strip()
                    if token:
                        logger.info("SUPERVISOR_TOKEN loaded from %s", token_file)
                        break
                except Exception:
                    pass

    # 3. Legacy HASSIO_TOKEN
    if not token:
        token = os.environ.get("HASSIO_TOKEN", "")

    if not token:
        logger.error("SUPERVISOR_TOKEN not found in environment or s6 files!")
        logger.info("Available env vars: %s", [k for k in os.environ if not k.startswith("_")])

    return token


def init_components() -> None:
    """Initialize components with Supervisor authentication."""
    global _components
    if _components is not None:
        return

    # Load options
    options = _load_options()

    # Get Supervisor token (provided by Home Assistant when hassio_api is enabled)
    token = _get_supervisor_token()

    if not token:
        logger.error(
            "No Supervisor token available. "
            "Ensure 'hassio_api: true' is set in config.json and "
            "the add-on was installed (not just rebuilt)."
        )
        # Create dummy components that will fail gracefully
        ha = HAWebSocketClient(url="ws://supervisor/core/websocket", token="")
    else:
        # Use internal Supervisor WebSocket endpoint
        # This URL is only accessible from within the add-on container
        ha = HAWebSocketClient(
            url="ws://supervisor/core/websocket",
            token=token,
            timeout=30.0,
        )

    # Create engine
    # Prefer storing state under /config so it survives add-on uninstall/reinstall.
    data_dir = "/config/ha_housekeeping"
    os.makedirs(data_dir, exist_ok=True)

    # One-time best-effort migration from old /data location.
    # /data persists across updates, but not across uninstall/reinstall.
    legacy_dir = "/data"
    for name in ("plan.json", "rollback.json", "ignored.json"):
        src = os.path.join(legacy_dir, name)
        dst = os.path.join(data_dir, name)
        try:
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                logger.info("Migrated %s -> %s", src, dst)
        except Exception as e:
            logger.warning("Failed migrating %s -> %s: %s", src, dst, e)

    engine = HousekeeperEngine(
        ha=ha,
        onbekend_area_name=str(options.get("onbekend_area_name", "Onbekend")),
        confidence_threshold=float(options.get("confidence_threshold", 0.9)),
        data_dir=data_dir,
    )

    _components = Components(ha=ha, engine=engine)

    if token:
        logger.info("Components initialized with Supervisor authentication")
    else:
        logger.warning("Components initialized WITHOUT authentication - operations will fail")


def get_engine() -> HousekeeperEngine:
    """Get the engine instance."""
    if _components is None:
        init_components()
    assert _components is not None
    return _components.engine
