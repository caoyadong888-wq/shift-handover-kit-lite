#!/usr/bin/env python3
"""Lite generator: shift JSON plus tickets, markdown only, no alarms or carry-over."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from handover_gen import build_report, main  # noqa: E402


def minimal_shift(**overrides):
    data = {
        "site": "DC1 Hall B",
        "shift": "day",
        "date": "2026-10-19",
        "outgoing_lead": "Shift A lead",
        "incoming_lead": "Shift B lead",
        "window_start": "2026-10-19T08:00:00",
        "window_end": "2026-10-19T16:00:00",
        "summary_note": "Quiet shift.",
        "checklist": {
            "walkdown": True,
            "alarms_acked": True,
            "tickets_reviewed": True,
            "change_freeze": False,
            "spares": True,
            "access_log": True,
        },
        "incidents": [],
        "changes": [],
        "hardware_actions": [],
        "tasks": [],
        "risks": [],
    }
    data.update(overrides)
    return data


def ticket(ticket_id, opened, closed, priority, status, **extra):
    row = {
        "ticket_id": ticket_id,
        "opened": opened,
        "closed": closed,
        "priority": priority,
        "status": status,
        "category": "power",
        "summary": "Synthetic ticket",
        "owner_role": "Hall B tech",
    }
    row.update(extra)
    return row


def p_incident(item_id, severity, status="open"):
    row = {
        "id": item_id,
        "title": "Synthetic incident",
        "severity": severity,
        "status": status,
        "opened": "2026-10-19T09:00:00",
        "owner_role": "Hall B tech",
        "summary": "",
    }
    if status == "closed":
        row["closed"] = "2026-10-19T10:00:00"
    return row


def run_main(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(argv)
    return code, stdout.getvalue(), stderr.getvalue()


class LiteHandoverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def drive(self, shift, tickets_text=None, lang=None, argv_prefix=None):
        argv = list(argv_prefix or [])
        shift_path = self.root / "shift.json"
        if isinstance(shift, str):
            shift_path.write_text(shift, encoding="utf-8")
        else:
            shift_path.write_text(json.dumps(shift), encoding="utf-8")
        argv += ["--input", str(shift_path)]
        if tickets_text is not None:
            path = self.root / "tickets.csv"
            path.write_text(tickets_text, encoding="utf-8")
            argv += ["--tickets", str(path)]
        out = self.root / "out"
        argv += ["--out", str(out)]
        if lang:
            argv += ["--lang", lang]
        code, stdout, stderr = run_main(argv)
        return code, stdout, stderr, out

    def test_rejects_invalid_json(self):
        code, _stdout, stderr, out = self.drive("{")
        self.assertEqual(code, 1)
        self.assertIn("not valid JSON", stderr)
        self.assertFalse((out / "handover.md").exists())

    def test_rejects_missing_site(self):
        data = minimal_shift()
        del data["site"]
        code, _stdout, stderr, out = self.drive(data)
        self.assertEqual(code, 1)
        self.assertIn("missing required field 'site'", stderr)
        self.assertFalse((out / "handover.md").exists())

    def test_rejects_unknown_field(self):
        code, _stdout, stderr, _out = self.drive(minimal_shift(site_name="DC1 Hall B"))
        self.assertEqual(code, 1)
        self.assertIn("unknown field 'site_name'", stderr)

    def test_rejects_window_order(self):
        data = minimal_shift(window_start="2026-10-19T16:00:00", window_end="2026-10-19T08:00:00")
        code, _stdout, stderr, _out = self.drive(data)
        self.assertEqual(code, 1)
        self.assertIn("'window_end' must be after 'window_start'", stderr)

    def test_rejects_bad_severity(self):
        data = minimal_shift(incidents=[p_incident("INC-1", "P9")])
        code, _stdout, stderr, _out = self.drive(data)
        self.assertEqual(code, 1)
        self.assertIn("unknown severity", stderr)

    def test_rejects_open_ticket_with_closed_time(self):
        text = (
            "ticket_id,opened,closed,priority,status,category,summary,owner_role\n"
            "TCK-1,2026-10-19T09:00:00,2026-10-19T10:00:00,P3,open,power,Still open,Hall B tech\n"
        )
        code, _stdout, stderr, _out = self.drive(minimal_shift(), tickets_text=text)
        self.assertEqual(code, 1)
        self.assertIn("status is open but 'closed' is set", stderr)

    def test_rejects_missing_priority_column(self):
        text = "ticket_id,opened,closed,status,category,summary,owner_role\n"
        code, _stdout, stderr, _out = self.drive(minimal_shift(), tickets_text=text)
        self.assertEqual(code, 1)
        self.assertIn("missing column 'priority'", stderr)

    def test_rejects_duplicate_ticket_id(self):
        text = (
            "ticket_id,opened,closed,priority,status,category,summary,owner_role\n"
            "TCK-1,2026-10-19T09:00:00,,P3,open,power,One,Hall B tech\n"
            "TCK-1,2026-10-19T10:00:00,,P3,open,power,Two,Hall B tech\n"
        )
        code, _stdout, stderr, _out = self.drive(minimal_shift(), tickets_text=text)
        self.assertEqual(code, 1)
        self.assertIn("duplicate", stderr)

    def test_green_writes_markdown_only(self):
        code, stdout, _stderr, out = self.drive(minimal_shift())
        self.assertEqual(code, 0)
        self.assertIn("status: green", stdout)
        self.assertTrue((out / "handover.md").is_file())
        self.assertFalse((out / "handover.html").exists())
        self.assertFalse((out / "handover.json").exists())
        text = (out / "handover.md").read_text(encoding="utf-8")
        self.assertIn("GREEN / 正常", text)
        self.assertNotIn("carried", text.lower())
        self.assertNotIn("<script", text.lower())

    def test_open_p1_exits_3(self):
        code, stdout, _stderr, _out = self.drive(minimal_shift(incidents=[p_incident("INC-1", "P1")]))
        self.assertEqual(code, 3)
        self.assertIn("status: red", stdout)
        self.assertIn("open_p1", stdout)

    def test_open_p2_exits_2(self):
        code, stdout, _stderr, _out = self.drive(minimal_shift(incidents=[p_incident("INC-2", "P2")]))
        self.assertEqual(code, 2)
        self.assertIn("status: amber", stdout)
        self.assertIn("open_p2", stdout)

    def test_open_p3_stays_green(self):
        report = build_report(minimal_shift(incidents=[p_incident("INC-3", "P3")]))
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["status_reasons"], [])

    def test_overdue_task_is_amber(self):
        data = minimal_shift(
            tasks=[
                {
                    "id": "TASK-1",
                    "title": "Late filter",
                    "owner_role": "Facilities watch",
                    "due": "2026-10-18",
                    "status": "open",
                }
            ]
        )
        code, stdout, _stderr, _out = self.drive(data)
        self.assertEqual(code, 2)
        self.assertIn("overdue_task", stdout)

    def test_due_on_window_end_date_is_not_overdue(self):
        data = minimal_shift(
            tasks=[
                {
                    "id": "TASK-2",
                    "title": "Same day",
                    "owner_role": "Hall B tech",
                    "due": "2026-10-19",
                    "status": "open",
                }
            ]
        )
        report = build_report(data)
        self.assertFalse(report["tasks"][0]["overdue"])
        self.assertEqual(report["status"], "green")

    def test_p1_four_hours_is_not_sla(self):
        shift = minimal_shift(window_start="2026-10-19T08:00:00", window_end="2026-10-19T12:00:00")
        report = build_report(shift, [ticket("TCK-1", "2026-10-19T08:00:00", "", "P1", "open")])
        self.assertEqual(report["status"], "red")
        self.assertEqual(report["status_detail"]["sla_breach"], [])
        self.assertIn("TCK-1", report["status_detail"]["open_p1"])

    def test_p2_over_eight_hours_is_sla(self):
        shift = minimal_shift(window_start="2026-10-19T07:00:00", window_end="2026-10-19T16:00:00")
        report = build_report(shift, [ticket("TCK-9", "2026-10-19T07:59:59", "", "P2", "open")])
        self.assertEqual(report["status"], "amber")
        self.assertIn("TCK-9", report["status_detail"]["sla_breach"])
        exact = build_report(
            minimal_shift(window_start="2026-10-19T08:00:00", window_end="2026-10-19T16:00:00"),
            [ticket("TCK-8", "2026-10-19T08:00:00", "", "P2", "open")],
        )
        self.assertEqual(exact["status_detail"]["sla_breach"], [])
        self.assertIn("TCK-8", exact["status_detail"]["open_p2"])

    def test_closed_ticket_is_not_sla(self):
        shift = minimal_shift()
        report = build_report(shift, [ticket("TCK-1", "2026-10-19T08:00:00", "2026-10-19T18:00:00", "P1", "closed")])
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["status_detail"]["sla_breach"], [])

    def test_red_keeps_amber_reasons(self):
        data = minimal_shift(
            incidents=[p_incident("INC-1", "P1")],
            tasks=[
                {
                    "id": "TASK-1",
                    "title": "Late",
                    "owner_role": "Hall B tech",
                    "due": "2026-10-18",
                    "status": "open",
                }
            ],
        )
        report = build_report(data)
        self.assertEqual(report["status"], "red")
        self.assertIn("open_p1", report["status_reasons"])
        self.assertIn("overdue_task", report["status_reasons"])
        self.assertNotIn("alarms", report)
        self.assertNotIn("carry_over", report)

    def test_lang_blocks(self):
        code, _stdout, _stderr, out = self.drive(minimal_shift(), lang="en")
        self.assertEqual(code, 0)
        text = (out / "handover.md").read_text(encoding="utf-8")
        self.assertIn("# Shift handover report\n", text)
        self.assertNotIn("交接班报告", text)
        code, _stdout, _stderr, out = self.drive(minimal_shift(), lang="zh")
        self.assertEqual(code, 0)
        text = (out / "handover.md").read_text(encoding="utf-8")
        self.assertIn("# 交接班报告\n", text)
        self.assertNotIn("Shift handover report", text)
        code, _stdout, _stderr, out = self.drive(minimal_shift(), lang="both")
        self.assertEqual(code, 0)
        text = (out / "handover.md").read_text(encoding="utf-8")
        self.assertIn("# Shift handover report / 交接班报告", text)

    def test_alarms_flag_rejected(self):
        code, _stdout, stderr, out = self.drive(minimal_shift(), argv_prefix=["--alarms", "alarms.csv"])
        self.assertEqual(code, 1)
        self.assertIn("full-pack only", stderr)
        self.assertFalse((out / "handover.md").exists())
        self.assertFalse((out / "handover.html").exists())

    def test_prev_flag_rejected(self):
        code, _stdout, stderr, out = self.drive(minimal_shift(), argv_prefix=["--prev", "prev.json"])
        self.assertEqual(code, 1)
        self.assertIn("full-pack only", stderr)
        self.assertFalse((out / "handover.json").exists())

    def test_sample_omits_carry_and_alarms(self):
        shift = json.loads((ROOT / "samples" / "shift_input.json").read_text(encoding="utf-8"))
        tickets = (ROOT / "samples" / "tickets.csv").read_text(encoding="utf-8")
        code, stdout, _stderr, out = self.drive(shift, tickets_text=tickets)
        self.assertEqual(code, 3)
        self.assertIn("status: red", stdout)
        self.assertIn("sla_breaches: 2", stdout)
        self.assertNotIn("uncleared_critical", stdout)
        self.assertNotIn("carried_over", stdout)
        text = (out / "handover.md").read_text(encoding="utf-8")
        self.assertIn("INC-118", text)
        self.assertIn("TCK-2402", text)
        self.assertNotIn("INC-104", text)
        self.assertNotIn("PDU-B-R4", text)
        self.assertNotIn("carried", text.lower())
        self.assertFalse((out / "handover.html").exists())
        self.assertFalse((out / "handover.json").exists())


if __name__ == "__main__":
    unittest.main()
