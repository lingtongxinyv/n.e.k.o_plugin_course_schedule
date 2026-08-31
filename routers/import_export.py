"""课程表导入/导出入口。

支持四种来源：
1. 自描述 JSON（最通用，import_schedule format=json）
2. CSV 表格文本（import_schedule format=csv）
3. iCalendar .ics（import_schedule format=ics）
4. 结构化 dict（import_from_structured，供 AI 对话 / 教务适配器调用）

所有导入都会先"预览/校验"再入库，返回 created / skipped 统计。
"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any

from plugin.sdk.plugin import Err, Ok, SdkError, plugin_entry
from plugin.sdk.shared.core.router import PluginRouter

from .._time import parse_date, parse_weekday

# ──────────────────────────────────────────────────────────────
# 纯函数：各种格式 → 统一中间结构
# 中间结构（normalized）：
#   {
#     "semester": {"name", "start_date", "end_date", "total_weeks?"},
#     "courses": [
#       {"name", "code?", "teacher?", "location?", "color?", "note?",
#        "sessions": [{"weekday": 1-7, "period_no": int, "weeks": [int...] or None}]}
#     ],
#     "exceptions": [{"date": "YYYY-MM-DD", "kind": "cancel"|"add",
#                     "course_match": {"name?"} 或 "title",
#                     "period_no", "location?", "note?"}]
#   }
# ──────────────────────────────────────────────────────────────


def _detect_format(content: str) -> str:
    s = content.lstrip()
    if s.startswith("{") or s.startswith("["):
        return "json"
    if s.startswith("BEGIN:VCALENDAR") or s.startswith("BEGIN:VEVENT"):
        return "ics"
    # 粗略判断 CSV：有表头逗号分隔
    head = content.splitlines()[0] if content else ""
    if "," in head and any(k in head.lower() for k in ("课", "课程", "星期", "weekday", "name")):
        return "csv"
    return "json"  # 兜底


def parse_json(content: str) -> dict:
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("JSON 根必须是对象")
    return data


def parse_csv(content: str) -> dict:
    """解析简单 CSV 课表。

    期望列（中文/英文任一即可）：
    weekday（星期,周几）, period_no（节次,period）, course_name（课程,name）,
    teacher（教师）, location（地点）, weeks（周次）
    同一门课可出现在多行，按 name 聚合。
    """
    reader = csv.DictReader(io.StringIO(content))
    courses_map: dict[str, dict] = {}
    for row in reader:
        name = (row.get("course_name") or row.get("课程") or row.get("name") or "").strip()
        if not name:
            continue
        wd = parse_weekday(row.get("weekday") or row.get("星期") or row.get("周几") or "")
        pno = row.get("period_no") or row.get("节次") or row.get("period") or ""
        try:
            pno = int(str(pno).strip())
        except ValueError:
            pno = 0
        weeks = _parse_weeks_field(row.get("weeks") or row.get("周次") or "")
        teacher = (row.get("teacher") or row.get("教师") or "").strip() or None
        location = (row.get("location") or row.get("地点") or "").strip() or None
        code = (row.get("code") or row.get("课程代码") or "").strip() or None
        note = (row.get("note") or row.get("备注") or "").strip() or None

        course = courses_map.setdefault(
            name,
            {
                "name": name,
                "code": code,
                "teacher": teacher,
                "location": location,
                "note": note,
                "sessions": [],
            },
        )
        if wd and pno:
            course["sessions"].append({"weekday": wd, "period_no": pno, "weeks": weeks})

    return {"courses": list(courses_map.values())}


def parse_ics(content: str) -> dict:
    """解析 iCalendar (RFC 5545)。

    策略：抓所有 VEVENT，按 SUMMARY 聚合成课程；从 RRULE / RDATE 推导 weekday+weeks；
    DTSTART 取 time-of-day 映射到 period_no（按默认作息时间）。
    """

    events: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for raw in content.splitlines():
        line = raw.rstrip("\r")
        if line.startswith("BEGIN:VEVENT"):
            cur = {}
        elif line.startswith("END:VEVENT") and cur is not None:
            events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, _, val = line.partition(":")
            # 处理带参数的属性，如 DTSTART;TZID=Asia/Shanghai:2025-09-01T08:00:00
            prop = key.split(";")[0].upper()
            cur.setdefault(prop, []).append(val)

    # 中国高校默认作息（与 _schema.DEFAULT_PERIOD_TIMES 同步）
    _PERIOD_STARTS = [
        "08:00",
        "08:55",
        "10:00",
        "10:55",
        "14:00",
        "14:55",
        "16:00",
        "16:55",
        "19:00",
        "19:55",
        "20:50",
    ]

    def _time_to_period(dt_str: str) -> int | None:
        # DTSTART 可能是 20250901T080000 或 2025-09-01T08:00:00
        m = re.search(r"(\d{1,2}):(\d{2})", dt_str)
        if not m:
            m = re.search(r"T(\d{2})(\d{2})", dt_str)
        if not m:
            return None
        hhmm = f"{m.group(1)}:{m.group(2)}"
        for i, start in enumerate(_PERIOD_STARTS, start=1):
            if hhmm == start:
                return i
        return None

    courses_map: dict[str, dict] = {}
    for ev in events:
        summary = (ev.get("SUMMARY") or ["未命名"])[0].strip()
        desc = (ev.get("DESCRIPTION") or [""])[0].strip()
        loc = (ev.get("LOCATION") or [""])[0].strip() or None
        dtstart = (ev.get("DTSTART") or [""])[0]
        rrule = (ev.get("RRULE") or [""])[0]

        period_no = _time_to_period(dtstart)

        # weekday：从 RRULE 的 BYDAY 提取
        weekday = None
        m = re.search(r"BYDAY=([A-Z,]+)", rrule.upper())
        if m:
            day_map = {"MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6, "SU": 7}
            for d in m.group(1).split(","):
                if d in day_map:
                    weekday = day_map[d]
                    break

        if not summary:
            continue
        course = courses_map.setdefault(
            summary,
            {
                "name": summary,
                "location": loc,
                "note": desc or None,
                "sessions": [],
            },
        )
        if weekday and period_no:
            # 同 (weekday, period) 去重
            already = {(s["weekday"], s["period_no"]) for s in course["sessions"]}
            if (weekday, period_no) not in already:
                course["sessions"].append({"weekday": weekday, "period_no": period_no, "weeks": None})

    return {"courses": list(courses_map.values())}


def _parse_weeks_field(s: str) -> list[int] | None:
    """解析 "1-8,10,12-15" 这类周次串，返回 [1,2,3,4,5,6,7,8,10,12,13,14,15]。空=每周。"""
    s = s.strip()
    if not s or s.lower() in ("all", "每周", "每", "全周", "*"):
        return None
    out: list[int] = []
    for part in re.split(r"[,，、\s]+", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~到至]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            for w in range(min(a, b), max(a, b) + 1):
                out.append(w)
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return sorted(set(out)) if out else None


# ──────────────────────────────────────────────────────────────
# 入库逻辑
# ──────────────────────────────────────────────────────────────


async def _apply_normalized(router: PluginRouter, data: dict, semester_id: int) -> dict:
    """把 normalized dict 写入数据库，返回统计。"""
    repo = router.main_plugin.repo

    # 1) 如果 data 里带 semester 元数据、且没指定 semester_id → 创建
    sem_info = data.get("semester") or {}
    sem = None
    if semester_id:
        for s in await repo.list_semesters():
            if s["id"] == semester_id:
                sem = s
                break
    if sem is None and sem_info.get("start_date") and sem_info.get("end_date"):
        sem = await repo.add_semester(
            name=sem_info.get("name") or "导入学期",
            start_date=parse_date(sem_info["start_date"]),
            end_date=parse_date(sem_info["end_date"]),
            total_weeks=int(sem_info.get("total_weeks") or 0),
            activate=True,
        )
    if sem is None:
        sem = await repo.get_active_semester()
    if sem is None:
        raise ValueError("没有可用学期：请先 add_semester 或在导入数据里带 semester 块")

    created_courses = 0
    created_sessions = 0
    skipped_sessions = 0
    created_exceptions = 0

    # 2) 课程
    for cd in data.get("courses", []):
        name = (cd.get("name") or "").strip()
        if not name:
            continue
        course = await repo.add_course(
            semester_id=sem["id"],
            name=name,
            code=(cd.get("code") or None),
            teacher=(cd.get("teacher") or None),
            location=(cd.get("location") or None),
            color=(cd.get("color") or None),
            note=(cd.get("note") or None),
        )
        created_courses += 1
        for s in cd.get("sessions", []) or []:
            wd = s.get("weekday")
            pno = s.get("period_no")
            if not (1 <= int(wd) <= 7) or int(pno) < 1:
                skipped_sessions += 1
                continue
            await repo.add_session(
                course_id=course["id"],
                weekday=int(wd),
                period_no=int(pno),
                weeks=s.get("weeks"),
                note=s.get("note"),
            )
            created_sessions += 1

    # 3) 例外（需要第二次遍历课程按 name 查找 course_id）
    courses_all = await repo.list_courses(sem["id"])
    for ed in data.get("exceptions", []) or []:
        d = parse_date(ed.get("date") or "")
        if not d or ed.get("kind") not in ("cancel", "add"):
            continue
        match_name = None
        cm = ed.get("course_match") or {}
        if isinstance(cm, str):
            match_name = cm
        else:
            match_name = cm.get("name") if isinstance(cm, dict) else None
        course_id = None
        if match_name:
            for c in courses_all:
                if c["name"] == match_name:
                    course_id = c["id"]
                    break
        await repo.add_exception(
            semester_id=sem["id"],
            course_id=course_id,
            title=ed.get("title"),
            date=d,
            kind=ed["kind"],
            period_no=int(ed.get("period_no")) if ed.get("period_no") else None,
            location=ed.get("location"),
            note=ed.get("note"),
        )
        created_exceptions += 1

    return {
        "semester_id": sem["id"],
        "created_courses": created_courses,
        "created_sessions": created_sessions,
        "created_exceptions": created_exceptions,
        "skipped_sessions": skipped_sessions,
    }


# ──────────────────────────────────────────────────────────────
# 导出
# ──────────────────────────────────────────────────────────────


async def _build_normalized_for_export(router: PluginRouter, semester_id: int) -> dict:
    repo = router.main_plugin.repo

    # 用 execute 查询 sessions
    async with await repo._session() as session:
        sem_row = None
        cur = await session.execute("SELECT * FROM semesters WHERE id = ?", (int(semester_id),))
        sem_row = cur.fetchone()
        if not sem_row:
            raise ValueError(f"semester_id={semester_id} 不存在")
        sem = dict(sem_row)
        cur = await session.execute("SELECT * FROM courses WHERE semester_id = ? ORDER BY id", (int(semester_id),))
        courses_rows = [dict(r) for r in cur.fetchall()]
        cur = await session.execute(
            "SELECT cs.* FROM course_sessions cs JOIN courses c ON c.id = cs.course_id "
            "WHERE c.semester_id = ? ORDER BY c.id, cs.weekday, cs.period_no",
            (int(semester_id),),
        )
        sessions_rows = [dict(r) for r in cur.fetchall()]
        cur = await session.execute("SELECT * FROM exceptions WHERE semester_id = ? ORDER BY date", (int(semester_id),))
        exceptions_rows = [dict(r) for r in cur.fetchall()]

    sessions_by_course: dict[int, list[dict]] = {}
    for s in sessions_rows:
        sessions_by_course.setdefault(s["course_id"], []).append(
            {
                "weekday": int(s["weekday"]),
                "period_no": int(s["period_no"]),
                "weeks": json.loads(s["weeks"]) if s["weeks"] else None,
                "note": s["note"],
            }
        )

    courses_out = []
    for c in courses_rows:
        courses_out.append(
            {
                "name": c["name"],
                "code": c["code"],
                "teacher": c["teacher"],
                "location": c["location"],
                "color": c["color"],
                "note": c["note"],
                "sessions": sessions_by_course.get(c["id"], []),
            }
        )

    exceptions_out = []
    course_name_by_id = {c["id"]: c["name"] for c in courses_rows}
    for e in exceptions_rows:
        exceptions_out.append(
            {
                "date": e["date"],
                "kind": e["kind"],
                "course_match": {"name": course_name_by_id.get(e["course_id"])} if e["course_id"] else None,
                "title": e["title"],
                "period_no": e["period_no"],
                "location": e["location"],
                "note": e["note"],
            }
        )

    return {
        "semester": {
            "id": sem["id"],
            "name": sem["name"],
            "start_date": sem["start_date"],
            "end_date": sem["end_date"],
            "total_weeks": sem["total_weeks"],
        },
        "courses": courses_out,
        "exceptions": exceptions_out,
    }


# ──────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────


class ImportExportRouter(PluginRouter):
    def __init__(self):
        super().__init__(name="import_export")

    @property
    def repo(self):
        return self.main_plugin.repo

    # ── 通用导入：文本 + 格式 ──

    @plugin_entry(
        id="import_schedule",
        name="导入课表（文件）",
        description=(
            "从文本内容导入课表，format=json|csv|ics|auto（auto=自动检测）。"
            "content 粘贴文件的原始文本内容。semester_id 留空则用当前学期；"
            "若当前学期不存在，且 content 是带 semester 元信息的 JSON，会自动新建学期。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "json/csv/ics/auto，默认 auto"},
                "content": {"type": "string", "description": "文件文本内容"},
                "semester_id": {"type": "integer", "description": "目标学期 ID，可空"},
            },
            "required": ["content"],
        },
    )
    async def import_schedule(self, content: str, format: str = "auto", semester_id: int = 0, **_):
        fmt = (format or "auto").lower()
        if fmt == "auto":
            fmt = _detect_format(content)
        try:
            if fmt == "json":
                data = parse_json(content)
            elif fmt == "csv":
                data = parse_csv(content)
            elif fmt == "ics":
                data = parse_ics(content)
            else:
                return Err(SdkError(f"不支持的 format: {format}"))
        except Exception as exc:
            return Err(SdkError(f"解析失败（{fmt}）: {exc}"))

        try:
            stats = await _apply_normalized(self, data, int(semester_id or 0))
        except Exception as exc:
            return Err(SdkError(f"入库失败: {exc}"))
        return Ok({"format": fmt, "stats": stats})

    # ── AI 对话 / 教务适配器：直接传结构化 dict ──

    @plugin_entry(
        id="import_from_structured",
        name="导入结构化课表",
        description=(
            "直接接受结构化 dict 入库（AI 对话录入、教务系统适配器都会用这个入口）。"
            "结构：{semester?:{...}, courses:[{name,sessions:[...]}], exceptions:[...]}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "结构化课表数据"},
                "semester_id": {"type": "integer", "description": "目标学期 ID，可空"},
            },
            "required": ["data"],
        },
    )
    async def import_from_structured(self, data: dict, semester_id: int = 0, **_):
        if not isinstance(data, dict):
            return Err(SdkError("data 必须是对象"))
        try:
            stats = await _apply_normalized(self, data, int(semester_id or 0))
        except Exception as exc:
            return Err(SdkError(f"入库失败: {exc}"))
        return Ok({"stats": stats})

    # ── 导出 ──

    @plugin_entry(
        id="export_schedule",
        name="导出课表",
        description=("把指定（或当前）学期的课表导出为文本。format=json（默认）|csv|ics。"),
        input_schema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "json/csv/ics"},
                "semester_id": {"type": "integer", "description": "学期 ID，可空"},
            },
        },
    )
    async def export_schedule(self, format: str = "json", semester_id: int = 0, **_):
        sid = int(semester_id or 0)
        if not sid:
            sem = await self.repo.get_active_semester()
            if not sem:
                return Err(SdkError("没有当前学期"))
            sid = sem["id"]
        try:
            norm = await _build_normalized_for_export(self, sid)
        except Exception as exc:
            return Err(SdkError(f"导出失败: {exc}"))
        fmt = (format or "json").lower()
        if fmt == "json":
            text = json.dumps(norm, ensure_ascii=False, indent=2)
        elif fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["weekday", "period_no", "course_name", "teacher", "location", "weeks"])
            for c in norm["courses"]:
                for s in c["sessions"]:
                    weeks = ",".join(str(w) for w in s["weeks"]) if s.get("weeks") else ""
                    w.writerow(
                        [
                            s["weekday"],
                            s["period_no"],
                            c["name"],
                            c.get("teacher") or "",
                            c.get("location") or "",
                            weeks,
                        ]
                    )
            text = buf.getvalue()
        elif fmt == "ics":
            text = _build_ics(norm)
        else:
            return Err(SdkError(f"不支持的 format: {format}"))
        return Ok(
            {
                "format": fmt,
                "semester_id": sid,
                "content": text,
                "size": len(text),
            }
        )


def _build_ics(norm: dict) -> str:
    """把 normalized dict 拼成最简 iCalendar。"""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//N.E.K.O CourseSchedule//EN"]
    # 默认作息起止
    start_map = {
        1: "080000",
        2: "085500",
        3: "100000",
        4: "105500",
        5: "140000",
        6: "145500",
        7: "160000",
        8: "165500",
        9: "190000",
        10: "195500",
        11: "205000",
    }
    end_map = {
        1: "084500",
        2: "094000",
        3: "104500",
        4: "114000",
        5: "144500",
        6: "154000",
        7: "164500",
        8: "174000",
        9: "194500",
        10: "204000",
        11: "213500",
    }
    week_day_abbr = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}

    sem = norm.get("semester") or {}
    (sem.get("start_date") or "2025-09-01")[:4]
    start_yyyymmdd = (sem.get("start_date") or "20250901").replace("-", "")

    for c in norm["courses"]:
        for s in c["sessions"]:
            pno = s["period_no"]
            st = start_map.get(pno, "080000")
            et = end_map.get(pno, "084500")
            byday = week_day_abbr.get(s["weekday"], "MO")
            weeks = s.get("weeks") or list(range(1, 21))
            ",".join(f"BYSETPOS={w}" for w in weeks)
            loc = c.get("location") or ""
            lines += [
                "BEGIN:VEVENT",
                f"DTSTART:{start_yyyymmdd}T{st}",
                f"DTEND:{start_yyyymmdd}T{et}",
                f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
                f"SUMMARY:{c['name']}",
                f"LOCATION:{loc}",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
