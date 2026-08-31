"""课程表数据访问层。"""

from __future__ import annotations

from plugin.sdk.plugin import unwrap

from ._schema import DEFAULT_PERIOD_TIMES, ensure_schema, parse_weeks, weeks_to_json
from ._time import active_in_week, week_number, weekday_of


class ScheduleRepo:
    def __init__(self, plugin):
        self.plugin = plugin

    @property
    def db(self):
        return self.plugin.db

    async def _session(self):
        return unwrap(await self.db.session())

    async def ensure_schema(self) -> None:
        async with await self._session() as session:
            await ensure_schema(session)

    # ── 学期 ──
    async def list_semesters(self) -> list[dict]:
        async with await self._session() as session:
            cur = await session.execute("SELECT * FROM semesters ORDER BY id DESC")
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    async def get_active_semester(self) -> dict | None:
        async with await self._session() as session:
            cur = await session.execute("SELECT * FROM semesters WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
        return dict(row) if row else None

    async def add_semester(self, *, name, start_date, end_date, total_weeks, activate=True) -> dict:
        async with await self._session() as session:
            if activate:
                await session.execute("UPDATE semesters SET is_active = 0")
            cur = await session.execute(
                "INSERT INTO semesters (name, start_date, end_date, total_weeks, is_active) VALUES (?, ?, ?, ?, ?)",
                (name, str(start_date), str(end_date), int(total_weeks), 1 if activate else 0),
            )
            sid = cur.lastrowid
            for pno, st, et, slot in DEFAULT_PERIOD_TIMES:
                await session.execute(
                    "INSERT OR IGNORE INTO period_times (semester_id, period_no, start_time, end_time, slot) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (sid, pno, st, et, slot),
                )
            await session.commit()
        return {
            "id": sid,
            "name": name,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_weeks": int(total_weeks),
            "is_active": activate,
        }

    async def activate_semester(self, semester_id: int) -> bool:
        async with await self._session() as session:
            cur = await session.execute("SELECT 1 FROM semesters WHERE id = ?", (int(semester_id),))
            if cur.fetchone() is None:
                return False
            await session.execute("UPDATE semesters SET is_active = 0")
            await session.execute("UPDATE semesters SET is_active = 1 WHERE id = ?", (int(semester_id),))
            await session.commit()
        return True

    # ── 节次作息 ──
    async def get_period_times(self, semester_id: int) -> dict:
        async with await self._session() as session:
            cur = await session.execute(
                "SELECT period_no, start_time, end_time, slot FROM period_times "
                "WHERE semester_id = ? ORDER BY period_no",
                (int(semester_id),),
            )
            rows = cur.fetchall()
        return {
            r["period_no"]: {"start_time": r["start_time"], "end_time": r["end_time"], "slot": r["slot"]} for r in rows
        }

    async def set_period_times(self, semester_id: int, periods: list[dict]) -> int:
        async with await self._session() as session:
            await session.execute("DELETE FROM period_times WHERE semester_id = ?", (int(semester_id),))
            for p in periods:
                await session.execute(
                    "INSERT INTO period_times (semester_id, period_no, start_time, end_time, slot) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        int(semester_id),
                        int(p["period_no"]),
                        str(p["start_time"]),
                        str(p["end_time"]),
                        p.get("slot") or "morning",
                    ),
                )
            await session.commit()
        return len(periods)

    # ── 课程 ──
    async def add_course(
        self, *, semester_id, name, code=None, teacher=None, location=None, color=None, note=None
    ) -> dict:
        async with await self._session() as session:
            cur = await session.execute(
                "INSERT INTO courses (semester_id, name, code, teacher, location, color, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(semester_id), name, code, teacher, location, color, note),
            )
            cid = cur.lastrowid
            await session.commit()
        return {
            "id": cid,
            "semester_id": int(semester_id),
            "name": name,
            "code": code,
            "teacher": teacher,
            "location": location,
            "color": color,
            "note": note,
        }

    async def list_courses(self, semester_id: int) -> list[dict]:
        async with await self._session() as session:
            cur = await session.execute("SELECT * FROM courses WHERE semester_id = ? ORDER BY id", (int(semester_id),))
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    async def get_course(self, course_id: int) -> dict | None:
        async with await self._session() as session:
            cur = await session.execute("SELECT * FROM courses WHERE id = ?", (int(course_id),))
            row = cur.fetchone()
        return dict(row) if row else None

    # ── 上课安排 ──
    async def add_session(self, *, course_id, weekday, period_no, weeks=None, note=None) -> dict:
        wj = weeks_to_json(weeks)
        async with await self._session() as session:
            cur = await session.execute(
                "INSERT INTO course_sessions (course_id, weekday, period_no, weeks, note) VALUES (?, ?, ?, ?, ?)",
                (int(course_id), int(weekday), int(period_no), wj, note),
            )
            sid = cur.lastrowid
            await session.commit()
        return {
            "id": sid,
            "course_id": int(course_id),
            "weekday": int(weekday),
            "period_no": int(period_no),
            "weeks": parse_weeks(wj),
            "note": note,
        }

    # ── 例外 ──
    async def add_exception(
        self, *, semester_id, course_id=None, title=None, date, kind, period_no=None, location=None, note=None
    ) -> dict:
        async with await self._session() as session:
            cur = await session.execute(
                "INSERT INTO exceptions (semester_id, course_id, title, date, kind, period_no, location, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (int(semester_id), course_id, title, str(date), kind, period_no, location, note),
            )
            eid = cur.lastrowid
            await session.commit()
        return {
            "id": eid,
            "semester_id": int(semester_id),
            "course_id": course_id,
            "title": title,
            "date": str(date),
            "kind": kind,
            "period_no": period_no,
            "location": location,
            "note": note,
        }

    async def list_exceptions(self, semester_id: int, date_str: str | None = None) -> list[dict]:
        async with await self._session() as session:
            if date_str:
                cur = await session.execute(
                    "SELECT * FROM exceptions WHERE semester_id = ? AND date = ? ORDER BY period_no",
                    (int(semester_id), date_str),
                )
            else:
                cur = await session.execute(
                    "SELECT * FROM exceptions WHERE semester_id = ? ORDER BY date, period_no",
                    (int(semester_id),),
                )
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    # ── 核心：某天的课程（周重复 + 例外叠加） ──
    async def resolve_sessions_for_date(self, semester: dict, d) -> list[dict]:
        sid = semester["id"]
        wd = weekday_of(d)
        wn = week_number(semester, d)
        if wn is None:
            return []
        sessions: list[dict] = []
        async with await self._session() as session:
            cur = await session.execute(
                "SELECT cs.id, cs.course_id, cs.weekday, cs.period_no, cs.note, cs.weeks, "
                "c.name AS name, c.teacher, c.location, c.color "
                "FROM course_sessions cs JOIN courses c ON c.id = cs.course_id "
                "WHERE c.semester_id = ? AND cs.weekday = ? ORDER BY cs.period_no",
                (sid, wd),
            )
            for r in cur.fetchall():
                if active_in_week(parse_weeks(r["weeks"]), wn):
                    sessions.append(dict(r))
            cur = await session.execute(
                "SELECT * FROM exceptions WHERE semester_id = ? AND date = ? ORDER BY period_no",
                (sid, d.isoformat()),
            )
            excs = [dict(r) for r in cur.fetchall()]
        # 取消
        cancel_keys = {
            (e["course_id"], e["period_no"])
            for e in excs
            if e["kind"] == "cancel" and e["period_no"] is not None and e["course_id"] is not None
        }
        sessions = [s for s in sessions if (s["course_id"], s["period_no"]) not in cancel_keys]
        # 新增
        for e in excs:
            if e["kind"] != "add" or e["period_no"] is None:
                continue
            name = e.get("title")
            loc = e.get("location")
            teacher = None
            color = None
            if e.get("course_id"):
                course = await self.get_course(e["course_id"])
                if course:
                    name = name or course["name"]
                    loc = loc or course.get("location")
                    teacher = course.get("teacher")
                    color = course.get("color")
            sessions.append(
                {
                    "course_id": e.get("course_id"),
                    "period_no": e["period_no"],
                    "name": name or "临时安排",
                    "location": loc,
                    "teacher": teacher,
                    "color": color,
                    "note": e.get("note"),
                    "exception_id": e["id"],
                }
            )
        sessions.sort(key=lambda x: x.get("period_no") or 0)
        return sessions

    # ── 作业 / 考试 ──
    async def add_assignment(
        self, *, semester_id, kind, title, course_id=None, due_at=None, location=None, note=None
    ) -> dict:
        async with await self._session() as session:
            cur = await session.execute(
                "INSERT INTO assignments (semester_id, course_id, kind, title, due_at, location, note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(semester_id), course_id, kind, title, due_at, location, note),
            )
            aid = cur.lastrowid
            await session.commit()
        return {
            "id": aid,
            "semester_id": int(semester_id),
            "course_id": course_id,
            "kind": kind,
            "title": title,
            "due_at": due_at,
            "location": location,
            "note": note,
            "done": 0,
        }

    async def list_assignments(self, *, semester_id, kind=None, status=None, course_id=None, limit=100) -> list[dict]:
        sql = (
            "SELECT a.*, c.name AS course_name "
            "FROM assignments a LEFT JOIN courses c ON c.id = a.course_id "
            "WHERE a.semester_id = ?"
        )
        params: list = [int(semester_id)]
        if kind:
            sql += " AND a.kind = ?"
            params.append(kind)
        if course_id:
            sql += " AND a.course_id = ?"
            params.append(int(course_id))
        if status == "pending":
            sql += " AND a.done = 0"
        elif status == "done":
            sql += " AND a.done = 1"
        sql += " ORDER BY a.due_at IS NULL, a.due_at, a.id DESC LIMIT ?"
        params.append(int(limit))
        async with await self._session() as session:
            cur = await session.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]

    async def update_assignment(self, assignment_id: int, **fields) -> dict | None:
        allowed = {"title", "due_at", "location", "note", "done", "course_id"}
        sets = [f"{k} = ?" for k in fields if k in allowed]
        vals = [v for k, v in fields.items() if k in allowed]
        if not sets:
            return None
        vals.append(int(assignment_id))
        async with await self._session() as session:
            await session.execute(
                f"UPDATE assignments SET {', '.join(sets)} WHERE id = ?",
                vals,
            )
            await session.commit()
            cur = await session.execute(
                "SELECT a.*, c.name AS course_name "
                "FROM assignments a LEFT JOIN courses c ON c.id = a.course_id "
                "WHERE a.id = ?",
                (int(assignment_id),),
            )
            row = cur.fetchone()
        return dict(row) if row else None

    async def delete_assignment(self, assignment_id: int) -> bool:
        async with await self._session() as session:
            cur = await session.execute(
                "DELETE FROM assignments WHERE id = ?",
                (int(assignment_id),),
            )
            await session.commit()
        return cur.rowcount > 0

    async def get_upcoming_assignments(self, *, semester_id, kind=None, limit=10) -> list[dict]:
        sql = (
            "SELECT a.*, c.name AS course_name "
            "FROM assignments a LEFT JOIN courses c ON c.id = a.course_id "
            "WHERE a.semester_id = ? AND a.done = 0 AND a.due_at IS NOT NULL "
            "AND a.due_at >= date('now')"
        )
        params: list = [int(semester_id)]
        if kind:
            sql += " AND a.kind = ?"
            params.append(kind)
        sql += " ORDER BY a.due_at LIMIT ?"
        params.append(int(limit))
        async with await self._session() as session:
            cur = await session.execute(sql, params)
            rows = cur.fetchall()
        return [dict(r) for r in rows]
