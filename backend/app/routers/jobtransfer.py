"""岗位异动登记接口：承接职业健康判定结果，也支持手工登记普通调岗。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.jobtransfer import JobTransferService

router = APIRouter(prefix="/api/jobtransfer", tags=["岗位异动登记"])

service = JobTransferService()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按人员编号或姓名检索"),
    status: str | None = Query(default=None, description="待调岗、已调岗、已撤销"),
    pending_only: bool = Query(default=False, description="只看待调岗待办"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, pending_only=pending_only, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "jobtransfer", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"岗位异动单 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="岗位异动已登记，进入待调岗", entry=entry)


@router.post("/{entry_id}/complete", response_model=ActionResult)
def complete_transfer(entry_id: int, payload: EntryPayload) -> ActionResult:
    """完成调岗：填了新岗位类别和完成日期才闭环，健康侧待办同步关闭。"""
    entry, message = service.complete_transfer(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/cancel", response_model=ActionResult)
def cancel_transfer(entry_id: int) -> ActionResult:
    entry, message = service.cancel_transfer(entry_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
