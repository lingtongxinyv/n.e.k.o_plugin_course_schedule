"""喜鹊儿 / 青果教务系统适配器。

登录流程参考 XiQueEr2Ics 项目逆向成果：
  GET  /cas/login.action                   → 拿 JSESSIONID + _sessionid
  GET  /frame/homepage?method=getTempDeskey → 拿 deskey
  GET  /frame/homepage?method=getTempNowtime → 拿 nowtime
  POST /cas/logon.action                    → 提交加密后的登录参数

课表获取：
  GET /student/wsxk.xskcb10319.jsp?params=base64(xn+"+"+xq+"+"+xh)
  → 解析 table#mytable → 返回课程列表

零第三方依赖：requests + 内置 jkingo_des + 正则解析 HTML。
"""
from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

from .._academic_adapter import AcademicAdapter, AcademicAdapterError
from .jkingo_des import KingoDES

# 一些已知青果/喜鹊儿教务系统的 base_url（用户也可以直接传）
# 可从 https://github.com/shutdown-awa/XiQueEr2Ics 持续扩展
SCHOOL_PRESETS: dict[str, dict[str, str]] = {
    "12623": {"title": "华南农业大学珠江学院", "base_url": "http://202.103.141.242:801"},
}


class XiQueErAdapter(AcademicAdapter):
    """喜鹊儿 / 青果教务系统适配器。"""

    adapter_id = "xiqueer"
    adapter_name = "喜鹊儿（青果教务）"

    def __init__(self, base_url: str = "", school_code: str = "", **kwargs):
        super().__init__(**kwargs)
        self.base_url = (base_url or "").rstrip("/")
        self.school_code = school_code.strip()
        if not self.base_url and self.school_code and self.school_code in SCHOOL_PRESETS:
            self.base_url = SCHOOL_PRESETS[self.school_code]["base_url"]
        self._session = None
        self._jsessionid = None
        self._user_code: str | None = None

    # ── 认证 ──

    async def authenticate(self, creds: dict[str, Any]) -> None:
        import requests as _requests  # 宿主应该已装

        username = str(creds.get("username") or "").strip()
        password = str(creds.get("password") or "").strip()
        md5_password = str(creds.get("md5_password") or "").strip()  # 可选：用户直接给 MD5
        if not self.base_url:
            raise AcademicAdapterError("缺少 base_url 或未识别的 school_code，请提供教务系统地址")
        if not username or not password:
            raise AcademicAdapterError("缺少 username 或 password")

        # 用 requests 同步调，再用 asyncio.to_thread 包装（entry point 是 async 的）
        import asyncio as _asyncio

        def _do_login():
            s = _requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })

            # 1) 登录页面
            login_page_url = f"{self.base_url}/cas/login.action"
            r = s.get(login_page_url, timeout=10)
            if r.status_code != 200:
                raise AcademicAdapterError(f"无法访问教务系统登录页：HTTP {r.status_code}（{login_page_url}）")
            jsessionid = s.cookies.get("JSESSIONID")
            if not jsessionid:
                raise AcademicAdapterError(
                    "登录页未返回 JSESSIONID。"
                    f" 登录页内容前200字：{r.text[:200]}"
                )

            # 尝试多种正则匹配 _sessionid（不同学校登录页格式略有差异）
            session_id = None
            session_id_patterns = [
                r'var\s+_sessionid\s*=\s*"([A-Fa-f0-9]+)"',       # 标准大写 hex
                r"var\s+_sessionid\s*=\s*'([A-Fa-f0-9]+)'",       # 单引号版本
                r"var\s+sessionid\s*=\s*['\"]([A-Fa-f0-9]+)['\"]",  # 变量名无下划线
                r'_sessionid["\']?\s*[:=]\s*["\']([A-Fa-f0-9]+)["\']',  # JSON/对象属性风格
            ]
            for pat in session_id_patterns:
                m = re.search(pat, r.text)
                if m:
                    session_id = m.group(1)
                    break

            if not session_id:
                raise AcademicAdapterError(
                    "无法从登录页提取 _sessionid（学校教务系统登录页格式可能不同）。"
                    f" 登录页前300字：{r.text[:300]}"
                )

            # 2) 动态参数
            deskey = s.get(f"{self.base_url}/frame/homepage?method=getTempDeskey", timeout=10).text.strip()
            nowtime = s.get(f"{self.base_url}/frame/homepage?method=getTempNowtime", timeout=10).text.strip()
            if not deskey or not nowtime:
                raise AcademicAdapterError(
                    "获取 deskey/nowtime 失败，教务系统可能不可用或需要额外参数。"
                    f" deskey={deskey[:50] if deskey else '(空)'}, nowtime={nowtime[:50] if nowtime else '(空)'}"
                )

            # 3) 组装登录参数
            params_u = base64.b64encode(f"{username};;{session_id}".encode()).decode()
            real_pwd = md5_password or hashlib.md5(password.encode("utf-8")).hexdigest()
            params_p = hashlib.md5((real_pwd + hashlib.md5(b"").hexdigest()).encode("utf-8")).hexdigest()

            params_v1 = (
                f"_u={params_u}&_p={params_p}&randnumber=&isPasswordPolicy=1&"
                "txt_mm_expression=14&txt_mm_length=15&txt_mm_userzh=0&"
                "hid_flag=1&hidlag=1&hid_dxyzm="
            )
            token = hashlib.md5(
                (hashlib.md5(params_v1.encode()).hexdigest() + hashlib.md5(nowtime.encode()).hexdigest()).encode()
            ).hexdigest()
            params_v1_encoded = KingoDES.encrypt(params_v1, deskey)

            post_body = f"params={params_v1_encoded}&token={token}&timestamp={nowtime}&deskey={deskey}&ssessionid={session_id}"
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{self.base_url}/cas/login.action",
                "Cookie": f"JSESSIONID={jsessionid}",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
            }
            r = s.post(f"{self.base_url}/cas/logon.action", data=post_body, headers=headers, timeout=10)
            try:
                result = r.json()
            except Exception:
                # 服务器返回了 HTML 而非 JSON —— 通常意味着 session/token 失效
                body_snippet = r.text[:500].replace("\n", " ").replace("\r", " ")
                raise AcademicAdapterError(
                    f"登录返回非 JSON（服务器返回了 HTML/脚本）。"
                    f" 登录凭证 session/deskey 可能已失效或与该教务系统版本不兼容。"
                    f" 服务器响应前500字：{body_snippet}"
                )
            if str(result.get("status")) != "200":
                raise AcademicAdapterError(
                    f"登录失败：{result.get('message', '未知错误')} "
                    f"(code={result.get('status')})"
                )

            return s, username

        self._session, self._user_code = await _asyncio.to_thread(_do_login)
        self._jsessionid = self._session.cookies.get("JSESSIONID")
        self._authenticated = True

    # ── 学期列表 ──

    async def fetch_semesters(self) -> list[dict]:
        """喜鹊儿不暴露学期列表接口，这里根据当前日期生成几个合理候选。"""
        from datetime import date
        today = date.today()
        year = today.year
        # 9月起=上学期(1)，2月起=下学期(2)
        term = "1" if 9 <= today.month <= 12 else "2"
        return [
            {"name": f"{year}-{year + 1} 第{('一' if term == '1' else '二')}学期",
             "adapter_id": f"{year}-{term}", "school_year": str(year), "term": term},
        ]

    # ── 课程 ──

    async def fetch_courses(self, semester: dict) -> list[dict]:
        import asyncio as _asyncio

        school_year = semester.get("school_year") or (semester.get("adapter_id") or "-").split("-")[0]
        term = semester.get("term") or (semester.get("adapter_id") or "-").split("-")[-1]
        user_code = self._user_code or semester.get("user_code")
        if not user_code:
            raise AcademicAdapterError("未登录，没有 user_code")

        def _do_fetch():
            assert self._session and self._jsessionid
            params_raw = f"xn={school_year}&xq={term}&xh={user_code}"
            params_b64 = base64.b64encode(params_raw.encode()).decode()
            url = f"{self.base_url}/student/wsxk.xskcb10319.jsp?params={params_b64}"
            headers = {
                "Referer": f"{self.base_url}/student/xkjg.wdkb.jsp?menucode=S20301",
                "Cookie": f"JSESSIONID={self._jsessionid}",
            }
            r = self._session.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                raise AcademicAdapterError(f"课表请求失败：HTTP {r.status_code}")
            return r.text

        html = await _asyncio.to_thread(_do_fetch)
        return _parse_xiqueer_html(html)


def _parse_xiqueer_html(html: str) -> list[dict]:
    """解析喜鹊儿课表 HTML（零 bs4 依赖，用正则）。

    喜鹊儿 HTML 结构（table#mytable）：
      <td class="td">...
        <div style="padding-bottom:5px;clear:both;">
          <font style="font-weight: bolder">课名</font><br>
          教师:xxx<br>
          教学周次[节次]<br>
          地点<br>
        </div>
    """
    # 找到 mytable 的内容
    m = re.search(r'<table[^>]*id="mytable"[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    table_html = m.group(1)

    # 提取所有 td.td（前 7 个对应当周一到周日）
    # 简化：按行 split，每行取 7 个 td，跳过第一行（标题）
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
    courses_raw: list[tuple[int, str]] = []  # (weekday 1-7, course_div_text)
    for row_html in rows[1:]:  # 跳过标题行
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
        for i in range(min(7, len(tds))):
            td_html = tds[i]
            # 找所有 padding-bottom div
            for dm in re.finditer(
                r'<div\s+style="padding-bottom:5px;clear:both;"[^>]*>(.*?)</div>',
                td_html, re.DOTALL | re.IGNORECASE,
            ):
                courses_raw.append((i + 1, dm.group(1)))

    # 聚合同名课程的 sessions
    courses_map: dict[str, dict] = {}
    for weekday, div_html in courses_raw:
        lines = [ln.strip() for ln in re.split(r'<br\s*/?>', div_html, flags=re.IGNORECASE)]
        # 去掉 HTML 标签
        lines = [re.sub(r'<[^>]+>', '', ln).strip() for ln in lines]
        lines = [ln for ln in lines if ln]
        if not lines:
            continue
        # font 加粗标签内容是课名
        title_m = re.search(r'<font[^>]*font-weight:\s*bolder[^>]*>(.*?)</font>', div_html, re.IGNORECASE | re.DOTALL)
        title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip() if title_m else (lines[0] if lines else "")
        if not title:
            continue

        teacher = ""
        teaching_weeks_str = ""
        class_periods_str = ""
        location = ""
        for ln in lines[1:]:
            if ln.startswith("教师:") or ln.startswith("教师："):
                teacher = ln.replace("教师:", "").replace("教师：", "").strip()
            elif "[" in ln and "]" in ln:
                teaching_weeks_str, _, class_periods_str = ln.partition("[")
                teaching_weeks_str = teaching_weeks_str.strip()
                class_periods_str = class_periods_str.replace("]", "").strip()
            elif teaching_weeks_str or class_periods_str:
                location = ln

        if not teaching_weeks_str or not class_periods_str:
            continue

        # 解析周次 / 节次
        weeks = _parse_weeks(teaching_weeks_str)
        periods = _parse_periods(class_periods_str)
        if not weeks or not periods:
            continue

        course = courses_map.setdefault(title, {
            "name": title, "teacher": teacher or None, "location": location or None,
            "code": None, "note": None, "sessions": [],
        })
        for pno in periods:
            # 同课程同 weekday 同 period 去重
            already = {(s["weekday"], s["period_no"]) for s in course["sessions"]}
            if (weekday, pno) not in already:
                course["sessions"].append({"weekday": weekday, "period_no": pno, "weeks": weeks})

    return list(courses_map.values())


def _parse_weeks(s: str) -> list[int] | None:
    """解析 "1-8周" / "1-16" / "单周1-15" 等。返回 None=每周上。"""
    if not s:
        return None
    is_odd = "单" in s
    is_even = "双" in s
    clean = s.replace("单", "").replace("双", "").replace("周", "").strip()
    nums: list[int] = []
    for part in re.split(r"[，,、\s]+", clean):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~到至]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            nums.extend(range(min(a, b), max(a, b) + 1))
        else:
            try:
                nums.append(int(part))
            except ValueError:
                continue
    if is_odd:
        nums = [w for w in nums if w % 2 == 1]
    elif is_even:
        nums = [w for w in nums if w % 2 == 0]
    nums = sorted(set(nums))
    return nums if nums else None


def _parse_periods(s: str) -> list[int]:
    """解析 "1-2" / "3" / "5-6,7"。"""
    out: list[int] = []
    for part in re.split(r"[，,、\s]+", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-~到至]\s*(\d+)$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            out.extend(range(min(a, b), max(a, b) + 1))
        else:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return sorted(set(out))
