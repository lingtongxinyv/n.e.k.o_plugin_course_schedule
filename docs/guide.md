# 课程表插件使用指南

通用课程表工具，采用「周重复 + 例外」时间模型。

## 快速开始

1. **添加学期**：`add_semester(name="2025秋季", start_date="2025-09-01", end_date="2026-01-11")`
   - 会自动种入默认节次作息（第 1-11 节），可用 `set_period_times` 覆盖。
2. **添加课程**：`add_course(name="高等数学", teacher="王老师", location="3-201", sessions=[{"weekday":1,"period_no":1},{"weekday":3,"period_no":1}])`
   - `weekday`：1=周一 … 7=周日；`period_no`：第几节。
   - `weeks`：留空=每周；填周次列表如 `[1,3,5]` 表示只在这些周上（可表达单双周）。
3. **查询**：`get_today_schedule` / `get_tomorrow_schedule` / `get_week_schedule` / `get_next_class` / `get_week_info`

## 时间模型

- **周重复**：常规课按「每周几 + 第几节」重复，作用于学期范围内。
- **例外**：用 `add_exception` 处理临时情况
  - `cancel`：取消某天某节（需 `course_id` + `period_no`）。
  - `add`：新增单次安排（`course_id` 可空，用 `title` 作课名）。
  - 调课 = `cancel`（原时段）+ `add`（新时段）。

## 配置

`plugin.toml` 的 `[course]` 段：

| 字段 | 说明 | 默认 |
|---|---|---|
| `timezone` | 时区 | Asia/Shanghai |
| `remind_enabled` | 上课提醒（P2 启用） | false |
| `remind_lead_minutes` | 提前提醒分钟数 | 10 |
| `remind_check_interval_seconds` | 检查间隔 | 60 |
