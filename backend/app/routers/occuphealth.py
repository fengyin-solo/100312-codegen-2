"""职业健康监护接口：维护接害人员体检档案，覆盖登记判定、复查销号、归档与历史回填。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BackfillPayload, EntryPayload, PageResult
from app.services.occuphealth import CONCLUSION_SEVERITY, CYCLE_RULES, STANDARD_VERSION, OccuphealthService

router = APIRouter(prefix="/api/occuphealth", tags=["职业健康监护"])

service = OccuphealthService()

LIST_FIELDS = ["档案编号", "姓名", "岗位类别", "接触危害因素", "累计工龄", "体检日期", "体检周期(月)", "下次体检日期", "体检结论", "复查到期日", "判定标准版本", "档案状态"]
STATUSES = ["待复查", "已完成", "已存档"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按姓名或档案编号检索"),
    status: str | None = Query(default=None, description="待复查、已完成、已存档"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按体检日期顺序列出监护档案；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出职业健康监护清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "occuphealth", "total": total, "items": items}


@router.get("/rules")
def judgement_rules() -> dict[str, Any]:
    """当前唯一生效的判定口径：周期规则、结论分档与标准版本，供登记页面对照。"""
    return {
        "标准版本": STANDARD_VERSION,
        "周期规则": CYCLE_RULES,
        "结论分档": CONCLUSION_SEVERITY,
        "冲突处理": "多条判定冲突时以更严的那一档为准；已存档结论不按新标准重算",
    }


@router.post("/backfill", response_model=ActionResult)
def backfill_entries(payload: BackfillPayload) -> ActionResult:
    """历史纸质体检表回填：整批校验通过后按体检日期顺序入库，任何一条不合格整批退回。"""
    entries, errors = service.backfill_entries(payload.items)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message=f"已按体检日期顺序回填 {len(entries)} 条历史体检记录", entry={"count": len(entries)})


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条监护档案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"监护档案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条体检记录：岗位类别为空直接退回，周期与结论由判定口径自动合并。"""
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    message = "体检记录已登记"
    if entry and entry.get("处理说明"):
        message = f"{message}，{entry['处理说明']}"
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条监护档案执行登记复查结论、归档；已存档记录不按新标准重算。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
