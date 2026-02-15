import json
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from .ha_ws import HAWebSocketClient
from .model import Action, asdict_action
from .rules import load_rules
from .util import is_suffix_duplicate_entity, tokenize


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_active_state(state_obj: dict[str, Any] | None) -> bool:
    if not state_obj:
        return False
    st = state_obj.get("state")
    if st is None:
        return False
    return st != "unavailable"


def _effective_area_id(
    entity_reg: dict[str, Any],
    device_by_id: dict[str, Any],
) -> str | None:
    # Effective area = entity.area_id if set; else device.area_id if linked.
    area_id = entity_reg.get("area_id")
    if area_id:
        return area_id
    device_id = entity_reg.get("device_id")
    if not device_id:
        return None
    return device_by_id.get(device_id, {}).get("area_id")


def _normalize_name(s: str) -> str:
    return (s or "").strip().lower()


def _looks_generic_media_name(name: str) -> bool:
    n = _normalize_name(name)
    if not n:
        return True
    generic = {
        "tv",
        "speaker",
        "speakers",
        "chromecast",
        "google cast",
        "google home",
        "media player",
        "mediaplayer",
        "nest audio",
        "nest mini",
        "home",
        "default",
        "unknown",
    }
    return n in generic or n.startswith("media player")


def _media_base_label(entity_id: str, friendly: str) -> str:
    e = _normalize_name(entity_id)
    f = _normalize_name(friendly)
    hay = f"{e} {f}"
    if "tv" in hay:
        return "TV"
    if "speaker" in hay or "sonos" in hay or "nest" in hay:
        return "Speaker"
    if "beamer" in hay or "projector" in hay:
        return "Beamer"
    return "Media"


class HousekeeperEngine:
    def __init__(
        self,
        ha: HAWebSocketClient,
        onbekend_area_name: str,
        confidence_threshold: float,
        data_dir: str,
    ):
        self.ha = ha
        self.onbekend_area_name = onbekend_area_name
        self.confidence_threshold = confidence_threshold
        self.data_dir = data_dir

        os.makedirs(self.data_dir, exist_ok=True)
        self.plan_path = os.path.join(self.data_dir, "plan.json")
        self.rollback_path = os.path.join(self.data_dir, "rollback.json")
        self.ignored_path = os.path.join(self.data_dir, "ignored.json")
        self.rules_path = os.environ.get("HOUSEKEEPER_RULES_PATH")

    def _load_rules(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return load_rules(self.rules_path)

    @staticmethod
    def _compile_regex(pattern: str) -> re.Pattern | None:
        try:
            return re.compile(pattern, flags=re.IGNORECASE)
        except Exception:
            return None

    async def health(self) -> tuple[bool, dict[str, Any]]:
        try:
            await self.ha.connect()
            return True, {"ha_ws_url": self.ha.url}
        except Exception as e:
            return False, {"error": str(e), "ha_ws_url": self.ha.url}

    async def _fetch(self) -> dict[str, Any]:
        areas = await self.ha.area_list()
        devices = await self.ha.device_list()
        entities = await self.ha.entity_list()
        states = await self.ha.get_states()

        states_by_entity_id = {s.get("entity_id"): s for s in states if s.get("entity_id")}

        return {
            "areas": areas,
            "devices": devices,
            "entities": entities,
            "states_by_entity_id": states_by_entity_id,
        }

    async def audit(self) -> dict[str, Any]:
        d = await self._fetch()

        areas = d["areas"]
        devices = d["devices"]
        entities = d["entities"]
        states_by_entity_id = d["states_by_entity_id"]

        area_name_by_id = {a.get("area_id"): a.get("name") for a in areas if a.get("area_id")}
        area_id_by_name = {
            a.get("name"): a.get("area_id") for a in areas if a.get("name") and a.get("area_id")
        }

        device_by_id = {dv.get("id"): dv for dv in devices if dv.get("id")}
        entities_by_device_id: dict[str, list[dict[str, Any]]] = {}
        for er in entities:
            did = er.get("device_id")
            if not did:
                continue
            entities_by_device_id.setdefault(did, []).append(er)

        devices_without_area = []
        for dv in devices:
            if not dv.get("area_id"):
                devices_without_area.append(
                    {
                        "device_id": dv.get("id"),
                        "name": dv.get("name_by_user") or dv.get("name") or "",
                    }
                )

        entities_without_effective_area = []
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id:
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            if not _effective_area_id(er, device_by_id):
                device_id = er.get("device_id")
                entities_without_effective_area.append(
                    {
                        "entity_id": entity_id,
                        "name": er.get("name") or er.get("original_name") or "",
                        "device_id": device_id,
                    }
                )

        entity_ids = {e.get("entity_id") for e in entities if e.get("entity_id")}
        suffix_dupes = []
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id:
                continue
            is_dup, base = is_suffix_duplicate_entity(entity_id)
            if is_dup and base in entity_ids:
                suffix_dupes.append({"entity_id": entity_id, "base_entity_id": base})

        unique_id_dupes = []
        by_unique_id: dict[str, list[str]] = {}
        for er in entities:
            uid = er.get("unique_id")
            eid = er.get("entity_id")
            if uid and eid:
                by_unique_id.setdefault(uid, []).append(eid)
        for uid, eids in by_unique_id.items():
            if len(eids) > 1:
                unique_id_dupes.append({"unique_id": uid, "entity_ids": sorted(eids)})

        generic_media = []
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id or not entity_id.startswith("media_player."):
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            friendly = (
                er.get("name")
                or er.get("original_name")
                or str((st.get("attributes") or {}).get("friendly_name") or "")
            )
            if _looks_generic_media_name(friendly):
                generic_media.append(
                    {
                        "entity_id": entity_id,
                        "current_name": friendly,
                        "effective_area_id": _effective_area_id(er, device_by_id),
                    }
                )

        helpers = []
        for er in entities:
            entity_id = er.get("entity_id") or ""
            if not (
                entity_id.startswith("input_")
                or entity_id.startswith("sensor.")
                or entity_id.startswith("template.")
            ):
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            helpers.append(
                {"entity_id": entity_id, "effective_area_id": _effective_area_id(er, device_by_id)}
            )

        return {
            "generated_at": _now_iso(),
            "counts": {
                "areas": len(areas),
                "devices": len(devices),
                "entities": len(entities),
                "devices_without_area": len(devices_without_area),
                "entities_without_effective_area": len(entities_without_effective_area),
                "suffix_duplicate_entities": len(suffix_dupes),
                "unique_id_duplicate_groups": len(unique_id_dupes),
                "generic_media_players": len(generic_media),
            },
            "devices_without_area": devices_without_area,
            "entities_without_effective_area": entities_without_effective_area,
            "suffix_duplicate_entities": suffix_dupes,
            "unique_id_duplicates": unique_id_dupes,
            "generic_media_players": generic_media,
            "helpers": helpers,
            "area_id_by_name": area_id_by_name,
            "area_name_by_id": area_name_by_id,
        }

    async def plan(self, include_onbekend_fallback: bool) -> dict[str, Any]:
        d = await self._fetch()
        areas = d["areas"]
        devices = d["devices"]
        entities = d["entities"]
        states_by_entity_id = d["states_by_entity_id"]

        rules, rules_meta = self._load_rules()

        area_tokens = []
        area_names = set()
        area_name_by_id = {}
        for a in areas:
            if not a.get("area_id") or not a.get("name"):
                continue
            area_names.add(a["name"])
            area_name_by_id[a["area_id"]] = a["name"]
            area_tokens.append((a["area_id"], a["name"], tokenize(a["name"])))

        device_by_id = {dv.get("id"): dv for dv in devices if dv.get("id")}
        entities_by_device_id: dict[str, list[dict[str, Any]]] = {}
        for er in entities:
            did = er.get("device_id")
            if not did:
                continue
            entities_by_device_id.setdefault(did, []).append(er)

        actions: list[Action] = []
        planned_entity_area: set[str] = set()
        planned_entity_remove: set[str] = set()
        planned_entity_hide: set[str] = set()

        # Area renames from rules.
        area_by_name_ci: dict[str, list[dict[str, Any]]] = {}
        for a in areas:
            nm = a.get("name")
            if not nm:
                continue
            area_by_name_ci.setdefault(str(nm).strip().lower(), []).append(a)

        for r in rules.get("area_renames", []) or []:
            if not isinstance(r, dict):
                continue
            src = str(r.get("from") or "").strip()
            dst = str(r.get("to") or "").strip()
            if not src or not dst or src == dst:
                continue
            req = bool(r.get("requires_approval", True))

            src_areas = area_by_name_ci.get(src.lower(), [])
            dst_areas = area_by_name_ci.get(dst.lower(), [])
            if len(src_areas) != 1:
                continue
            if len(dst_areas) != 0:
                continue
            area_id = src_areas[0].get("area_id")
            if not area_id:
                continue
            actions.append(
                Action(
                    id=str(uuid.uuid4()),
                    type="rename_area",
                    payload={"area_id": area_id, "name": dst},
                    reason=f"Rule: rename area '{src}' -> '{dst}'.",
                    confidence=0.9,
                    requires_approval=req,
                )
            )

        # Explicit entity removals/hides from rules.
        entity_ids = {e.get("entity_id") for e in entities if e.get("entity_id")}

        erem = rules.get("entity_remove", {}) or {}
        for eid in erem.get("ids", []) or []:
            if not isinstance(eid, str):
                continue
            if eid in entity_ids and eid not in planned_entity_remove:
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="remove_entity_registry_entry",
                        payload={"entity_id": eid},
                        reason="Rule: explicit entity removal.",
                        confidence=1.0,
                        requires_approval=True,
                    )
                )
                planned_entity_remove.add(eid)

        for rr in erem.get("regex", []) or []:
            if not isinstance(rr, dict):
                continue
            pat = str(rr.get("pattern") or "")
            rx = self._compile_regex(pat)
            if not rx:
                continue
            req = bool(rr.get("requires_approval", True))
            for eid in sorted([x for x in entity_ids if isinstance(x, str)]):
                if eid in planned_entity_remove:
                    continue
                if rx.search(eid):
                    actions.append(
                        Action(
                            id=str(uuid.uuid4()),
                            type="remove_entity_registry_entry",
                            payload={"entity_id": eid},
                            reason=f"Rule: entity_id matches /{pat}/.",
                            confidence=0.95,
                            requires_approval=req,
                        )
                    )
                    planned_entity_remove.add(eid)

        ehide = rules.get("entity_hide", {}) or {}
        for eid in ehide.get("ids", []) or []:
            if not isinstance(eid, str):
                continue
            if eid in entity_ids and eid not in planned_entity_hide:
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="hide_entity",
                        payload={"entity_id": eid, "hidden_by": "user"},
                        reason="Rule: explicit entity hide.",
                        confidence=1.0,
                        requires_approval=True,
                    )
                )
                planned_entity_hide.add(eid)

        for rr in ehide.get("regex", []) or []:
            if not isinstance(rr, dict):
                continue
            pat = str(rr.get("pattern") or "")
            rx = self._compile_regex(pat)
            if not rx:
                continue
            req = bool(rr.get("requires_approval", True))
            for eid in sorted([x for x in entity_ids if isinstance(x, str)]):
                if eid in planned_entity_hide:
                    continue
                if rx.search(eid):
                    actions.append(
                        Action(
                            id=str(uuid.uuid4()),
                            type="hide_entity",
                            payload={"entity_id": eid, "hidden_by": "user"},
                            reason=f"Rule: entity_id matches /{pat}/.",
                            confidence=0.95,
                            requires_approval=req,
                        )
                    )
                    planned_entity_hide.add(eid)

        # Entities: if device has area and entity has none -> set entity area (deterministic).
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id:
                continue
            if entity_id in planned_entity_remove:
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            if er.get("area_id"):
                continue
            device_id = er.get("device_id")
            if not device_id:
                continue
            device_area_id = device_by_id.get(device_id, {}).get("area_id")
            if not device_area_id:
                continue
            actions.append(
                Action(
                    id=str(uuid.uuid4()),
                    type="set_entity_area",
                    payload={"entity_id": entity_id, "area_id": device_area_id},
                    reason="Entity has no area_id; device has area_id, so entity can inherit deterministically.",
                    confidence=1.0,
                    requires_approval=False,
                )
            )
            planned_entity_area.add(entity_id)

        # Devices: if device has no area, and all linked entities resolve to exactly 1 effective area -> set device area.
        for dv in devices:
            device_id = dv.get("id")
            if not device_id or dv.get("area_id"):
                continue
            linked = entities_by_device_id.get(device_id) or []
            effective_area_ids = set()
            for er in linked:
                eid = er.get("entity_id")
                if not eid:
                    continue
                st = states_by_entity_id.get(eid)
                if not _is_active_state(st):
                    continue
                # Use entity explicit area only here (avoid circular inference from the same device).
                if er.get("area_id"):
                    effective_area_ids.add(er.get("area_id"))
            if len(effective_area_ids) == 1:
                area_id = next(iter(effective_area_ids))
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="set_device_area",
                        payload={"device_id": device_id, "area_id": area_id},
                        reason="Device has no area_id; all linked active entities have exactly 1 explicit area_id.",
                        confidence=0.98,
                        requires_approval=False,
                    )
                )

        needs_fallback_onbekend = False

        # Entities without effective area: try token-match to a single area.
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id:
                continue
            if entity_id in planned_entity_area:
                continue
            if entity_id in planned_entity_remove:
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            if er.get("area_id"):
                continue
            device_id = er.get("device_id")
            if device_id and device_by_id.get(device_id, {}).get("area_id"):
                continue

            hay = " ".join(
                [
                    entity_id,
                    str(er.get("name") or ""),
                    str(er.get("original_name") or ""),
                    str((st.get("attributes") or {}).get("friendly_name") or ""),
                ]
            )
            ht = tokenize(hay)
            matches = []
            for area_id, area_name, at in area_tokens:
                if at and at <= ht:
                    matches.append((area_id, area_name))
            if len(matches) == 1:
                area_id, area_name = matches[0]
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="set_entity_area",
                        payload={"entity_id": entity_id, "area_id": area_id},
                        reason=f"Token match to area name '{area_name}' from entity metadata.",
                        confidence=0.95,
                        requires_approval=False,
                    )
                )
                planned_entity_area.add(entity_id)
            elif include_onbekend_fallback:
                needs_fallback_onbekend = True

        if (
            include_onbekend_fallback
            and needs_fallback_onbekend
            and (self.onbekend_area_name not in area_names)
        ):
            actions.append(
                Action(
                    id=str(uuid.uuid4()),
                    type="create_area",
                    payload={"name": self.onbekend_area_name},
                    reason="Fallback area requested to ensure everything has an effective area.",
                    confidence=0.6,
                    requires_approval=True,
                )
            )

        # Entities still without effective area: optionally place into Onbekend (approval).
        if include_onbekend_fallback:
            onbekend_area_id = None
            for a in areas:
                if a.get("name") == self.onbekend_area_name:
                    onbekend_area_id = a.get("area_id")
                    break
            if onbekend_area_id:
                for er in entities:
                    entity_id = er.get("entity_id")
                    if not entity_id:
                        continue
                    if entity_id in planned_entity_area:
                        continue
                    if entity_id in planned_entity_remove:
                        continue
                    st = states_by_entity_id.get(entity_id)
                    if not _is_active_state(st):
                        continue
                    if _effective_area_id(er, device_by_id):
                        continue
                    actions.append(
                        Action(
                            id=str(uuid.uuid4()),
                            type="set_entity_area",
                            payload={"entity_id": entity_id, "area_id": onbekend_area_id},
                            reason=f"Fallback: put entity into area '{self.onbekend_area_name}'.",
                            confidence=0.6,
                            requires_approval=True,
                        )
                    )
                    planned_entity_area.add(entity_id)

        # Suffix duplicate entities: propose removal (approval required).
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id:
                continue
            if entity_id in planned_entity_remove:
                continue
            is_dup, base = is_suffix_duplicate_entity(entity_id)
            if not is_dup or base not in entity_ids:
                continue
            actions.append(
                Action(
                    id=str(uuid.uuid4()),
                    type="remove_entity_registry_entry",
                    payload={"entity_id": entity_id},
                    reason=f"Entity id looks like a suffix duplicate of '{base}'.",
                    confidence=0.9,
                    requires_approval=True,
                )
            )
            planned_entity_remove.add(entity_id)

        # Unique_id duplicates: suggest hiding all but the first one (approval).
        by_unique_id: dict[str, list[str]] = {}
        for er in entities:
            uid = er.get("unique_id")
            eid = er.get("entity_id")
            if uid and eid:
                by_unique_id.setdefault(uid, []).append(eid)
        for uid, eids in by_unique_id.items():
            if len(eids) <= 1:
                continue
            kept = sorted(eids)[0]
            for eid in sorted(eids)[1:]:
                if eid in planned_entity_hide or eid in planned_entity_remove:
                    continue
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="hide_entity",
                        payload={"entity_id": eid, "hidden_by": "user"},
                        reason=f"Duplicate unique_id '{uid}'. Keeping '{kept}', hiding '{eid}'.",
                        confidence=0.9,
                        requires_approval=True,
                    )
                )
                planned_entity_hide.add(eid)

        area_id_by_name_lower = {
            str(a.get("name")).strip().lower(): a.get("area_id")
            for a in areas
            if a.get("name") and a.get("area_id")
        }

        # Entity area assignment rules (regex -> area).
        for rr in rules.get("entity_area", []) or []:
            if not isinstance(rr, dict):
                continue
            pat = str(rr.get("pattern") or "")
            area_name = str(rr.get("area") or "").strip()
            if not pat or not area_name:
                continue
            rx = self._compile_regex(pat)
            if not rx:
                continue
            req = bool(rr.get("requires_approval", True))
            overwrite = bool(rr.get("overwrite", False))
            target_area_id = area_id_by_name_lower.get(area_name.lower())
            if not target_area_id:
                continue
            for er in entities:
                entity_id = er.get("entity_id") or ""
                if not entity_id or entity_id in planned_entity_remove:
                    continue
                st = states_by_entity_id.get(entity_id)
                if not _is_active_state(st):
                    continue
                if not overwrite and (
                    _effective_area_id(er, device_by_id) or entity_id in planned_entity_area
                ):
                    continue
                if rx.search(entity_id):
                    actions.append(
                        Action(
                            id=str(uuid.uuid4()),
                            type="set_entity_area",
                            payload={"entity_id": entity_id, "area_id": target_area_id},
                            reason=f"Rule: entity_id matches /{pat}/ -> area '{area_name}'.",
                            confidence=0.9,
                            requires_approval=req,
                        )
                    )
                    planned_entity_area.add(entity_id)

        # Device area assignment rules (device name regex -> area).
        for rr in rules.get("device_area", []) or []:
            if not isinstance(rr, dict):
                continue
            pat = str(rr.get("pattern") or "")
            area_name = str(rr.get("area") or "").strip()
            if not pat or not area_name:
                continue
            rx = self._compile_regex(pat)
            if not rx:
                continue
            req = bool(rr.get("requires_approval", True))
            overwrite = bool(rr.get("overwrite", False))
            target_area_id = area_id_by_name_lower.get(area_name.lower())
            if not target_area_id:
                continue
            for dv in devices:
                device_id = dv.get("id")
                if not device_id:
                    continue
                if dv.get("area_id") and not overwrite:
                    continue
                name = str(dv.get("name_by_user") or dv.get("name") or "")
                if not name:
                    continue
                if rx.search(name):
                    actions.append(
                        Action(
                            id=str(uuid.uuid4()),
                            type="set_device_area",
                            payload={"device_id": device_id, "area_id": target_area_id},
                            reason=f"Rule: device name matches /{pat}/ -> area '{area_name}'.",
                            confidence=0.9,
                            requires_approval=req,
                        )
                    )

        # Helpers: suggest strong areas based on keywords (approval).
        helper_area_rules = rules.get("helper_area_rules", []) or []
        for er in entities:
            entity_id = er.get("entity_id") or ""
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            if not entity_id:
                continue
            if entity_id in planned_entity_area:
                continue
            if _effective_area_id(er, device_by_id):
                continue
            tokens = tokenize(
                entity_id
                + " "
                + str(er.get("original_name") or "")
                + " "
                + str(er.get("name") or "")
            )
            for hr in helper_area_rules:
                if not isinstance(hr, dict):
                    continue
                area_name = str(hr.get("area") or "").strip()
                kws_raw = hr.get("keywords") or []
                kws = {
                    str(x).strip().lower() for x in kws_raw if isinstance(x, str) and str(x).strip()
                }
                if not area_name or not kws:
                    continue
                req = bool(hr.get("requires_approval", True))
                if not (kws & tokens):
                    continue
                # Only if target area exists.
                # (We can add create-area later, but keep safety.)
                target_area_id = area_id_by_name_lower.get(area_name.strip().lower())
                if not target_area_id:
                    continue
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="set_entity_area",
                        payload={"entity_id": entity_id, "area_id": target_area_id},
                        reason=f"Rule: keyword match suggests area '{area_name}'.",
                        confidence=0.85,
                        requires_approval=req,
                    )
                )
                break

        # Media players: propose renames for generic/empty names based on effective area (approval).
        media_candidates = []
        for er in entities:
            entity_id = er.get("entity_id")
            if not entity_id or not entity_id.startswith("media_player."):
                continue
            st = states_by_entity_id.get(entity_id)
            if not _is_active_state(st):
                continue
            eff_area_id = _effective_area_id(er, device_by_id)
            if not eff_area_id:
                continue
            current = (
                er.get("name")
                or er.get("original_name")
                or str((st.get("attributes") or {}).get("friendly_name") or "")
            )
            if not _looks_generic_media_name(current):
                continue
            base = _media_base_label(entity_id, current)
            media_candidates.append((eff_area_id, base, entity_id, current))

        # Stable numbering per (area, base).
        grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for area_id, base, entity_id, current in media_candidates:
            grouped.setdefault((area_id, base), []).append((entity_id, current))

        for (area_id, base), items in grouped.items():
            items_sorted = sorted(items, key=lambda x: x[0])
            area_name = area_name_by_id.get(area_id) or area_id
            need_numbers = len(items_sorted) > 1
            for idx, (entity_id, current) in enumerate(items_sorted, start=1):
                new_name = f"{base} {area_name}" + (f" {idx}" if need_numbers else "")
                actions.append(
                    Action(
                        id=str(uuid.uuid4()),
                        type="rename_entity",
                        payload={"entity_id": entity_id, "name": new_name},
                        reason=f"Generic media player name '{current}' -> '{new_name}' based on effective area.",
                        confidence=0.8,
                        requires_approval=True,
                    )
                )

        all_actions = [asdict_action(a) for a in actions]

        # Filter out ignored actions
        ignored = set(self.load_ignored())
        visible_actions = [a for a in all_actions if self.action_fingerprint(a) not in ignored]
        ignored_count = len(all_actions) - len(visible_actions)

        plan = {
            "created_at": _now_iso(),
            "rules": rules_meta,
            "actions": visible_actions,
            "area_name_by_id": area_name_by_id,
            "ignored_count": ignored_count,
        }
        self.save_plan(plan)
        return {"plan": plan}

    def save_plan(self, plan: dict[str, Any]) -> None:
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, sort_keys=True)

    def load_plan(self) -> dict[str, Any] | None:
        if not os.path.exists(self.plan_path):
            return None
        with open(self.plan_path, encoding="utf-8") as f:
            return json.load(f)

    def save_rollback(self, rb: dict[str, Any]) -> None:
        with open(self.rollback_path, "w", encoding="utf-8") as f:
            json.dump(rb, f, indent=2, sort_keys=True)

    def load_rollback(self) -> dict[str, Any] | None:
        if not os.path.exists(self.rollback_path):
            return None
        with open(self.rollback_path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def action_fingerprint(action: dict[str, Any]) -> str:
        atype = action.get("type", "")
        p = action.get("payload") or {}
        key = p.get("entity_id") or p.get("device_id") or p.get("area_id") or p.get("name") or ""
        return f"{atype}:{key}"

    def load_ignored(self) -> list[str]:
        if not os.path.exists(self.ignored_path):
            return []
        with open(self.ignored_path, encoding="utf-8") as f:
            return json.load(f)

    def save_ignored(self, fingerprints: list[str]) -> None:
        with open(self.ignored_path, "w", encoding="utf-8") as f:
            json.dump(sorted(set(fingerprints)), f, indent=2)

    def add_ignored(self, fingerprints: list[str]) -> list[str]:
        current = set(self.load_ignored())
        current.update(fingerprints)
        result = sorted(current)
        self.save_ignored(result)
        return result

    def remove_ignored(self, fingerprints: list[str]) -> list[str]:
        current = set(self.load_ignored())
        current -= set(fingerprints)
        result = sorted(current)
        self.save_ignored(result)
        return result

    def clear_ignored(self) -> None:
        self.save_ignored([])

    async def apply(self, approved_action_ids: list[str]) -> dict[str, Any]:
        plan = self.load_plan()
        if not plan:
            raise ValueError("No plan.json found; run /plan first")

        approved = set(approved_action_ids or [])
        actions = plan.get("actions") or []

        rollback_steps: list[dict[str, Any]] = []
        applied: list[str] = []
        skipped: list[dict[str, Any]] = []

        # Snapshot registries for rollback.
        entities = await self.ha.entity_list()
        areas = await self.ha.area_list()
        devices = await self.ha.device_list()
        entity_by_id = {e.get("entity_id"): e for e in entities if e.get("entity_id")}
        area_by_name = {a.get("name"): a for a in areas if a.get("name")}
        device_by_id = {d.get("id"): d for d in devices if d.get("id")}
        area_by_id = {a.get("area_id"): a for a in areas if a.get("area_id")}

        for a in actions:
            aid = a.get("id")
            if bool(a.get("requires_approval")) and aid not in approved:
                skipped.append({"id": aid, "reason": "requires_approval"})
                continue

            atype = a.get("type")
            payload = a.get("payload") or {}

            if atype == "create_area":
                name = payload.get("name")
                if not name:
                    skipped.append({"id": aid, "reason": "missing name"})
                    continue
                if name in area_by_name:
                    applied.append(aid)
                    continue
                res = await self.ha.area_create(name=name)
                area_id = res.get("area_id")
                rollback_steps.append(
                    {
                        "type": "note",
                        "note": "Area created; rollback does not delete areas.",
                        "area_id": area_id,
                        "name": name,
                    }
                )
                applied.append(aid)
                continue

            if atype == "set_entity_area":
                entity_id = payload.get("entity_id")
                area_id = payload.get("area_id")
                if not entity_id or not area_id:
                    skipped.append({"id": aid, "reason": "missing entity_id/area_id"})
                    continue
                before = entity_by_id.get(entity_id, {})
                rollback_steps.append(
                    {
                        "type": "entity_update",
                        "entity_id": entity_id,
                        "before": {"area_id": before.get("area_id")},
                    }
                )
                await self.ha.entity_update(entity_id=entity_id, area_id=area_id)
                applied.append(aid)
                continue

            if atype == "set_device_area":
                device_id = payload.get("device_id")
                area_id = payload.get("area_id")
                if not device_id or not area_id:
                    skipped.append({"id": aid, "reason": "missing device_id/area_id"})
                    continue
                before = device_by_id.get(device_id, {})
                rollback_steps.append(
                    {
                        "type": "device_update",
                        "device_id": device_id,
                        "before": {"area_id": before.get("area_id")},
                    }
                )
                await self.ha.device_update(device_id=device_id, area_id=area_id)
                applied.append(aid)
                continue

            if atype == "rename_entity":
                entity_id = payload.get("entity_id")
                name = payload.get("name")
                if not entity_id or not name:
                    skipped.append({"id": aid, "reason": "missing entity_id/name"})
                    continue
                before = entity_by_id.get(entity_id, {})
                rollback_steps.append(
                    {
                        "type": "entity_update",
                        "entity_id": entity_id,
                        "before": {"name": before.get("name")},
                    }
                )
                await self.ha.entity_update(entity_id=entity_id, name=name)
                applied.append(aid)
                continue

            if atype == "hide_entity":
                entity_id = payload.get("entity_id")
                hidden_by = payload.get("hidden_by", "user")
                if not entity_id:
                    skipped.append({"id": aid, "reason": "missing entity_id"})
                    continue
                before = entity_by_id.get(entity_id, {})
                rollback_steps.append(
                    {
                        "type": "entity_update",
                        "entity_id": entity_id,
                        # Roll back both fields if present; HA ignores unknown keys.
                        "before": {
                            "hidden_by": before.get("hidden_by"),
                            "disabled_by": before.get("disabled_by"),
                        },
                    }
                )
                # HA has changed "hide" semantics over time. Prefer hidden_by,
                # but fall back to disabled_by if hidden_by is not supported.
                try:
                    await self.ha.entity_update(entity_id=entity_id, hidden_by=hidden_by)
                except Exception:
                    await self.ha.entity_update(entity_id=entity_id, disabled_by=hidden_by)
                applied.append(aid)
                continue

            if atype == "remove_entity_registry_entry":
                entity_id = payload.get("entity_id")
                if not entity_id:
                    skipped.append({"id": aid, "reason": "missing entity_id"})
                    continue
                before = entity_by_id.get(entity_id)
                rollback_steps.append(
                    {"type": "entity_restore_note", "entity_id": entity_id, "before": before}
                )
                await self.ha.entity_remove(entity_id=entity_id)
                applied.append(aid)
                continue

            if atype == "rename_device":
                device_id = payload.get("device_id")
                name = payload.get("name")
                if not device_id or not name:
                    skipped.append({"id": aid, "reason": "missing device_id/name"})
                    continue
                before = device_by_id.get(device_id, {})
                rollback_steps.append(
                    {
                        "type": "device_update",
                        "device_id": device_id,
                        "before": {"name_by_user": before.get("name_by_user")},
                    }
                )
                await self.ha.device_update(device_id=device_id, name_by_user=name)
                applied.append(aid)
                continue

            if atype == "rename_area":
                area_id = payload.get("area_id")
                name = payload.get("name")
                if not area_id or not name:
                    skipped.append({"id": aid, "reason": "missing area_id/name"})
                    continue
                before = area_by_id.get(area_id, {})
                rollback_steps.append(
                    {
                        "type": "area_update",
                        "area_id": area_id,
                        "before": {"name": before.get("name")},
                    }
                )
                await self.ha.area_update(area_id=area_id, name=name)
                applied.append(aid)
                continue

            skipped.append({"id": aid, "reason": f"unsupported action type {atype}"})

        rb = {"created_at": _now_iso(), "steps": rollback_steps}
        self.save_rollback(rb)
        return {"applied_action_ids": applied, "skipped": skipped, "rollback": rb}

    async def rollback(self) -> dict[str, Any]:
        rb = self.load_rollback()
        if not rb:
            return {"ok": False, "detail": "No rollback.json found"}

        steps = rb.get("steps") or []
        reverted = 0
        errors: list[dict[str, Any]] = []

        # Roll back in reverse order (last change reverted first).
        for st in reversed(steps):
            try:
                stype = st.get("type")
                if stype == "entity_update":
                    entity_id = st.get("entity_id")
                    before = st.get("before") or {}
                    # HA needs area_id=None sent explicitly to clear it
                    await self.ha.entity_update(entity_id=entity_id, **before)
                    reverted += 1
                elif stype == "device_update":
                    device_id = st.get("device_id")
                    before = st.get("before") or {}
                    await self.ha.device_update(device_id=device_id, **before)
                    reverted += 1
                elif stype == "area_update":
                    area_id = st.get("area_id")
                    before = st.get("before") or {}
                    # Filter None values - area_update requires a name
                    clean = {k: v for k, v in before.items() if v is not None}
                    if clean:
                        await self.ha.area_update(area_id=area_id, **clean)
                    reverted += 1
                elif stype in ("note", "entity_restore_note"):
                    # Informational steps, nothing to revert
                    continue
            except Exception as e:
                errors.append({"step": st, "error": str(e)})

        return {"ok": len(errors) == 0, "reverted": reverted, "errors": errors}
