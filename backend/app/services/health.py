"""职业健康监护业务规则。

口径只有这一份：体检周期、结论处置、待办挂起/关闭、资质停用都收在本服务里，
路由层与岗位异动服务都不自行判定。

关键规则（对应安全科的诉求）：

1. 每个接害岗位按接触的危害因素和累计工龄定体检周期；一个人同时接触多种
   危害因素时，各因素分别给档，冲突时以更严（周期更短）的那一档为准。
2. 岗位类别是强制项：岗位类别空着的档案一律不允许保存。
3. 体检结论为「复查」的，复查待办一直挂到复查结论填完才关闭。
4. 判定为「职业禁忌」的，结论落到岗位异动登记（jobtransfer 表）的待办里，
   同时把对应资质证书停用。
5. 新判定标准只影响在档人员的下一次体检安排；已经登记存档的体检结论按
   登记时的标准版本原样保留，不重算、不改写。
6. 历史纸质体检表由回填接口统一按体检日期升序落档，只存档、不补触发待办。
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "health"
JOBTRANSFER_MODULE = "jobtransfer"
CERTIFICATE_MODULE = "certificate"

# 判定标准版本：结论登记时把版本快照存进体检记录，标准换版后历史结论不重算。
STANDARD_VERSION = "2026版"

HAZARDS = ["粉尘", "噪声", "有毒有害气体"]
EXAM_TYPES = ["上岗前", "在岗期间", "离岗时"]
CONCLUSIONS = ["目前未见异常", "复查", "职业禁忌", "疑似职业病", "职业病"]
RECHECK_CONCLUSIONS = ["复查合格", "职业禁忌", "疑似职业病"]
DIAGNOSIS_CONCLUSIONS = ["确诊职业病", "排除职业病"]

# 周期档位（月）。每种危害因素按累计工龄分两档：未到阈值走 loose，到了走 strict。
# 数值越短越严，多因素冲突时取最小值。
CYCLE_RULES: dict[str, dict[str, Any]] = {
    "粉尘": {"tenure_years": 10, "loose_months": 12, "strict_months": 6},
    "噪声": {"tenure_years": 10, "loose_months": 24, "strict_months": 12},
    "有毒有害气体": {"tenure_years": 5, "loose_months": 12, "strict_months": 6},
}

REQUIRED_FIELDS = ["人员编号", "姓名", "岗位类别", "接触危害因素", "累计工龄"]
RECHECK_DAYS = 30
TRANSFER_DAYS = 30
DIAGNOSIS_DAYS = 30

STATUS_ON_DUTY = "在岗监护"
STATUS_ARCHIVED = "已归档"


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def add_months(day: date, months: int) -> date:
    """按月顺延，月底日期（如 12-31 加 2 个月）自动收敛到目标月最后一天。"""
    total = (day.year * 12 + day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def decide_cycle(hazards: list[str], tenure_years: float) -> tuple[int, str, dict[str, int]]:
    """唯一的周期判定口径。

    返回 (最终周期月数, 可读判定依据, 各危害因素分别给出的月数)。
    多因素结论冲突时以更严（月数最小）的一档为准。
    """
    months_by_hazard: dict[str, int] = {}
    for hazard in hazards:
        rule = CYCLE_RULES[hazard]
        reached = tenure_years >= rule["tenure_years"]
        months_by_hazard[hazard] = rule["strict_months"] if reached else rule["loose_months"]
    cycle = min(months_by_hazard.values())
    parts = []
    for hazard in hazards:
        rule = CYCLE_RULES[hazard]
        reached = tenure_years >= rule["tenure_years"]
        compare = "≥" if reached else "<"
        parts.append(
            f"{hazard}：累计工龄{compare}{rule['tenure_years']:g}年"
            f"→{months_by_hazard[hazard]}个月"
        )
    parts.append(f"多因素取更严一档→{cycle}个月")
    return cycle, "；".join(parts), months_by_hazard


def _normalize_hazards(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = [str(item).strip() for item in value]
    else:
        raw = [item.strip() for item in str(value or "").replace("，", ",").split(",")]
    return [item for item in raw if item]


class HealthService:
    # ---------------- 列表与明细 ----------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        hazard: str | None = None,
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
        if hazard:
            rows = [row for row in rows if hazard in list(row.get("接触危害因素", []))]
        if pending_only:
            rows = [row for row in rows if row.get("pending")]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def standard(self) -> dict[str, Any]:
        return {
            "version": STANDARD_VERSION,
            "hazards": HAZARDS,
            "rules": CYCLE_RULES,
            "note": "换版只重算在档人员的下一次体检周期，已登记存档的结论不重算。",
        }

    # ---------------- 建档 ----------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field
            for field in REQUIRED_FIELDS
            if not str(values.get(field) or "").strip()
        ]
        # 岗位类别单独再把一次：即便上面漏过，空字符串/空白也不允许落库。
        if not str(values.get("岗位类别") or "").strip():
            if "岗位类别" not in missing:
                missing.append("岗位类别")
        if missing:
            return None, missing

        hazards = _normalize_hazards(values.get("接触危害因素"))
        invalid = [item for item in hazards if item not in CYCLE_RULES]
        if invalid:
            return None, [f"接触危害因素不认识：{'、'.join(invalid)}（可选：{'、'.join(HAZARDS)}）"]
        if not hazards:
            return None, ["接触危害因素至少要选一种，否则不属于职业健康监护范围"]

        try:
            tenure = float(values["累计工龄"])
            if tenure < 0:
                raise ValueError
        except (TypeError, ValueError):
            return None, ["累计工龄需填写非负数字（单位：年）"]

        rows = store.rows(MODULE)
        sequence = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        cycle, basis, _ = decide_cycle(hazards, tenure)
        entry: dict[str, Any] = {
            "id": sequence,
            "档案编号": f"HEAL-{sequence:04d}",
            "人员编号": str(values["人员编号"]).strip(),
            "姓名": str(values["姓名"]).strip(),
            "岗位类别": str(values["岗位类别"]).strip(),
            "接触危害因素": hazards,
            "累计工龄": tenure,
            "资质证书编号": str(values.get("资质证书编号") or "").strip(),
            "体检周期": cycle,
            "周期依据": basis,
            "适用标准版本": STANDARD_VERSION,
            "最新结论": "",
            "下次体检日期": "",
            "status": STATUS_ON_DUTY,
            "pending": True,
            "abnormal": False,
            "exams": [],
            "todos": [],
        }
        # 接害岗位上岗前必须先体检，岗前结论没登记之前先挂一条上岗前体检待办。
        entry["todos"].append(
            self._make_todo("上岗前体检", None, "上岗前须完成职业健康体检，合格后方可接害上岗")
        )
        self._refresh_summary(entry)
        rows.append(entry)
        return entry, []

    # ---------------- 体检登记 ----------------
    def record_exam(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"职业健康监护档案 {entry_id} 不存在"
        if entry["status"] == STATUS_ARCHIVED:
            return None, "该档案已随离岗归档，不能再登记体检"

        exam_day = _parse_date(values.get("体检日期"))
        if exam_day is None:
            return None, "体检日期格式应为 YYYY-MM-DD"
        exam_type = str(values.get("体检类型") or "").strip()
        if exam_type not in EXAM_TYPES:
            return None, f"体检类型须为：{'、'.join(EXAM_TYPES)}"
        conclusion = str(values.get("体检结论") or "").strip()
        if conclusion not in CONCLUSIONS:
            return None, f"体检结论须为：{'、'.join(CONCLUSIONS)}"
        institution = str(values.get("体检机构") or "").strip()
        if not institution:
            return None, "体检机构不能为空"

        if any(_parse_date(exam.get("体检日期")) == exam_day for exam in entry["exams"]):
            return None, f"{exam_day:%Y-%m-%d} 已有体检记录，不能重复登记"

        exam = {
            "序号": len(entry["exams"]) + 1,
            "体检日期": f"{exam_day:%Y-%m-%d}",
            "体检类型": exam_type,
            "体检机构": institution,
            "体检结论": conclusion,
            "处理意见": str(values.get("处理意见") or "").strip(),
            "适用标准版本": STANDARD_VERSION,
            "数据来源": "电子登记",
            "复查截止日": "",
            "复查结论": "",
            "复查日期": "",
        }
        entry["exams"].append(exam)

        # 登记了新体检，旧的「到期体检」待办自然结束。
        self._close_todos(entry, kinds=("到期体检", "上岗前体检"))

        if exam_type == "离岗时":
            # 离岗体检是监护终点：所有未完成事项随档案归档一并结束，结论永久保留。
            for todo in entry["todos"]:
                if todo["状态"] == "待办":
                    todo["状态"] = "已完成"
                    todo["关闭说明"] = "离岗时体检完成，档案归档"
            entry["status"] = STATUS_ARCHIVED
        else:
            self._apply_conclusion(entry, exam, exam_day, conclusion)

        self._refresh_summary(entry)
        return entry, f"{exam_type}体检已登记，判定结论：{conclusion}"

    def _apply_conclusion(
        self, entry: dict[str, Any], exam: dict[str, Any], exam_day: date, conclusion: str
    ) -> None:
        """结论处置口径：复查挂待办；职业禁忌落异动并停用资质；异常建诊断待办。"""
        if conclusion == "目前未见异常":
            self._schedule_next(entry, exam_day, reason="本次体检未见异常")
            return

        if conclusion == "复查":
            deadline = exam_day.fromordinal(exam_day.toordinal() + RECHECK_DAYS)
            exam["复查截止日"] = f"{deadline:%Y-%m-%d}"
            entry["todos"].append(
                self._make_todo(
                    "复查",
                    deadline,
                    f"体检结论为复查，{RECHECK_DAYS}日内完成复查并填报复查结论",
                    exam_no=exam["序号"],
                )
            )
            return

        if conclusion == "职业禁忌":
            self._open_transfer(entry, exam, exam_day)
            return

        if conclusion == "疑似职业病":
            deadline = exam_day.fromordinal(exam_day.toordinal() + DIAGNOSIS_DAYS)
            entry["todos"].append(
                self._make_todo(
                    "职业病诊断",
                    deadline,
                    "体检结论为疑似职业病，需到职业病诊断机构申请诊断",
                    exam_no=exam["序号"],
                )
            )
            return

        if conclusion == "职业病":
            self._open_transfer(entry, exam, exam_day, reason="确诊职业病，调离接害岗位")

    # ---------------- 复查/诊断结论填报 ----------------
    def complete_followup(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"职业健康监护档案 {entry_id} 不存在"

        todo = self._find_open_todo(entry, values.get("待办编号"), allow_kinds=("复查", "职业病诊断"))
        if todo is None:
            return None, "没有找到处于待办状态的复查/职业病诊断事项"

        result_day = _parse_date(values.get("结论日期"))
        if result_day is None:
            return None, "结论日期格式应为 YYYY-MM-DD"
        result = str(values.get("随访结论") or "").strip()

        if todo["类型"] == "复查":
            if result not in RECHECK_CONCLUSIONS:
                return None, f"复查结论须为：{'、'.join(RECHECK_CONCLUSIONS)}"
            exam = next(item for item in entry["exams"] if item["序号"] == todo["体检序号"])
            exam["复查结论"] = result
            exam["复查日期"] = f"{result_day:%Y-%m-%d}"
            todo["状态"] = "已完成"
            todo["关闭说明"] = f"复查结论已填报：{result}"
            # 复查结论本身也是一次判定，同样按统一口径处置，且以更严结论为准。
            if result == "复查合格":
                self._schedule_next(entry, result_day, reason="复查合格，按周期安排在岗体检")
            elif result == "职业禁忌":
                self._open_transfer(entry, exam, result_day, source_exam_day=_parse_date(exam["体检日期"]))
            elif result == "疑似职业病":
                entry["todos"].append(
                    self._make_todo(
                        "职业病诊断",
                        result_day.fromordinal(result_day.toordinal() + DIAGNOSIS_DAYS),
                        "复查仍提示疑似职业病，需申请职业病诊断",
                        exam_no=exam["序号"],
                    )
                )
            self._refresh_summary(entry)
            return entry, f"复查结论「{result}」已填报，复查待办已关闭"

        # 职业病诊断待办
        if result not in DIAGNOSIS_CONCLUSIONS:
            return None, f"诊断结论须为：{'、'.join(DIAGNOSIS_CONCLUSIONS)}"
        todo["状态"] = "已完成"
        todo["关闭说明"] = f"职业病诊断结论：{result}"
        if result == "确诊职业病":
            exam = next(item for item in entry["exams"] if item["序号"] == todo["体检序号"])
            self._open_transfer(entry, exam, result_day, reason="确诊职业病，调离接害岗位")
        else:
            self._schedule_next(entry, result_day, reason="排除职业病，恢复按周期在岗体检")
        self._refresh_summary(entry)
        return entry, f"诊断结论「{result}」已登记，诊断待办已关闭"

    # ---------------- 岗位异动 / 资质停用 ----------------
    def _open_transfer(
        self,
        entry: dict[str, Any],
        exam: dict[str, Any],
        exam_day: date,
        *,
        reason: str = "体检判定职业禁忌，不得继续从事原接害岗位",
        source_exam_day: date | None = None,
    ) -> dict[str, Any]:
        """判定结果落到岗位异动登记的待办里，并停用对应资质。"""
        deadline = exam_day.fromordinal(exam_day.toordinal() + TRANSFER_DAYS)
        transfers = store.rows(JOBTRANSFER_MODULE)

        # 同一份体检结论不重复开异动单。
        existed = next(
            (
                row
                for row in transfers
                if row.get("档案id") == entry["id"]
                and row.get("体检序号") == exam["序号"]
                and row.get("状态") != "已撤销"
            ),
            None,
        )
        if existed is None:
            transfer = {
                "id": max((int(row.get("id", 0)) for row in transfers), default=0) + 1,
                "异动编号": f"JOBT-{len(transfers) + 1:04d}",
                "人员编号": entry["人员编号"],
                "姓名": entry["姓名"],
                "原岗位类别": entry["岗位类别"],
                "新岗位类别": "",
                "异动原因": reason,
                "体检日期": f"{(source_exam_day or exam_day):%Y-%m-%d}",
                "申请日期": f"{exam_day:%Y-%m-%d}",
                "完成日期": "",
                "档案id": entry["id"],
                "体检序号": exam["序号"],
                "待办编号": "",
                "关联证书编号": entry.get("资质证书编号", ""),
                "证书处置": "",
                "status": "待调岗",
                "pending": True,
                "abnormal": True,
            }
            transfers.append(transfer)
        else:
            transfer = existed

        cert_no = entry.get("资质证书编号", "")
        cert_msg = "档案未登记资质证书编号，未联动停用"
        if cert_no:
            certificate = next(
                (row for row in store.rows(CERTIFICATE_MODULE) if row.get("证书编号") == cert_no),
                None,
            )
            if certificate is None:
                cert_msg = f"未找到证书编号 {cert_no}，请人工核对"
            else:
                certificate["status"] = "已停用"
                certificate["证书状态"] = "职业禁忌停用"
                certificate["pending"] = False
                certificate["abnormal"] = True
                cert_msg = f"资质 {cert_no} 已停用"
        transfer["证书处置"] = cert_msg

        # 同一判定不重复给档案挂异动待办。
        open_transfer = next(
            (
                todo
                for todo in entry["todos"]
                if todo["状态"] == "待办"
                and todo["类型"] == "岗位异动"
                and todo["体检序号"] == exam["序号"]
            ),
            None,
        )
        if open_transfer is None:
            todo = self._make_todo(
                "岗位异动",
                deadline,
                f"{reason}；{cert_msg}",
                exam_no=exam["序号"],
            )
            entry["todos"].append(todo)
            transfer["待办编号"] = todo["编号"]
        else:
            open_transfer["说明"] = f"{reason}；{cert_msg}"
            transfer["待办编号"] = open_transfer["编号"]
        return transfer

    def close_transfer_todo(self, archive_id: int, todo_no: str, finish_note: str) -> bool:
        """岗位异动登记完成后，由岗位异动服务回调关闭健康档案侧待办。"""
        entry = store.find(MODULE, archive_id)
        if entry is None:
            return False
        todo = next((item for item in entry["todos"] if item["编号"] == todo_no), None)
        if todo is None:
            return False
        todo["状态"] = "已完成"
        todo["关闭说明"] = finish_note
        self._refresh_summary(entry)
        return True

    # ---------------- 纸质体检表回填 ----------------
    def backfill_paper(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """历史纸质体检表按体检日期顺序回填。

        只追加存档，不按当前口径补触发任何待办、不停用资质；
        适用标准版本标记为「历史归档」，换版不重算。
        """
        parsed: list[tuple[date, dict[str, Any]]] = []
        errors: list[str] = []
        for index, raw in enumerate(records, start=1):
            person_no = str(raw.get("人员编号") or "").strip()
            exam_day = _parse_date(raw.get("体检日期"))
            exam_type = str(raw.get("体检类型") or "在岗期间").strip() or "在岗期间"
            conclusion = str(raw.get("体检结论") or "").strip()
            institution = str(raw.get("体检机构") or "").strip()
            label = f"第{index}行（{person_no or '人员编号为空'}，{raw.get('体检日期') or '日期为空'}）"
            if not person_no:
                errors.append(f"{label}：人员编号为空")
                continue
            if exam_day is None:
                errors.append(f"{label}：体检日期无效")
                continue
            if exam_type not in EXAM_TYPES:
                errors.append(f"{label}：体检类型无效")
                continue
            if conclusion not in CONCLUSIONS:
                errors.append(f"{label}：体检结论无效")
                continue
            if not institution:
                errors.append(f"{label}：体检机构为空")
                continue
            entry = next(
                (row for row in store.rows(MODULE) if row.get("人员编号") == person_no),
                None,
            )
            if entry is None:
                errors.append(f"{label}：监护档案不存在，请先建档")
                continue
            # 岗位类别是档案的强制项，没有岗位类别的档案不允许承接回填记录。
            if not str(entry.get("岗位类别") or "").strip():
                errors.append(f"{label}：档案岗位类别为空，按规定不允许保存/回填")
                continue
            if any(_parse_date(exam.get("体检日期")) == exam_day for exam in entry["exams"]):
                errors.append(f"{label}：该日期体检已存在，跳过避免重复")
                continue
            parsed.append((exam_day, {
                "entry": entry,
                "raw": raw,
                "exam_day": exam_day,
                "exam_type": exam_type,
                "conclusion": conclusion,
                "institution": institution,
                "label": label,
            }))

        # 全部记录跨人员统一按体检日期升序，再按人员顺序落档，保证历史时序唯一。
        parsed.sort(key=lambda item: (item[0], item[1]["entry"]["id"]))
        backfilled: list[dict[str, Any]] = []
        for _, payload in parsed:
            entry = payload["entry"]
            paper_count = sum(1 for exam in entry["exams"] if exam.get("数据来源") == "纸质回填")
            exam = {
                "序号": len(entry["exams"]) + 1,
                "体检日期": f"{payload['exam_day']:%Y-%m-%d}",
                "体检类型": payload["exam_type"],
                "体检机构": payload["institution"],
                "体检结论": payload["conclusion"],
                "处理意见": str(payload["raw"].get("处理意见") or "").strip(),
                "适用标准版本": f"历史归档（{STANDARD_VERSION}口径不重算）",
                "数据来源": "纸质回填",
                "回填批次序号": paper_count + 1,
                "复查截止日": "",
                "复查结论": "",
                "复查日期": "",
            }
            entry["exams"].append(exam)
            # 历史结论只更新「最新结论」展示，不改变待办与资质状态。
            entry["最新结论"] = f"{exam['体检结论']}（纸质回填）"
            backfilled.append({
                "档案编号": entry["档案编号"],
                "姓名": entry["姓名"],
                "体检日期": exam["体检日期"],
                "回填批次序号": exam["回填批次序号"],
                "体检结论": exam["体检结论"],
            })
        return backfilled, errors

    # ---------------- 标准换版：只重排周期，不重算结论 ----------------
    def refresh_cycles(self) -> dict[str, Any]:
        """按当前判定口径刷新在档人员周期。

        - 在档（未离岗归档）人员：重算周期依据；若有未完成的「到期体检」待办，
          以最近一次合格体检日为基准重排截止日。
        - 已归档档案：完全不动。
        - 任何体检/复查结论、复查与异动待办：一律不重算、不改写。
        """
        refreshed: list[dict[str, Any]] = []
        skipped_archived: list[str] = []
        for entry in store.rows(MODULE):
            if entry["status"] == STATUS_ARCHIVED:
                skipped_archived.append(entry["档案编号"])
                continue
            cycle, basis, _ = decide_cycle(
                list(entry["接触危害因素"]), float(entry["累计工龄"])
            )
            entry["体检周期"] = cycle
            entry["周期依据"] = basis
            entry["适用标准版本"] = STANDARD_VERSION

            open_due = next(
                (todo for todo in entry["todos"] if todo["状态"] == "待办" and todo["类型"] == "到期体检"),
                None,
            )
            if open_due is not None:
                base = None
                for exam in reversed(entry["exams"]):
                    if exam["体检结论"] == "目前未见异常" or exam.get("复查结论") == "复查合格":
                        base = _parse_date(exam.get("复查日期") or exam["体检日期"])
                        break
                if base is not None:
                    new_deadline = add_months(base, cycle)
                    open_due["截止日期"] = f"{new_deadline:%Y-%m-%d}"
                    open_due["说明"] = f"按{STANDARD_VERSION}口径重排，基准日 {base:%Y-%m-%d}"
                    entry["下次体检日期"] = open_due["截止日期"]
            refreshed.append({"档案编号": entry["档案编号"], "姓名": entry["姓名"], "体检周期": cycle})
        return {
            "standard_version": STANDARD_VERSION,
            "refreshed": refreshed,
            "skipped_archived": skipped_archived,
            "note": "已登记存档的体检结论未做任何重算",
        }

    # ---------------- 内部工具 ----------------
    def _make_todo(
        self,
        kind: str,
        deadline: date | None,
        note: str,
        *,
        exam_no: int | None = None,
    ) -> dict[str, Any]:
        todos_all = [todo for row in store.rows(MODULE) for todo in row.get("todos", [])]
        number = max((int(todo.get("编号", "TD-0000")[3:]) for todo in todos_all), default=0) + 1
        return {
            "编号": f"TD-{number:04d}",
            "类型": kind,
            "截止日期": f"{deadline:%Y-%m-%d}" if deadline else "",
            "状态": "待办",
            "说明": note,
            "体检序号": exam_no,
            "关闭说明": "",
        }

    def _schedule_next(self, entry: dict[str, Any], base_day: date, *, reason: str) -> None:
        cycle, basis, _ = decide_cycle(list(entry["接触危害因素"]), float(entry["累计工龄"]))
        entry["体检周期"] = cycle
        entry["周期依据"] = basis
        deadline = add_months(base_day, cycle)
        entry["todos"].append(
            self._make_todo("到期体检", deadline, f"{reason}，每{cycle}个月体检一次")
        )

    def _close_todos(self, entry: dict[str, Any], *, kinds: tuple[str, ...]) -> None:
        for todo in entry["todos"]:
            if todo["状态"] == "待办" and todo["类型"] in kinds:
                todo["状态"] = "已完成"
                todo["关闭说明"] = "已登记新的体检记录"

    def _find_open_todo(
        self, entry: dict[str, Any], todo_no: Any, *, allow_kinds: tuple[str, ...]
    ) -> dict[str, Any] | None:
        todo_no = str(todo_no or "").strip()
        for todo in entry["todos"]:
            if todo["状态"] == "待办" and todo["类型"] in allow_kinds and todo["编号"] == todo_no:
                return todo
        return None

    def _refresh_summary(self, entry: dict[str, Any]) -> None:
        """根据体检与待办重算档案顶层的展示/统计字段。"""
        open_todos = [todo for todo in entry["todos"] if todo["状态"] == "待办"]
        entry["pending"] = bool(open_todos) and entry["status"] != STATUS_ARCHIVED
        latest = entry["exams"][-1] if entry["exams"] else None
        entry["最新结论"] = (
            f"{latest['体检结论']}"
            + ("（纸质回填）" if latest and latest.get("数据来源") == "纸质回填" else "")
            if latest
            else ""
        )
        due = next(
            (todo["截止日期"] for todo in open_todos if todo["类型"] in ("到期体检", "上岗前体检")),
            "",
        )
        entry["下次体检日期"] = due
        # 异常量只统计尚未闭环的复查/异动/诊断；异动办完、复查填完即解除。
        entry["abnormal"] = bool(
            open_todos
            and any(todo["类型"] in ("复查", "岗位异动", "职业病诊断") for todo in open_todos)
        )
