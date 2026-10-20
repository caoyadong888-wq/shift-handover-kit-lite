# Full pack only

# 只在完整包里

This lite tree reads a shift JSON file and a ticket CSV. It writes `handover.md` and paints one red / amber / green status from open P1 work, open P2 work, SLA, and overdue tasks.

本精简版只读班次 JSON 和工单 CSV。它写出 `handover.md`，并用未关闭的 P1、未关闭的 P2、时限和逾期任务涂一种红 / 琥珀 / 绿。

Not in this tree:

- Alarm CSV merge, and an uncleared critical alarm as a red reason
- `handover.html` and `handover.json`
- Carry-over flags from the previous handover
- Store cover images

不在这里：

- 告警 CSV 合并，以及把未清除的严重告警当作红色原因
- `handover.html` 和 `handover.json`
- 从上一份交接报告标承接
- 商店封面
