# How the lite report colour is chosen

# 精简版报告颜色怎么定

`scripts/handover_gen.py` paints one colour for the whole shift. Red wins over amber. Amber wins over green.

`scripts/handover_gen.py` 给整班只涂一种颜色。红色压过琥珀色。琥珀色压过绿色。

1. Red when any P1 ticket or P1 incident is still open.
2. Otherwise amber when any P2 ticket or P2 incident is still open, or any open ticket has breached SLA, or any task is overdue.
3. Otherwise green.

1. 仍有未关闭的 P1 工单或 P1 事件，就是红色。
2. 否则，仍有未关闭的 P2 工单或 P2 事件，或有未关闭工单超出时限，或有任务逾期，就是琥珀色。
3. 否则是绿色。

Alarm rows do not change the colour here. Carry-over is not computed. Both are full-pack only (`reference/FULL_PACK_ONLY.md`).

告警行在这里不改变颜色。也不计算承接。这两项只在完整包里（`reference/FULL_PACK_ONLY.md`）。

P1 older than 4 hours, or P2 older than 8 hours, is an SLA breach while the ticket is still open. Exactly 4 hours and exactly 8 hours are not breaches. The clock stops at `window_end`.

仍未关闭时，P1 超过 4 小时或 P2 超过 8 小时算超出时限。刚好 4 小时和刚好 8 小时不算。时钟停在 `window_end`。

A date-only task due on the calendar date of `window_end` is not overdue. A timestamp due strictly before `window_end` is overdue when the task is still open.

只有日期、而且就是 `window_end` 那天的任务，不算逾期。时刻严格早于 `window_end`、任务仍是 open，才算逾期。

A false checklist item does not by itself change the colour.

检查单某一项是 false，本身不改变颜色。
