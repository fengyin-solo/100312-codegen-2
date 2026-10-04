"""职业健康监护档案接口。

围绕接害岗位人员建档、体检登记、复查随访、纸质回填与周期标准换版；
业务判定全部在 HealthService，路由层只做参数透传和错误转译。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.health import HealthService

router = APIRouter(prefix="/api/health-archive", tags=["职业健康监护"])

service = HealthService()

COLUMNS = [
    "档案编号", "人员编号", "姓名", "岗位类别", "接触危害因素", "累计工龄",
    "体检周期", "最新结论", "下次体检日期", "适用标准版本", "status",
]


@router.get("/standard")
def get_standard() -> dict[str, Any]:
    """唯一的体检周期判定口径（危害因素 × 累计工龄分档）。"""
    return service.standard()


@router.post("/standard/refresh", response_model=ActionResult)
def refresh_standard() -> ActionResult:
    """按新口径重排在档人员周期；已存档结论不重算。"""
    result = service.refresh_cycles()
    return ActionResult(
        ok=True,
        message=(
            f"已按{result['standard_version']}口径重排 {len(result['refreshed'])} 份在档档案，"
            f"跳过 {len(result['skipped_archived'])} 份已归档档案，历史结论未重算"
        ),
        entry=result,
    )


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按人员编号或姓名检索"),
    status: str | None = Query(default=None, description="在岗监护、已归档"),
    hazard: str | None = Query(default=None, description="按危害因素过滤：粉尘、噪声、有毒有害气体"),
    pending_only: bool = Query(default=False, description="只看待办未闭环的档案"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, hazard=hazard, pending_only=pending_only,
        page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "health", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"职业健康监护档案 {entry_id} 不存在")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """新建监护档案。岗位类别为空一律拒绝，不允许保存。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"建档失败：{'、'.join(missing)}")
    return ActionResult(ok=True, message="监护档案已建立，已挂上岗前体检待办", entry=entry)


@router.post("/{entry_id}/exams", response_model=ActionResult)
def record_exam(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记一次体检（上岗前/在岗期间/离岗时），结论按统一口径自动处置。"""
    entry, message = service.record_exam(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/followups", response_model=ActionResult)
def complete_followup(entry_id: int, payload: EntryPayload) -> ActionResult:
    """填报复查/职业病诊断结论；复查结论不填，复查待办就一直挂着。"""
    entry, message = service.complete_followup(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/backfill", response_model=ActionResult)
def backfill_paper(payload: EntryPayload) -> ActionResult:
    """历史纸质体检表按体检日期顺序回填，只存档、不补触发待办。"""
    records = payload.values.get("records")
    if not isinstance(records, list) or not records:
        return ActionResult(ok=False, message="请在 records 中提交至少一条纸质体检记录")
    backfilled, errors = service.backfill_paper(records)
    message = f"纸质体检表已按体检日期顺序回填 {len(backfilled)} 条"
    if errors:
        message += f"；{len(errors)} 条未通过校验未入库"
    return ActionResult(
        ok=not errors,
        message=message,
        entry={"backfilled": backfilled, "errors": errors},
    )
