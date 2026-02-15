from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .dependencies import get_engine

router = APIRouter()


class PlanRequest(BaseModel):
    include_onbekend_fallback: bool = Field(default=False)


class ApplyRequest(BaseModel):
    approved_action_ids: list[str] = Field(default_factory=list)


class IgnoreRequest(BaseModel):
    fingerprints: list[str] = Field(default_factory=list)


@router.get("/health")
async def health() -> dict[str, Any]:
    """Health check."""
    try:
        engine = get_engine()
        has_token = bool(engine.ha.token)
        return {
            "ok": True,
            "detail": "API running",
            "ha_connected": has_token,
        }
    except Exception as e:
        return {
            "ok": False,
            "detail": str(e),
            "ha_connected": False,
        }


@router.get("/audit")
async def audit() -> dict[str, Any]:
    try:
        engine = get_engine()
        return await engine.audit()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/plan")
async def plan(req: PlanRequest) -> dict[str, Any]:
    try:
        engine = get_engine()
        return await engine.plan(include_onbekend_fallback=req.include_onbekend_fallback)
    except Exception as e:
        return {"ok": False, "error": str(e), "plan": {"actions": []}}


@router.post("/apply")
async def apply(req: ApplyRequest) -> dict[str, Any]:
    try:
        engine = get_engine()
        return await engine.apply(approved_action_ids=req.approved_action_ids)
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/rollback")
async def rollback() -> dict[str, Any]:
    try:
        engine = get_engine()
        return await engine.rollback()
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/plan")
async def get_plan() -> dict[str, Any]:
    engine = get_engine()
    return {"plan": engine.load_plan()}


@router.get("/rollback")
async def get_rollback() -> dict[str, Any]:
    engine = get_engine()
    return {"rollback": engine.load_rollback()}


@router.post("/ignore")
async def ignore_actions(req: IgnoreRequest) -> dict[str, Any]:
    try:
        engine = get_engine()
        result = engine.add_ignored(req.fingerprints)
        return {"ok": True, "ignored_count": len(result)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.delete("/ignore")
async def unignore_actions(req: IgnoreRequest) -> dict[str, Any]:
    try:
        engine = get_engine()
        result = engine.remove_ignored(req.fingerprints)
        return {"ok": True, "ignored_count": len(result)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/ignore/clear")
async def clear_ignored() -> dict[str, Any]:
    try:
        engine = get_engine()
        engine.clear_ignored()
        return {"ok": True, "ignored_count": 0}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/ignore")
async def get_ignored() -> dict[str, Any]:
    try:
        engine = get_engine()
        ignored = engine.load_ignored()
        return {"ok": True, "ignored": ignored, "ignored_count": len(ignored)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
