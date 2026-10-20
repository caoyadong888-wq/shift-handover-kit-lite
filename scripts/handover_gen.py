#!/usr/bin/env python3
"""Build a markdown shift handover from a JSON shift input and a ticket CSV.

Alarm merge, HTML, JSON, and carry-over are full-pack only. Exit 0 when the
report is green, 2 when amber, 3 when red, and 1 when the input is invalid.
A red or amber report is still written.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "templates" / "handover_template.md"
GENERATOR = "shift-handover-kit-lite"

REQUIRED_SHIFT = (
    "site",
    "shift",
    "date",
    "outgoing_lead",
    "incoming_lead",
    "window_start",
    "window_end",
)
SHIFT_FIELDS = set(REQUIRED_SHIFT) | {
    "summary_note",
    "incidents",
    "changes",
    "hardware_actions",
    "tasks",
    "risks",
    "checklist",
}
INCIDENT_FIELDS = {"id", "title", "severity", "status", "opened", "closed", "owner_role", "summary"}
CHANGE_FIELDS = {"id", "title", "status", "owner_role", "summary", "started", "finished"}
HARDWARE_FIELDS = {"id", "kind", "asset", "status", "owner_role", "summary"}
TASK_FIELDS = {"id", "title", "owner_role", "due", "status"}
RISK_FIELDS = {"id", "item", "level", "note"}
CHECKLIST_KEYS = (
    "walkdown",
    "alarms_acked",
    "tickets_reviewed",
    "change_freeze",
    "spares",
    "access_log",
)
TICKET_COLUMNS = (
    "ticket_id",
    "opened",
    "closed",
    "priority",
    "status",
    "category",
    "summary",
    "owner_role",
)

PRIORITIES = ("P1", "P2", "P3", "P4")
INCIDENT_STATUSES = ("open", "closed")
TASK_STATUSES = ("open", "done")
CHANGE_STATUSES = ("completed", "rolled_back", "aborted", "in_progress")
HARDWARE_KINDS = ("rma", "part_swap", "cabling")
HARDWARE_STATUSES = ("done", "pending")
RISK_LEVELS = ("watch", "elevated")

# Exclusive bounds: a P1 open for exactly 4h is not a breach. Same for P2 at 8h.
SLA_LIMIT = {"P1": timedelta(hours=4), "P2": timedelta(hours=8)}

TIME_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)
DATE_FORMAT = "%Y-%m-%d"

LABELS = {
    "field": ("Field", "字段"),
    "value": ("Value", "值"),
    "site": ("Site", "站点"),
    "shift": ("Shift", "班次"),
    "date": ("Date", "日期"),
    "outgoing": ("Outgoing lead", "交班角色"),
    "incoming": ("Incoming lead", "接班角色"),
    "window_start": ("Window start", "窗口开始"),
    "window_end": ("Window end", "窗口结束"),
    "status": ("Status", "状态"),
    "reasons": ("Reasons", "原因"),
    "none": ("None this shift.", "本班次无。"),
    "none_short": ("None.", "无。"),
    "yes": ("yes", "是"),
    "no": ("no", "否"),
    "id": ("ID", "编号"),
    "title_col": ("Title", "标题"),
    "severity": ("Severity", "级别"),
    "owner": ("Owner", "负责角色"),
    "opened": ("Opened", "打开时间"),
    "summary": ("Summary", "摘要"),
    "kind": ("Kind", "类型"),
    "asset": ("Asset", "资产"),
    "item": ("Item", "事项"),
    "level": ("Level", "等级"),
    "note": ("Note", "说明"),
    "due": ("Due", "截止"),
    "overdue": ("Overdue", "逾期"),
    "priority": ("Priority", "优先级"),
    "category": ("Category", "类别"),
    "confirmed": ("Recorded", "记录"),
    "kpi": ("KPI", "指标"),
    "open_incidents_sub": ("Open", "未关闭"),
    "closed_incidents_sub": ("Closed this shift", "本班次已关闭"),
    "tickets_sub": ("Tickets", "工单"),
    "check_walkdown": ("Walkdown", "现场巡视"),
    "check_alarms_acked": ("Alarms acknowledged", "告警已确认"),
    "check_tickets_reviewed": ("Open tickets reviewed", "未关闭工单已复核"),
    "check_change_freeze": ("Change freeze", "变更冻结"),
    "check_spares": ("Spares checked", "备件已核对"),
    "check_access_log": ("Access log reviewed", "进出记录已复核"),
    "kpi_opened": ("Tickets opened", "本班打开工单"),
    "kpi_closed": ("Tickets closed", "本班关闭工单"),
    "kpi_open": ("Tickets still open", "仍未关闭工单"),
    "kpi_sla": ("SLA breaches", "超出时限"),
    "kpi_mttr": ("MTTR minutes", "平均修复分钟"),
    "opened_during": ("Opened during shift", "班次内打开"),
    "closed_during": ("Closed during shift", "班次内关闭"),
    "sign_prose": (
        "The outgoing role confirms this report matches the shift. The incoming role accepts the open incidents and tasks above.",
        "交班角色确认本报告与本班事实一致。接班角色接收上面的未关闭事件和任务。",
    ),
    "report_time": ("Report time", "报告时间"),
}

REASON_TEXT = {
    "open_p1": ("Open P1", "存在未关闭的 P1"),
    "open_p2": ("Open P2", "存在未关闭的 P2"),
    "sla_breach": ("SLA breach", "超出时限"),
    "overdue_task": ("Overdue task", "任务逾期"),
}
STATUS_WORD = {
    "green": ("GREEN", "正常"),
    "amber": ("AMBER", "注意"),
    "red": ("RED", "异常"),
}
KIND_WORD = {
    "rma": ("RMA", "返修"),
    "part_swap": ("Part swap", "部件更换"),
    "cabling": ("Cabling", "布线"),
}
CHECK_LABEL_KEYS = {
    "walkdown": "check_walkdown",
    "alarms_acked": "check_alarms_acked",
    "tickets_reviewed": "check_tickets_reviewed",
    "change_freeze": "check_change_freeze",
    "spares": "check_spares",
    "access_log": "check_access_log",
}
REASON_ORDER = ("open_p1", "open_p2", "sla_breach", "overdue_task")
RED_REASONS = {"open_p1"}
AMBER_REASONS = {"open_p2", "sla_breach", "overdue_task"}

_LANG_BLOCK = re.compile(r"\{\{#(en|zh|both)\}\}(.*?)\{\{/\1\}\}", re.DOTALL)
_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_]+)\}\}")
FULL_PACK_ERROR = "error: alarm merge, HTML, JSON, and carry-over are full-pack only"


class HandoverError(Exception):
    """Invalid shift input. The CLI prints it and exits 1."""


def L(lang: str, en: str, zh: str) -> str:
    if lang == "en":
        return en
    if lang == "zh":
        return zh
    return f"{en} / {zh}"


def lab(lang: str, key: str) -> str:
    en, zh = LABELS[key]
    return L(lang, en, zh)


def status_code(status: str) -> int:
    return {"green": 0, "amber": 2, "red": 3}[status]


def _parse_stamp(value: str, *, path: str, allow_date: bool) -> tuple[datetime, bool]:
    text = (value or "").strip()
    if text.endswith("Z") and text.count("Z") == 1:
        text = text[:-1]
    if not text:
        raise HandoverError(f"{path} is empty")
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt), False
        except ValueError:
            continue
    if allow_date:
        try:
            return datetime.strptime(text, DATE_FORMAT), True
        except ValueError:
            pass
    raise HandoverError(f"{path} cannot parse time value {value!r}")


def _require_object(data, path: str) -> dict:
    if not isinstance(data, dict):
        raise HandoverError(f"{path} must be an object")
    return data


def _reject_unknown(data: dict, allowed: set[str], path: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise HandoverError(f"{path} unknown field {extra[0]!r}")


def _require_str(data: dict, field: str, path: str) -> str:
    if field not in data:
        raise HandoverError(f"{path} missing required field {field!r}")
    value = data[field]
    if not isinstance(value, str):
        raise HandoverError(f"{path} {field!r} must be a string")
    text = value.strip()
    if not text:
        raise HandoverError(f"{path} {field!r} is empty")
    return text


def _optional_str(data: dict, field: str, path: str) -> str:
    if field not in data or data[field] is None:
        return ""
    value = data[field]
    if not isinstance(value, str):
        raise HandoverError(f"{path} {field!r} must be a string")
    return value.strip()


def _enum(value: str, allowed: tuple[str, ...], path: str, field: str) -> str:
    token = value.strip()
    folded = token.lower().replace(" ", "_")
    allowed_l = {item.lower(): item for item in allowed}
    if folded in allowed_l:
        return allowed_l[folded]
    if token.upper() in allowed:
        return token.upper()
    raise HandoverError(f"{path} unknown {field} {value!r}")


def _priority(value: str, path: str) -> str:
    token = value.strip().upper()
    if token not in PRIORITIES:
        raise HandoverError(f"{path} unknown priority {value!r}")
    return token


def _severity_p(value: str, path: str) -> str:
    token = value.strip().upper()
    if token not in PRIORITIES:
        raise HandoverError(f"{path} unknown severity {value!r}")
    return token


def _list_of(data: dict, field: str, path: str) -> list:
    if field not in data or data[field] is None:
        return []
    value = data[field]
    if not isinstance(value, list):
        raise HandoverError(f"{path} {field!r} must be a list")
    return value


def _unique(ids: list[str], path: str) -> None:
    seen = set()
    for item_id in ids:
        if item_id in seen:
            raise HandoverError(f"{path} duplicate id {item_id!r}")
        seen.add(item_id)


def _unique_key(values: list[str], kind: str, field: str) -> None:
    seen = set()
    for value in values:
        if value in seen:
            raise HandoverError(f"{kind}: duplicate {field} {value!r}")
        seen.add(value)


def normalize_shift(raw) -> dict:
    path = "input"
    data = _require_object(raw, f"{path}: top level")
    _reject_unknown(data, SHIFT_FIELDS, f"{path}:")
    for field in REQUIRED_SHIFT:
        if field not in data:
            raise HandoverError(f"{path}: missing required field {field!r}")
    date_text = _require_str(data, "date", f"{path}:")
    try:
        datetime.strptime(date_text, DATE_FORMAT)
    except ValueError as exc:
        raise HandoverError(f"{path}: cannot parse 'date' value {date_text!r}") from exc
    start_text = _require_str(data, "window_start", f"{path}:")
    end_text = _require_str(data, "window_end", f"{path}:")
    start, start_date_only = _parse_stamp(start_text, path=f"{path}: 'window_start'", allow_date=False)
    end, end_date_only = _parse_stamp(end_text, path=f"{path}: 'window_end'", allow_date=False)
    if start_date_only or end_date_only:
        raise HandoverError(f"{path}: window_start and window_end must include a time")
    if end <= start:
        raise HandoverError(f"{path}: 'window_end' must be after 'window_start'")
    return {
        "site": _require_str(data, "site", f"{path}:"),
        "shift": _require_str(data, "shift", f"{path}:"),
        "date": date_text,
        "outgoing_lead": _require_str(data, "outgoing_lead", f"{path}:"),
        "incoming_lead": _require_str(data, "incoming_lead", f"{path}:"),
        "window_start": start_text.strip(),
        "window_end": end_text.strip(),
        "_window_start": start,
        "_window_end": end,
        "summary_note": _optional_str(data, "summary_note", f"{path}:"),
        "checklist": _normalize_checklist(data.get("checklist"), f"{path}: checklist"),
        "incidents": _normalize_incidents(_list_of(data, "incidents", f"{path}:"), f"{path}: incidents"),
        "changes": _normalize_changes(_list_of(data, "changes", f"{path}:"), f"{path}: changes"),
        "hardware_actions": _normalize_hardware(
            _list_of(data, "hardware_actions", f"{path}:"), f"{path}: hardware_actions"
        ),
        "tasks": _normalize_tasks(_list_of(data, "tasks", f"{path}:"), f"{path}: tasks"),
        "risks": _normalize_risks(_list_of(data, "risks", f"{path}:"), f"{path}: risks"),
    }


def _normalize_checklist(raw, path: str) -> dict[str, bool]:
    result = {key: False for key in CHECKLIST_KEYS}
    if raw is None:
        return result
    data = _require_object(raw, path)
    _reject_unknown(data, set(CHECKLIST_KEYS), f"{path}:")
    for key, value in data.items():
        if not isinstance(value, bool):
            raise HandoverError(f"{path}: {key!r} must be a boolean")
        result[key] = value
    return result


def _normalize_incidents(rows: list, path: str) -> list[dict]:
    out = []
    for index, raw in enumerate(rows):
        item_path = f"{path}[{index}]"
        data = _require_object(raw, item_path)
        _reject_unknown(data, INCIDENT_FIELDS, f"{item_path}:")
        status = _enum(_require_str(data, "status", item_path), INCIDENT_STATUSES, item_path, "status")
        closed = _optional_str(data, "closed", item_path)
        if status == "closed" and not closed:
            raise HandoverError(f"{item_path}: status is closed but 'closed' is empty")
        if status == "open" and closed:
            raise HandoverError(f"{item_path}: status is open but 'closed' is set")
        opened = _require_str(data, "opened", item_path)
        opened_dt, _ = _parse_stamp(opened, path=f"{item_path}: 'opened'", allow_date=True)
        if closed:
            closed_dt, _ = _parse_stamp(closed, path=f"{item_path}: 'closed'", allow_date=True)
            if closed_dt < opened_dt:
                raise HandoverError(f"{item_path}: 'closed' is before 'opened'")
        out.append(
            {
                "id": _require_str(data, "id", item_path),
                "title": _require_str(data, "title", item_path),
                "severity": _severity_p(_require_str(data, "severity", item_path), item_path),
                "status": status,
                "opened": opened.strip(),
                "closed": closed,
                "owner_role": _require_str(data, "owner_role", item_path),
                "summary": _optional_str(data, "summary", item_path),
            }
        )
    _unique([item["id"] for item in out], path)
    return out


def _normalize_changes(rows: list, path: str) -> list[dict]:
    out = []
    for index, raw in enumerate(rows):
        item_path = f"{path}[{index}]"
        data = _require_object(raw, item_path)
        _reject_unknown(data, CHANGE_FIELDS, f"{item_path}:")
        started = _optional_str(data, "started", item_path)
        finished = _optional_str(data, "finished", item_path)
        if started:
            _parse_stamp(started, path=f"{item_path}: 'started'", allow_date=False)
        if finished:
            _parse_stamp(finished, path=f"{item_path}: 'finished'", allow_date=False)
        out.append(
            {
                "id": _require_str(data, "id", item_path),
                "title": _require_str(data, "title", item_path),
                "status": _enum(
                    _require_str(data, "status", item_path), CHANGE_STATUSES, item_path, "status"
                ),
                "owner_role": _require_str(data, "owner_role", item_path),
                "summary": _optional_str(data, "summary", item_path),
                "started": started,
                "finished": finished,
            }
        )
    _unique([item["id"] for item in out], path)
    return out


def _normalize_hardware(rows: list, path: str) -> list[dict]:
    out = []
    for index, raw in enumerate(rows):
        item_path = f"{path}[{index}]"
        data = _require_object(raw, item_path)
        _reject_unknown(data, HARDWARE_FIELDS, f"{item_path}:")
        out.append(
            {
                "id": _require_str(data, "id", item_path),
                "kind": _enum(_require_str(data, "kind", item_path), HARDWARE_KINDS, item_path, "kind"),
                "asset": _require_str(data, "asset", item_path),
                "status": _enum(
                    _require_str(data, "status", item_path), HARDWARE_STATUSES, item_path, "status"
                ),
                "owner_role": _require_str(data, "owner_role", item_path),
                "summary": _optional_str(data, "summary", item_path),
            }
        )
    _unique([item["id"] for item in out], path)
    return out


def _normalize_tasks(rows: list, path: str) -> list[dict]:
    out = []
    for index, raw in enumerate(rows):
        item_path = f"{path}[{index}]"
        data = _require_object(raw, item_path)
        _reject_unknown(data, TASK_FIELDS, f"{item_path}:")
        due = _require_str(data, "due", item_path)
        due_dt, date_only = _parse_stamp(due, path=f"{item_path}: 'due'", allow_date=True)
        out.append(
            {
                "id": _require_str(data, "id", item_path),
                "title": _require_str(data, "title", item_path),
                "owner_role": _require_str(data, "owner_role", item_path),
                "due": due.strip(),
                "status": _enum(
                    _require_str(data, "status", item_path), TASK_STATUSES, item_path, "status"
                ),
                "_due": due_dt,
                "_due_date_only": date_only,
            }
        )
    _unique([item["id"] for item in out], path)
    return out


def _normalize_risks(rows: list, path: str) -> list[dict]:
    out = []
    for index, raw in enumerate(rows):
        item_path = f"{path}[{index}]"
        data = _require_object(raw, item_path)
        _reject_unknown(data, RISK_FIELDS, f"{item_path}:")
        level = _optional_str(data, "level", item_path) or "watch"
        out.append(
            {
                "id": _require_str(data, "id", item_path),
                "item": _require_str(data, "item", item_path),
                "level": _enum(level, RISK_LEVELS, item_path, "level"),
                "note": _optional_str(data, "note", item_path),
            }
        )
    _unique([item["id"] for item in out], path)
    return out


def _header_map(fieldnames) -> dict[str, str]:
    mapping = {}
    for name in fieldnames or []:
        if name is None:
            continue
        mapping[name.strip().lower().replace("-", "_").replace(" ", "_")] = name
    return mapping


def load_csv(path: Path, required: tuple[str, ...], kind: str) -> list[dict]:
    if not path.is_file():
        raise HandoverError(f"{kind}: file not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise HandoverError(f"{kind}: missing header row")
        headers = _header_map(reader.fieldnames)
        for column in required:
            if column not in headers:
                raise HandoverError(f"{kind}: missing column {column!r}")
        rows = []
        for line_no, raw in enumerate(reader, start=2):
            item = {}
            for column in required:
                value = raw.get(headers[column])
                item[column] = "" if value is None else str(value).strip()
            if not any(item.values()):
                continue
            item["_line"] = line_no
            rows.append(item)
        return rows


def _row_label(row: dict, index: int) -> str:
    if "_line" in row:
        return f"line {row['_line']}"
    return f"row {index + 1}"


def _minutes(delta: timedelta) -> float:
    return float(f"{delta.total_seconds() / 60.0:.1f}")


def normalize_tickets(rows: list, window_start: datetime, window_end: datetime) -> list[dict]:
    out = []
    for index, raw in enumerate(rows or []):
        data = _require_object(raw, f"tickets: row {index + 1}")
        label = f"tickets: {_row_label(data, index)}"
        ticket_id = (data.get("ticket_id") or "").strip()
        if not ticket_id:
            raise HandoverError(f"{label}: 'ticket_id' is empty")
        opened = (data.get("opened") or "").strip()
        closed = (data.get("closed") or "").strip()
        if not opened:
            raise HandoverError(f"{label}: 'opened' is empty")
        opened_dt, _ = _parse_stamp(opened, path=f"{label}: 'opened'", allow_date=True)
        status = _enum((data.get("status") or "").strip() or " ", ("open", "closed"), label, "status")
        if status == "closed" and not closed:
            raise HandoverError(f"{label}: status is closed but 'closed' is empty")
        if status == "open" and closed:
            raise HandoverError(f"{label}: status is open but 'closed' is set")
        closed_dt = None
        if closed:
            closed_dt, _ = _parse_stamp(closed, path=f"{label}: 'closed'", allow_date=True)
            if closed_dt < opened_dt:
                raise HandoverError(f"{label}: 'closed' is before 'opened'")
        priority = _priority((data.get("priority") or ""), label)
        end = window_end if status == "open" else closed_dt
        duration = end - opened_dt
        limit = SLA_LIMIT.get(priority)
        breach = bool(status == "open" and limit is not None and duration > limit)
        out.append(
            {
                "ticket_id": ticket_id,
                "opened": opened,
                "closed": closed,
                "priority": priority,
                "status": status,
                "category": (data.get("category") or "").strip(),
                "summary": (data.get("summary") or "").strip(),
                "owner_role": (data.get("owner_role") or "").strip(),
                "opened_during_shift": window_start <= opened_dt <= window_end,
                "closed_during_shift": bool(
                    status == "closed" and closed_dt is not None and window_start <= closed_dt <= window_end
                ),
                "sla_breach": breach,
                "elapsed_minutes": _minutes(duration),
            }
        )
    _unique_key([item["ticket_id"] for item in out], "tickets", "ticket_id")
    return out


def _task_overdue(task: dict, window_end: datetime) -> bool:
    if task["status"] != "open":
        return False
    if task["_due"] is None:
        return False
    if task["_due_date_only"]:
        return task["_due"].date() < window_end.date()
    return task["_due"] < window_end


def _public_task(task: dict, window_end: datetime) -> dict:
    return {
        "id": task["id"],
        "title": task["title"],
        "owner_role": task["owner_role"],
        "due": task["due"],
        "status": task["status"],
        "overdue": _task_overdue(task, window_end),
    }


def build_report(shift, tickets=None) -> dict:
    normal = normalize_shift(shift)
    window_start = normal.pop("_window_start")
    window_end = normal.pop("_window_end")
    ticket_rows = normalize_tickets(tickets or [], window_start, window_end)
    public_tasks = [_public_task(task, window_end) for task in normal["tasks"]]
    incidents = normal["incidents"]

    open_p1 = [item["id"] for item in incidents if item["status"] == "open" and item["severity"] == "P1"]
    open_p1 += [
        item["ticket_id"] for item in ticket_rows if item["status"] == "open" and item["priority"] == "P1"
    ]
    open_p2 = [item["id"] for item in incidents if item["status"] == "open" and item["severity"] == "P2"]
    open_p2 += [
        item["ticket_id"] for item in ticket_rows if item["status"] == "open" and item["priority"] == "P2"
    ]
    sla_ids = [item["ticket_id"] for item in ticket_rows if item["sla_breach"]]
    overdue_ids = [item["id"] for item in public_tasks if item["overdue"]]
    detail = {
        "open_p1": open_p1,
        "open_p2": open_p2,
        "sla_breach": sla_ids,
        "overdue_task": overdue_ids,
    }
    reasons = [key for key in REASON_ORDER if detail[key]]
    if any(key in RED_REASONS for key in reasons):
        status = "red"
    elif any(key in AMBER_REASONS for key in reasons):
        status = "amber"
    else:
        status = "green"

    closed_for_mttr = [item for item in ticket_rows if item["closed_during_shift"]]
    if closed_for_mttr:
        mttr = float(
            f"{(sum(item['elapsed_minutes'] for item in closed_for_mttr) / len(closed_for_mttr)):.1f}"
        )
    else:
        mttr = None

    return {
        "generator": GENERATOR,
        "site": normal["site"],
        "shift": normal["shift"],
        "date": normal["date"],
        "outgoing_lead": normal["outgoing_lead"],
        "incoming_lead": normal["incoming_lead"],
        "window_start": normal["window_start"],
        "window_end": normal["window_end"],
        "summary_note": normal["summary_note"],
        "status": status,
        "status_reasons": reasons,
        "status_detail": detail,
        "checklist": normal["checklist"],
        "incidents": incidents,
        "changes": normal["changes"],
        "hardware_actions": normal["hardware_actions"],
        "tasks": public_tasks,
        "risks": normal["risks"],
        "tickets": {
            "rows": ticket_rows,
            "opened_during_shift": [item["ticket_id"] for item in ticket_rows if item["opened_during_shift"]],
            "closed_during_shift": [item["ticket_id"] for item in ticket_rows if item["closed_during_shift"]],
            "open": [item["ticket_id"] for item in ticket_rows if item["status"] == "open"],
            "sla_breaches": sla_ids,
        },
        "kpis": {
            "tickets_opened": len([item for item in ticket_rows if item["opened_during_shift"]]),
            "tickets_closed": len(closed_for_mttr),
            "tickets_still_open": len([item for item in ticket_rows if item["status"] == "open"]),
            "sla_breaches": len(sla_ids),
            "mttr_minutes": mttr,
            "incidents_open": len([item for item in incidents if item["status"] == "open"]),
            "incidents_closed": len([item for item in incidents if item["status"] == "closed"]),
            "tasks_open": len([item for item in public_tasks if item["status"] == "open"]),
            "tasks_overdue": len(overdue_ids),
        },
        "sign_off": {
            "outgoing_lead": normal["outgoing_lead"],
            "incoming_lead": normal["incoming_lead"],
            "report_time": normal["window_end"],
        },
    }


def _cell(value) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "/").replace("\n", " ").strip()


def _md_table(headers: list[str], rows: list[list]) -> str:
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(col) for col in row) + " |" for row in rows]
    return "\n".join([head, rule, *body])


def _yn(lang: str, flag: bool) -> str:
    return lab(lang, "yes") if flag else lab(lang, "no")


def _reason_line(lang: str, report: dict, key: str) -> str:
    ids = ", ".join(report["status_detail"][key])
    return f"{L(lang, *REASON_TEXT[key])}: {ids}"


def _shift_table(report: dict, lang: str) -> str:
    rows = [
        [lab(lang, "site"), report["site"]],
        [lab(lang, "shift"), report["shift"]],
        [lab(lang, "date"), report["date"]],
        [lab(lang, "outgoing"), report["outgoing_lead"]],
        [lab(lang, "incoming"), report["incoming_lead"]],
        [lab(lang, "window_start"), report["window_start"]],
        [lab(lang, "window_end"), report["window_end"]],
    ]
    return _md_table([lab(lang, "field"), lab(lang, "value")], rows)


def _checklist_block(report: dict, lang: str) -> str:
    rows = [
        [lab(lang, CHECK_LABEL_KEYS[key]), _yn(lang, report["checklist"][key])] for key in CHECKLIST_KEYS
    ]
    return _md_table([lab(lang, "item"), lab(lang, "confirmed")], rows)


def _summary_block(report: dict, lang: str) -> str:
    lines = [f"**{lab(lang, 'status')}:** {L(lang, *STATUS_WORD[report['status']])}", ""]
    if report["summary_note"]:
        lines.append(report["summary_note"])
        lines.append("")
    if report["status_reasons"]:
        lines.append(f"**{lab(lang, 'reasons')}**")
        lines.append("")
        for key in report["status_reasons"]:
            lines.append(f"- {_reason_line(lang, report, key)}")
    else:
        lines.append(lab(lang, "none_short"))
    return "\n".join(lines)


def _incident_headers(lang: str) -> list[str]:
    return [
        lab(lang, "id"),
        lab(lang, "title_col"),
        lab(lang, "severity"),
        lab(lang, "status"),
        lab(lang, "owner"),
        lab(lang, "opened"),
    ]


def _incident_rows(items: list[dict], lang: str) -> list[list]:
    return [
        [item["id"], item["title"], item["severity"], item["status"], item["owner_role"], item["opened"]]
        for item in items
    ]


def _incidents_block(report: dict, lang: str) -> str:
    open_items = [item for item in report["incidents"] if item["status"] == "open"]
    closed_items = [item for item in report["incidents"] if item["status"] == "closed"]
    chunks = [f"### {lab(lang, 'open_incidents_sub')}", ""]
    chunks.append(
        _md_table(_incident_headers(lang), _incident_rows(open_items, lang)) if open_items else lab(lang, "none")
    )
    chunks.extend(["", f"### {lab(lang, 'closed_incidents_sub')}", ""])
    chunks.append(
        _md_table(_incident_headers(lang), _incident_rows(closed_items, lang))
        if closed_items
        else lab(lang, "none")
    )
    return "\n".join(chunks)


def _changes_block(report: dict, lang: str) -> str:
    if not report["changes"]:
        return lab(lang, "none")
    rows = [
        [item["id"], item["title"], item["status"], item["owner_role"], item["summary"]]
        for item in report["changes"]
    ]
    return _md_table(
        [lab(lang, "id"), lab(lang, "title_col"), lab(lang, "status"), lab(lang, "owner"), lab(lang, "summary")],
        rows,
    )


def _hardware_block(report: dict, lang: str) -> str:
    if not report["hardware_actions"]:
        return lab(lang, "none")
    rows = [
        [
            item["id"],
            L(lang, *KIND_WORD[item["kind"]]),
            item["asset"],
            item["status"],
            item["owner_role"],
            item["summary"],
        ]
        for item in report["hardware_actions"]
    ]
    return _md_table(
        [
            lab(lang, "id"),
            lab(lang, "kind"),
            lab(lang, "asset"),
            lab(lang, "status"),
            lab(lang, "owner"),
            lab(lang, "summary"),
        ],
        rows,
    )


def _tasks_block(report: dict, lang: str) -> str:
    pending = [item for item in report["tasks"] if item["status"] == "open"]
    done = [item for item in report["tasks"] if item["status"] != "open"]
    headers = [
        lab(lang, "id"),
        lab(lang, "title_col"),
        lab(lang, "owner"),
        lab(lang, "due"),
        lab(lang, "status"),
        lab(lang, "overdue"),
    ]

    def body(items: list[dict]) -> str:
        if not items:
            return lab(lang, "none")
        rows = [
            [item["id"], item["title"], item["owner_role"], item["due"], item["status"], _yn(lang, item["overdue"])]
            for item in items
        ]
        return _md_table(headers, rows)

    return "\n".join(
        [
            f"### {lab(lang, 'open_incidents_sub')}",
            "",
            body(pending),
            "",
            f"### {lab(lang, 'closed_incidents_sub')}",
            "",
            body(done),
        ]
    )


def _risks_block(report: dict, lang: str) -> str:
    if not report["risks"]:
        return lab(lang, "none")
    rows = [[item["id"], item["item"], item["level"], item["note"]] for item in report["risks"]]
    return _md_table(
        [lab(lang, "id"), lab(lang, "item"), lab(lang, "level"), lab(lang, "note")],
        rows,
    )


def _kpis_block(report: dict, lang: str) -> str:
    kpis = report["kpis"]
    mttr = "n/a" if kpis["mttr_minutes"] is None else f"{kpis['mttr_minutes']:.1f}"
    rows = [
        [lab(lang, "kpi_opened"), str(kpis["tickets_opened"])],
        [lab(lang, "kpi_closed"), str(kpis["tickets_closed"])],
        [lab(lang, "kpi_open"), str(kpis["tickets_still_open"])],
        [lab(lang, "kpi_sla"), str(kpis["sla_breaches"])],
        [lab(lang, "kpi_mttr"), mttr],
    ]
    chunks = [_md_table([lab(lang, "kpi"), lab(lang, "value")], rows), "", f"### {lab(lang, 'tickets_sub')}", ""]
    if not report["tickets"]["rows"]:
        chunks.append(lab(lang, "none"))
    else:
        ticket_rows = [
            [
                item["ticket_id"],
                item["priority"],
                item["status"],
                item["category"],
                item["owner_role"],
                _yn(lang, item["opened_during_shift"]),
                _yn(lang, item["closed_during_shift"]),
                _yn(lang, item["sla_breach"]),
                item["summary"],
            ]
            for item in report["tickets"]["rows"]
        ]
        chunks.append(
            _md_table(
                [
                    lab(lang, "id"),
                    lab(lang, "priority"),
                    lab(lang, "status"),
                    lab(lang, "category"),
                    lab(lang, "owner"),
                    lab(lang, "opened_during"),
                    lab(lang, "closed_during"),
                    lab(lang, "kpi_sla"),
                    lab(lang, "summary"),
                ],
                ticket_rows,
            )
        )
    return "\n".join(chunks)


def _signoff_block(report: dict, lang: str) -> str:
    sign = report["sign_off"]
    table = _md_table(
        [lab(lang, "field"), lab(lang, "value")],
        [
            [lab(lang, "outgoing"), sign["outgoing_lead"]],
            [lab(lang, "incoming"), sign["incoming_lead"]],
            [lab(lang, "report_time"), sign["report_time"]],
        ],
    )
    return "\n".join([lab(lang, "sign_prose"), "", table])


def _apply_lang(template: str, lang: str) -> str:
    if lang not in {"en", "zh", "both"}:
        raise HandoverError("lang: must be en, zh, or both")

    def repl(match: re.Match) -> str:
        return match.group(2) if match.group(1) == lang else ""

    return _LANG_BLOCK.sub(repl, template)


def render_markdown(report: dict, lang: str, template_text: str | None = None) -> str:
    if template_text is None:
        if not TEMPLATE_PATH.is_file():
            raise HandoverError(f"template: file not found: {TEMPLATE_PATH}")
        template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    selected = _apply_lang(template_text, lang)
    values = {
        "shift_table": _shift_table(report, lang),
        "checklist_block": _checklist_block(report, lang),
        "summary_block": _summary_block(report, lang),
        "incidents_block": _incidents_block(report, lang),
        "changes_block": _changes_block(report, lang),
        "hardware_block": _hardware_block(report, lang),
        "tasks_block": _tasks_block(report, lang),
        "risks_block": _risks_block(report, lang),
        "kpis_block": _kpis_block(report, lang),
        "signoff_block": _signoff_block(report, lang),
    }

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise HandoverError(f"template: unknown placeholder {key!r}")
        return values[key]

    rendered = _PLACEHOLDER.sub(repl, selected)
    if "{{#" in rendered or "{{/" in rendered:
        raise HandoverError("template: unclosed language block")
    return re.sub(r"\n{3,}", "\n\n", rendered).strip() + "\n"


def format_summary(report: dict) -> str:
    kpis = report["kpis"]
    mttr = "n/a" if kpis["mttr_minutes"] is None else f"{kpis['mttr_minutes']:.1f}"
    reasons = ", ".join(report["status_reasons"]) or "none"
    return "\n".join(
        [
            f"site: {report['site']}",
            f"shift: {report['shift']} {report['date']}",
            f"status: {report['status']}",
            f"reasons: {reasons}",
            (
                f"tickets opened: {kpis['tickets_opened']}"
                f" closed: {kpis['tickets_closed']}"
                f" open: {kpis['tickets_still_open']}"
                f" sla_breaches: {kpis['sla_breaches']}"
            ),
            f"mttr_minutes: {mttr}",
        ]
    )


def _load_json(path: Path, kind: str):
    if not path.is_file():
        raise HandoverError(f"{kind}: file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HandoverError(f"{kind}: not valid JSON ({exc.msg})") from exc


def write_outputs(report: dict, out_dir: Path, lang: str, template_text: str | None = None) -> None:
    if out_dir.exists() and not out_dir.is_dir():
        raise HandoverError(f"out: not a directory: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report, lang, template_text)
    (out_dir / "handover.md").write_text(markdown, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a markdown shift handover. Alarm merge, HTML, JSON, and carry-over are full-pack only."
    )
    parser.add_argument("--input", required=True, help="Shift input JSON")
    parser.add_argument("--tickets", help="Ticket CSV")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--lang", default="both", choices=("en", "zh", "both"))
    parser.add_argument("--alarms", help=argparse.SUPPRESS)
    parser.add_argument("--prev", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code in (0, None):
            return 0
        return 1
    if args.alarms or args.prev:
        print(FULL_PACK_ERROR, file=sys.stderr)
        return 1
    try:
        shift = _load_json(Path(args.input), "input")
        tickets = load_csv(Path(args.tickets), TICKET_COLUMNS, "tickets") if args.tickets else []
        report = build_report(shift, tickets)
        write_outputs(report, Path(args.out), args.lang)
    except HandoverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_summary(report))
    return status_code(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
