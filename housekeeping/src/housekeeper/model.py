from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ActionType = Literal[
    "set_entity_area",
    "set_device_area",
    "rename_entity",
    "rename_device",
    "remove_entity_registry_entry",
    "hide_entity",
    "rename_area",
    "create_area",
]


@dataclass(frozen=True)
class Action:
    id: str
    type: ActionType
    payload: dict[str, Any]
    reason: str
    confidence: float
    requires_approval: bool


def asdict_action(a: Action) -> dict[str, Any]:
    return {
        "id": a.id,
        "type": a.type,
        "payload": a.payload,
        "reason": a.reason,
        "confidence": a.confidence,
        "requires_approval": a.requires_approval,
    }
