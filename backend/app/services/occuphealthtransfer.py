"""岗位异动登记业务规则：接收职业健康判定落下的待办，跟踪异动落实情况。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "occuphealthtransfer"
REQUIRED_FIELDS = ["姓名", "原岗位类别", "触发结论"]
STATUS_ORDER = ["待落实", "已落实", "暂缓"]
ACTION_RULES = {"落实异动": "已落实", "暂缓异动": "暂缓"}
NEGATIVE_ACTIONS = ["暂缓异动"]


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


def create_transfer_for_judgement(
    *,
    name: str,
    person_no: str,
    post: str,
    conclusion: str,
    source_no: str,
) -> dict[str, Any]:
    """职业健康判定触发的异动待办：判定一落定就登记，等异动落实后才销号。"""
    rows = store.rows(MODULE)
    entry_id = _next_id(rows)
    measure = "调离接害岗位并停用相关资质" if conclusion == "职业禁忌证" else "调离原岗位，待诊断明确"
    entry = {
        "id": entry_id,
        "异动编号": f"TRAN-{entry_id:04d}",
        "姓名": name,
        "人员编号": person_no,
        "原岗位类别": post,
        "触发结论": conclusion,
        "建议措施": measure,
        "来源档案编号": source_no,
        "登记日期": date.today().isoformat(),
        "异动状态": STATUS_ORDER[0],
        "status": STATUS_ORDER[0],
        "pending": True,
        "abnormal": True,
    }
    rows.append(entry)
    return entry


class OccuphealthtransferService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("姓名", "")) or keyword in str(row.get("异动编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: (str(row.get("登记日期", "")), int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry_id = _next_id(rows)
        entry = {"id": entry_id, "异动编号": f"TRAN-{entry_id:04d}"}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["人员编号"] = values.get("人员编号") or ""
        entry["触发结论"] = values.get("触发结论")
        entry["建议措施"] = values.get("建议措施") or "调离接害岗位"
        entry["来源档案编号"] = values.get("来源档案编号") or ""
        entry["登记日期"] = values.get("登记日期") or date.today().isoformat()
        entry["异动状态"] = STATUS_ORDER[0]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"岗位异动 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于岗位异动可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if entry.get("status") == "已落实":
            return None, "岗位异动已落实，不再重复处理"
        entry["status"] = target
        entry["异动状态"] = target
        entry["pending"] = target == "待落实"
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"岗位异动已{target}"
