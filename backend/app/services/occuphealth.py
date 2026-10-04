"""职业健康监护业务规则：体检周期判定、结论口径合并、复查待办与岗位异动联动。

判定口径全系统只留这一份：
- 体检周期按「危害因素 + 累计工龄」查 CYCLE_RULES，一人接触多种危害因素时取最短周期；
- 体检结论按 CONCLUSION_SEVERITY 分档，多条判定冲突时以更严的那一档为准；
- 已存档的记录保留原判定标准版本，不按新标准重算。
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Any

from app.services.occuphealthtransfer import create_transfer_for_judgement
from app.store import store

MODULE = "occuphealth"

# 危害因素 -> [(累计工龄上限(年), 体检周期(月))]，按工龄从小到大取命中的第一档；None 表示不限工龄。
CYCLE_RULES: dict[str, list[tuple[float | None, int]]] = {
    "粉尘": [(10, 24), (None, 12)],
    "噪声": [(None, 12)],
    "有毒有害气体": [(5, 24), (None, 12)],
}

# 结论严重度从轻到重；两条判定冲突时以更严的那一档为准。
CONCLUSION_SEVERITY = ["目前未见异常", "其他疾病或异常", "复查", "疑似职业病", "职业禁忌证"]

# 当前执行的判定标准版本；历史纸质回填的记录保留原版本号。
STANDARD_VERSION = "GBZ188-2026"
BACKFILL_VERSION = "历史纸质回填"

REQUIRED_FIELDS = ["姓名", "岗位类别", "接触危害因素", "累计工龄", "体检日期"]
STATUS_ORDER = ["待复查", "已完成", "已存档"]
# 需要落到岗位异动登记待办的结论档。
TRANSFER_CONCLUSIONS = {"疑似职业病", "职业禁忌证"}
REVIEW_DAYS = 60


def parse_hazards(raw: Any) -> list[str]:
    """把「粉尘、噪声」这类写法拆成危害因素列表，兼容顿号、逗号、斜杠。"""
    text = str(raw or "").replace("/", "、").replace(",", "、").replace("，", "、")
    return [part.strip() for part in text.split("、") if part.strip()]


def cycle_months(hazards: list[str], seniority_years: float) -> int | None:
    """按危害因素和累计工龄定体检周期；多种危害因素并存时取最短（最严）周期。"""
    months: list[int] = []
    for hazard in hazards:
        tiers = CYCLE_RULES.get(hazard)
        if not tiers:
            continue
        for limit, cycle in tiers:
            if limit is None or seniority_years < limit:
                months.append(cycle)
                break
    return min(months) if months else None


def merge_conclusions(candidates: list[str]) -> str | None:
    """多条判定合并成唯一结论：保留严重度最高（最严）的那一档。"""
    known = [item for item in candidates if item in CONCLUSION_SEVERITY]
    if not known:
        return None
    return max(known, key=CONCLUSION_SEVERITY.index)


def add_months(day: date, months: int) -> date:
    """体检日期往后推若干个整月，月底日期按目标月天数收拢。"""
    month_index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(month_index, 12)
    last_day = monthrange(year, month + 1)[1]
    return date(year, month + 1, min(day.day, last_day))


def _parse_date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw or "").strip())
    except ValueError:
        return None


def _disable_certificates(person_no: str, name: str) -> int:
    """判定为职业禁忌证时，把该人员在持证管理里的对应资质全部停用。"""
    count = 0
    for row in store.rows("certificate"):
        matched = (person_no and str(row.get("人员编号")) == person_no) or str(row.get("姓名")) == name
        if not matched or row.get("status") in {"已停用", "已注销"}:
            continue
        row["status"] = "已停用"
        row["证书状态"] = "已停用（职业禁忌）"
        row["pending"] = False
        row["abnormal"] = True
        count += 1
    return count


class OccuphealthService:
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
            rows = [
                row
                for row in rows
                if keyword in str(row.get("姓名", "")) or keyword in str(row.get("档案编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: (str(row.get("体检日期", "")), int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def _build_entry(self, values: dict[str, Any], *, version: str) -> tuple[dict[str, Any] | None, list[str]]:
        """把登记或回填的字段整理成一条监护档案；岗位类别为空一律不许保存。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        try:
            seniority = float(str(values.get("累计工龄")).strip())
        except ValueError:
            return None, ["累计工龄需为数字"]
        exam_date = _parse_date(values.get("体检日期"))
        if exam_date is None:
            return None, ["体检日期需为 YYYY-MM-DD 格式"]
        hazards = parse_hazards(values.get("接触危害因素"))
        months = cycle_months(hazards, seniority)
        if months is None:
            return None, [f"接触危害因素不在判定口径内：{'、'.join(hazards) or '空'}"]

        detail = values.get("判定明细")
        candidates = [str(item).strip() for item in detail.values()] if isinstance(detail, dict) else []
        candidates.append(str(values.get("体检结论") or "").strip())
        conclusion = merge_conclusions(candidates)
        if conclusion is None:
            return None, [f"体检结论需为：{'、'.join(CONCLUSION_SEVERITY)}"]

        rows = store.rows(MODULE)
        entry_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": entry_id,
            "档案编号": f"HEAL-{entry_id:04d}",
            "姓名": str(values.get("姓名")).strip(),
            "人员编号": str(values.get("人员编号") or "").strip(),
            "岗位类别": str(values.get("岗位类别")).strip(),
            "接触危害因素": "、".join(hazards),
            "累计工龄": seniority,
            "体检类别": str(values.get("体检类别") or "在岗期间").strip(),
            "体检日期": exam_date.isoformat(),
            "体检周期(月)": months,
            "下次体检日期": add_months(exam_date, months).isoformat(),
            "体检结论": conclusion,
            "复查到期日": "",
            "复查结论": "",
            "判定标准版本": version,
        }
        return entry, []

    def _apply_side_effects(self, entry: dict[str, Any]) -> list[str]:
        """判定结果落岗位异动待办；职业禁忌证同时停用对应资质。"""
        notes: list[str] = []
        conclusion = str(entry.get("体检结论"))
        if conclusion in TRANSFER_CONCLUSIONS:
            transfer = create_transfer_for_judgement(
                name=str(entry.get("姓名")),
                person_no=str(entry.get("人员编号") or ""),
                post=str(entry.get("岗位类别")),
                conclusion=conclusion,
                source_no=str(entry.get("档案编号")),
            )
            notes.append(f"已落岗位异动待办 {transfer['异动编号']}")
        if conclusion == "职业禁忌证":
            count = _disable_certificates(str(entry.get("人员编号") or ""), str(entry.get("姓名")))
            notes.append(f"已停用 {count} 项对应资质" if count else "未查到可停用的对应资质")
        return notes

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        entry, errors = self._build_entry(values, version=STANDARD_VERSION)
        if entry is None:
            return None, errors
        if entry["体检结论"] == "复查":
            exam_date = date.fromisoformat(entry["体检日期"])
            entry["复查到期日"] = (exam_date + timedelta(days=REVIEW_DAYS)).isoformat()
            entry["status"] = "待复查"
            entry["pending"] = True  # 复查结论填完之前一直挂在待办里
        else:
            entry["status"] = "已完成"
            entry["pending"] = False
        entry["abnormal"] = entry["体检结论"] in {"复查", "疑似职业病", "职业禁忌证"}
        entry["档案状态"] = entry["status"]
        store.rows(MODULE).append(entry)
        notes = self._apply_side_effects(entry)
        if notes:
            entry["处理说明"] = "；".join(notes)
        return entry, []

    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"监护档案 {entry_id} 不存在或已归档"
        if entry.get("status") == "已存档":
            return None, "已存档的体检结论保持原判定口径，不按新标准重算"
        if action == "登记复查结论":
            if entry.get("status") != "待复查":
                return None, "只有待复查的档案才能登记复查结论"
            conclusion = str(values.get("复查结论") or "").strip()
            if conclusion not in CONCLUSION_SEVERITY or conclusion == "复查":
                return None, f"复查结论需给出最终判定档：{'、'.join(item for item in CONCLUSION_SEVERITY if item != '复查')}"
            entry["复查结论"] = conclusion
            entry["体检结论"] = conclusion
            entry["status"] = "已完成"
            entry["档案状态"] = "已完成"
            entry["pending"] = False  # 复查结论填完，待办结束
            entry["abnormal"] = conclusion in {"疑似职业病", "职业禁忌证"}
            notes = self._apply_side_effects(entry)
            suffix = f"，{'；'.join(notes)}" if notes else ""
            return entry, f"复查结论已登记，复查待办结束{suffix}"
        if action == "归档":
            if entry.get("status") != "已完成":
                return None, "复查结论填完之前不能归档"
            entry["status"] = "已存档"
            entry["档案状态"] = "已存档"
            entry["pending"] = False
            return entry, "监护档案已归档，结论按原判定口径封存"
        return None, f"动作「{action}」不属于职业健康监护可执行范围"

    def backfill_entries(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
        """历史纸质体检表回填：逐条校验后按体检日期顺序入库，结论保留原口径不重算。"""
        if not items:
            return [], ["没有需要回填的体检记录"]
        prepared: list[dict[str, Any]] = []
        errors: list[str] = []
        for index, values in enumerate(items, start=1):
            entry, entry_errors = self._build_entry(values, version=str(values.get("判定标准版本") or BACKFILL_VERSION))
            if entry is None:
                errors.extend(f"第 {index} 条：{message}" for message in entry_errors)
            else:
                prepared.append(entry)
        if errors:
            return [], errors
        prepared.sort(key=lambda row: (str(row.get("体检日期")), int(row.get("id", 0))))
        # 排序后重新编号，保证档案编号与体检日期顺序一致。
        rows = store.rows(MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        for offset, entry in enumerate(prepared):
            entry["id"] = next_id + offset
            entry["档案编号"] = f"HEAL-{entry['id']:04d}"
            entry["status"] = "已存档"
            entry["档案状态"] = "已存档"
            entry["pending"] = False
            entry["abnormal"] = False
            rows.append(entry)
        return prepared, []
