"""岗位异动登记业务规则。

两类异动来源：
- 职业健康监护判定「职业禁忌/职业病」后由健康服务自动开单，进来就是「待调岗」待办；
- 安全科手工登记的普通调岗。

调岗完成时回调健康档案，把对应的「岗位异动」待办一并关闭——判定结果只有在
异动登记里走完才算闭环。
"""
from __future__ import annotations

from typing import Any

from app.services.health import HealthService
from app.store import store

MODULE = "jobtransfer"

REQUIRED_FIELDS = ["人员编号", "姓名", "原岗位类别", "异动原因"]
STATUS_ORDER = ["待调岗", "已调岗", "已撤销"]


class JobTransferService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        pending_only: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("人员编号", "")) or keyword in str(row.get("姓名", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if pending_only:
            rows = [row for row in rows if row.get("pending")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "异动编号": f"JOBT-{len(rows) + 1:04d}",
            "人员编号": str(values["人员编号"]).strip(),
            "姓名": str(values["姓名"]).strip(),
            "原岗位类别": str(values["原岗位类别"]).strip(),
            "新岗位类别": str(values.get("新岗位类别") or "").strip(),
            "异动原因": str(values["异动原因"]).strip(),
            "体检日期": str(values.get("体检日期") or "").strip(),
            "申请日期": str(values.get("申请日期") or "").strip(),
            "完成日期": "",
            "档案id": None,
            "体检序号": None,
            "待办编号": "",
            "关联证书编号": "",
            "证书处置": "",
            "status": "待调岗",
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, []

    def complete_transfer(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"岗位异动单 {entry_id} 不存在"
        if entry["status"] == "已调岗":
            return None, "该异动单已完成调岗，不能重复办理"
        if entry["status"] == "已撤销":
            return None, "该异动单已撤销，不能再办理调岗"
        new_post = str(values.get("新岗位类别") or "").strip()
        if not new_post:
            return None, "调岗完成必须填写新岗位类别"
        finish_date = str(values.get("完成日期") or "").strip()
        if not finish_date:
            return None, "调岗完成必须填写完成日期"

        entry["新岗位类别"] = new_post
        entry["完成日期"] = finish_date
        entry["status"] = "已调岗"
        entry["pending"] = False
        entry["abnormal"] = False

        note = f"已调岗至「{new_post}」，完成日期 {finish_date}"
        if entry.get("档案id") and entry.get("待办编号"):
            HealthService().close_transfer_todo(int(entry["档案id"]), entry["待办编号"], note)
        return entry, f"{entry['姓名']} 已调岗至「{new_post}」，关联健康监护待办同步关闭"

    def cancel_transfer(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"岗位异动单 {entry_id} 不存在"
        if entry["status"] != "待调岗":
            return None, f"当前状态为「{entry['status']}」，不能撤销"
        entry["status"] = "已撤销"
        entry["pending"] = False
        return entry, "异动单已撤销（健康监护侧待办需在档案中另行处置）"
