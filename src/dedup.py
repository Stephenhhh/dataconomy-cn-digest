"""Persistent dedup state stored in state.json at the repo root."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .feed import FeedItem

logger = logging.getLogger(__name__)

STATE_PATH = Path("state.json")
MAX_SEEN = 200


def load_state(path: Path = STATE_PATH) -> dict:
    if not path.exists():
        logger.info("state.json missing; starting from empty state")
        return {"seen_ids": [], "last_run_utc": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("state.json unreadable (%s); resetting", exc)
        return {"seen_ids": [], "last_run_utc": None}
    if not isinstance(data, dict) or not isinstance(data.get("seen_ids"), list):
        logger.warning("state.json malformed; resetting")
        return {"seen_ids": [], "last_run_utc": None}
    data.setdefault("last_run_utc", None)
    return data


def is_bootstrap(state: dict) -> bool:
    return len(state.get("seen_ids") or []) == 0


def filter_new(items: list["FeedItem"], state: dict) -> list["FeedItem"]:
    """Return items whose id has not been seen before.

    On first-ever run (empty state), returns items as-is (bootstrap).
    """
    if is_bootstrap(state):
        logger.info("Bootstrap run: treating all %d items as new", len(items))
        return list(items)
    seen = set(state["seen_ids"])
    new_items = [it for it in items if it.id not in seen]
    logger.info("Filtered to %d new items (of %d)", len(new_items), len(items))
    return new_items


def update_state(state: dict, items_sent: list["FeedItem"]) -> dict:
    """Prepend new ids, dedupe preserving order, cap at MAX_SEEN."""
    new_ids = [it.id for it in items_sent]
    merged: list[str] = []
    seen: set[str] = set()
    for _id in new_ids + list(state.get("seen_ids") or []):
        if _id and _id not in seen:
            merged.append(_id)
            seen.add(_id)
        if len(merged) >= MAX_SEEN:
            break
    state["seen_ids"] = merged
    state["last_run_utc"] = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    return state


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Saved state: %d ids", len(state.get("seen_ids") or []))
