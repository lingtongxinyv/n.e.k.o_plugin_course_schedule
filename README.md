# 课程表（Course Schedule）

通用课程表工具，采用「周重复 + 例外」时间模型。支持手动录入、文件/教务系统导入、AI 对话查询、上课提醒、作业考试管理、周数与倒计时。

## 功能亮点

| 功能 | 说明 |
|---|---|
| 📅 学期管理 | 创建多个学期，自动种入默认节次作息，随时切换 |
| 📚 课程录入 | 手动录入，或从 JSON / CSV / ICS 文件导入 |
| 🎓 教务系统同步 | 喜鹊儿/青果教务一键拉取课表（纯 Python DES 加密，零依赖） |
| ⏰ 上课提醒 | 自动检查即将开始的课程，提前 N 分钟推送通知 |
| 📝 作业 / 📋 考试 | 截止日期、关联课程、完成标记、逾期自动识别 |
| 🤖 AI 对话 | 自然语言查询今日课表、下节课、周数进度 |
| 📊 倒计时 | 距下次考试 / 下次作业 / 学期结束还有多少天 |
| 🌏 多语言 | 中文 / 英文 i18n |
| 🎨 TSX 面板 | N.E.K.O Hosted UI：今日/本周课表、一键录入、数据管理 |

## 快速开始

### 1. 创建学期

```python
add_semester(name="2025秋季", start_date="2025-09-01", end_date="2026-01-11")
```

会自动种入默认 11 节作息时间，可稍后用 `set_period_times` 覆盖。

### 2. 添加课程

```python
add_course(
    name="高等数学",
    teacher="王老师",
    location="3-201",
    sessions=[
        {"weekday": 1, "period_no": 1, "weeks": [1, 2, 3, 4, 5, 6, 7, 8]},
        {"weekday": 3, "period_no": 1, "weeks": None},  # None = 每周
    ],
)
```

- `weekday`：1=周一 … 7=周日
- `period_no`：第几节
- `weeks`：周次列表如 `[1, 3, 5]` 表示单周；留空或 `None` 表示每周

### 3. 查询课表

```python
get_today_schedule()        # 今日课表
get_tomorrow_schedule()     # 明日课表
get_week_schedule()         # 本周整周课表
get_next_class()            # 下节课
get_week_info()             # 当前周数 + 学期进度
```

### 4. 导入课表

```python
# 从 JSON / CSV / ICS 文件导入
import_schedule(format="json", content="<文件内容>")

# AI 对话 / 后端结构化数据导入
import_from_structured(data={...})

# 教务系统一键拉取
import_from_academic(
    adapter="xiqueer",
    username="学号",
    password="密码",
    base_url="https://你的学校教务地址/",
)
```

### 5. 上课提醒

编辑 `config.json`（或通过插件管理面板修改配置）：

```json
{
    "course": {
        "remind_enabled": true,
        "remind_lead_minutes": 10
    }
}
```

启用后每分钟自动检查，提前 10 分钟推送提醒消息。

## 时间模型

**周重复 + 例外**：常规课程按「每周几 + 第几节 + （可选）周次过滤」重复。例外情况通过 `add_exception` 处理：

| kind | 说明 |
|---|---|
| `cancel` | 取消某天某节（如运动会停课），需 `course_id` + `period_no` |
| `add` | 新增单次安排（如临时补课），`course_id` 可空，用 `title` 作课名 |

**调课 = cancel（原时段）+ add（新时段）**。

## 入口点一览

### Manage（学期 & 课程）

| ID | 说明 |
|---|---|
| `add_semester` | 创建学期 |
| `add_course` | 添加课程（含多个 sessions） |
| `add_session` | 单独给已有课程添加一个上课时段 |
| `add_exception` | 添加例外（取消 / 新增单次） |
| `switch_semester` | 切换当前学期 |
| `list_semesters` | 列出所有学期 |
| `list_courses` | 列出当前学期课程 |
| `set_period_times` | 设置节次作息时间 |

### Query（查询）

| ID | 说明 |
|---|---|
| `get_today_schedule` | 今日课表 |
| `get_tomorrow_schedule` | 明日课表 |
| `get_week_schedule` | 本周课表（按天分组） |
| `get_next_class` | 下一节课 |
| `get_week_info` | 当前周数 + 学期进度 |

### Tasks（作业 & 考试 & 倒计时）

| ID | 说明 |
|---|---|
| `add_homework` | 添加作业 |
| `list_homework` | 作业列表（逾期自动标记） |
| `done_homework` | 标记作业完成 / 取消完成 |
| `delete_homework` | 删除作业 |
| `add_exam` | 添加考试 |
| `list_exams` | 考试列表 |
| `delete_exam` | 删除考试 |
| `get_countdown` | 综合倒计时（下次考试 / 下次作业 / 学期结束） |

### Import / Export

| ID | 说明 |
|---|---|
| `import_schedule` | 从 JSON / CSV / ICS 字符串导入 |
| `import_from_structured` | 从结构化字典导入（AI 对话用） |
| `import_from_academic` | 从教务系统拉取（喜鹊儿等） |
| `list_academic_adapters` | 列出可用教务适配器 |
| `export_schedule` | 导出为 JSON / CSV / ICS |

### Lifecycle

| ID | 说明 |
|---|---|
| `startup` | 插件启动（自动调用） |
| `shutdown` | 插件停止（自动调用） |
| `config_change` | 配置变更（自动调用） |
| `class_reminder_check` | 定时提醒检查（每 60s） |

## 配置说明

`plugin.toml` 中的 `[course]` 段：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `timezone` | string | `Asia/Shanghai` | 时区 |
| `remind_enabled` | bool | `false` | 是否启用上课提醒 |
| `remind_lead_minutes` | int | `10` | 提前多少分钟提醒 |
| `remind_check_interval_seconds` | int | `60` | 定时检查间隔 |

## 目录结构

```text
course_schedule/
├── __init__.py              ← 主插件：UI context、默认 action 白名单
├── _repo.py                 ← 数据库访问层（aiosqlite）
├── _schema.py               ← SQLite schema
├── _time.py                 ← 时间工具（周数、节次、星期）
├── _academic_adapter.py     ← 教务适配器抽象基类
├── config.example.toml      ← 配置模板
├── plugin.toml              ← 插件配置（Market 读取）
├── routers/
│   ├── __init__.py
│   ├── manage.py            ← 学期 / 课程 CRUD
│   ├── query.py             ← 查询类入口
│   ├── tasks.py             ← 作业 / 考试 / 倒计时
│   ├── import_export.py     ← 文件导入 / 导出
│   └── academic.py          ← 教务系统入口
├── _adapters/
│   ├── __init__.py          ← 适配器注册表
│   ├── jkingo_des.py        ← 纯 Python DES 加密（喜鹊儿用）
│   └── xiqueer.py           ← 喜鹊儿 / 青果教务适配器
├── ui/
│   └── panel.tsx            ← N.E.K.O Hosted UI 面板
├── i18n/
│   ├── zh-CN.json
│   └── en.json
├── docs/
│   └── guide.md             ← 插件管理面板内显示的使用指南
└── .github/workflows/
    ├── verify.yml           ← Market 验证 CI
    └── release.yml          ← Market Release CI
```

## 开发

本仓库是插件自身的 Git 仓库。开发时放在 N.E.K.O 源码目录：

```text
N.E.K.O/plugin/plugins/course_schedule/
```

从 N.E.K.O 源码根目录运行：

```bash
# 检查插件
uv run neko-plugin check course_schedule

# 完整发布检查
uv run neko-plugin check course_schedule --release
```

## 发布流程

```
修改源码 → 更新 plugin.toml 版本号 → check → git commit/push → neko-plugin publish
```

详见 [N.E.K.O 插件市场发布指南](https://project-neko.online/zh-CN/plugins/cli)。

## Entry

```toml
entry = "plugin.plugins.course_schedule:CourseSchedulePlugin"
```
