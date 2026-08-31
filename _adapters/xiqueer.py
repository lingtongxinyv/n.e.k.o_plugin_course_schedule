"""XiQueEr（喜鹊儿 / 青果教务系统）适配器。

学校教务系统 URL 通常形如 https://jw.hwec.edu.cn/cas/login.action
"""

import asyncio
import base64
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
from typing import Any

from .._academic_adapter import AcademicAdapter, AcademicAdapterError
from .jkingo_des import KingoDES

# ---------------------------------------------------------------------------
# SSL / 请求层：零第三方依赖，全标准库
# ---------------------------------------------------------------------------

_SSL_CTX = ssl._create_unverified_context()

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class _HttpSession:
    """极简封装：用 urllib 模拟 requests.Session 的常用接口。"""

    def __init__(self):
        self.cookie_jar = http.cookiejar.CookieJar()
        # 关键：ProxyHandler({}) 禁用所有代理 + HTTPSHandler 跳过证书
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            urllib.request.HTTPSHandler(context=_SSL_CTX),
        )
        self.last_status: int = 0

    def cookies_get(self, name: str) -> str | None:
        for cookie in self.cookie_jar:
            if cookie.name == name:
                return cookie.value
        return None

    def _request(self, method: str, url: str, headers: dict | None = None,
                 data: bytes | str | None = None, timeout: float = 10.0) -> "_Response":
        hdrs = {**_DEFAULT_HEADERS, **(headers or {})}
        body_bytes: bytes | None = None
        if data is not None:
            body_bytes = data.encode("utf-8") if isinstance(data, str) else data
        req = urllib.request.Request(url, data=body_bytes, headers=hdrs, method=method)
        try:
            resp = self.opener.open(req, timeout=timeout)
            self.last_status = resp.status
            raw = resp.read()
            return _Response(raw, resp.status, dict(resp.headers))
        except urllib.error.HTTPError as e:
            self.last_status = e.code
            raw = e.read() if hasattr(e, "read") else b""
            return _Response(raw, e.code, dict(e.headers) if e.headers else {})
        except urllib.error.URLError as e:
            self.last_status = 0
            reason = getattr(e, "reason", e)
            # 尝试连接看是否是代理/网络问题
            raise AcademicAdapterError(
                f"网络请求失败：{reason}。"
                f" 请检查教务系统地址是否正确、网络是否通畅，"
                f"或尝试关闭系统代理后重试。"
            ) from e
        except Exception as e:
            self.last_status = 0
            raise AcademicAdapterError(f"请求异常：{type(e).__name__}: {e}") from e

    def get(self, url: str, headers: dict | None = None, timeout: float = 10.0) -> "_Response":
        return self._request("GET", url, headers=headers, timeout=timeout)

    def post(self, url: str, data: bytes | str | None = None,
             headers: dict | None = None, timeout: float = 10.0) -> "_Response":
        return self._request("POST", url, data=data, headers=headers, timeout=timeout)


class _Response:
    """模拟 requests.Response 的 .text / .status_code / .json() 接口。"""

    def __init__(self, raw: bytes, status: int, headers: dict):
        self._raw = raw
        self.status_code = status
        self.headers = headers

    @property
    def text(self) -> str:
        try:
            return self._raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return self._raw.decode("gbk")
            except Exception:
                return self._raw.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


def _normalize_base_url(raw: str) -> str:
    """把用户可能输入的各种 URL 形式统一成教务系统根域名 scheme://netloc。"""
    raw = (raw or "").strip()
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        parsed = urllib.parse.urlparse(f"https://{raw}")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


# ---------------------------------------------------------------------------
# XiQueEr 适配器主体
# ---------------------------------------------------------------------------


class XiQueErAdapter(AcademicAdapter):
    """喜鹊儿 / 青果教务系统适配器。

    登录流程（基于 KingoSOFT 青果教务公开算法）：
        GET  /cas/login.action
        GET  /frame/homepage?method=getTempDeskey
        GET  /frame/homepage?method=getTempNowtime
        POST /cas/logon.action  (加密后的 JSON)
    抓课：
        GET  /xskbcx!getKbxxByXs?query.xnxq=...&query.xsh=...&query.kbzc=...
    """

    adapter_id = "xiqueer"
    adapter_name = "喜鹊儿（青果教务）"
    website = "https://jw.hwec.edu.cn"

    def __init__(self, **kwargs):
        # get_adapter("xiqueer", base_url=..., school_code=...) 会把参数透传给 __init__
        self.base_url: str = (kwargs.get("base_url") or "").rstrip("/")
        self._session: _HttpSession | None = None
        self._username: str = ""
        self._semester_keyword: str = ""
        # base_url 先归一化（去掉可能的 /cas/login.action 后缀）
        if self.base_url:
            self.base_url = _normalize_base_url(self.base_url)

    # ---- authenticate ------------------------------------------------------

    async def authenticate(self, creds: dict[str, Any]) -> None:
        # 优先级：creds 里传的 base_url 最优先，其次用 __init__ 里存好的 self.base_url
        raw_base = creds.get("base_url") or creds.get("website") or self.base_url
        self.base_url = _normalize_base_url(raw_base)
        username = (creds.get("username") or creds.get("student_id") or "").strip()
        password = creds.get("password", "")
        md5_password = creds.get("md5_password")

        if not self.base_url:
            raise AcademicAdapterError("缺少 base_url（教务系统地址），如 https://jw.hwec.edu.cn")
        if not username or not password:
            raise AcademicAdapterError("缺少 username 或 password")

        # 宿主超时限制：同步跑，单次 timeout 8s，串行但快速
        loop = asyncio.get_running_loop()
        s, user = await loop.run_in_executor(None, self._do_login_sync, self.base_url, username, password, md5_password)

        self._session = s
        self._username = user

    def _do_login_sync(self, base_url: str, username: str, password: str, md5_password: str | None):
        """同步登录（由 run_in_executor 调用，避免阻塞事件循环）。"""
        T = 8
        s = _HttpSession()

        # 1) 登录页面
        login_page_url = f"{base_url}/cas/login.action"
        r = s.get(login_page_url, timeout=T)
        if r.status_code != 200:
            raise AcademicAdapterError(
                f"无法访问教务系统登录页：HTTP {r.status_code}。"
                f" 地址应为根域名如 https://jw.hwec.edu.cn，"
                f"不要在后面加 /cas/login.action"
            )

        if "凭证已失效" in r.text or "<script>alert('温馨提示" in r.text[:2000]:
            raise AcademicAdapterError(
                "登录页被拦截，返回了错误页面。"
                "请检查网络/校园网环境或关闭系统代理后重试。"
                f" 前200字：{r.text[:200]}"
            )

        jsessionid = s.cookies_get("JSESSIONID")
        if not jsessionid:
            raise AcademicAdapterError(
                f"登录页未返回 JSESSIONID。"
                f" 前200字：{r.text[:200]}"
            )

        session_id = None
        for pat in (
            r'var\s+_sessionid\s*=\s*"([A-Fa-f0-9]+)"',
            r"var\s+_sessionid\s*=\s*'([A-Fa-f0-9]+)'",
            r"var\s+sessionid\s*=\s*['\"]([A-Fa-f0-9]+)['\"]",
            r'_sessionid["\']?\s*[:=]\s*["\']([A-Fa-f0-9]+)["\']',
        ):
            m = re.search(pat, r.text)
            if m:
                session_id = m.group(1)
                break
        if not session_id:
            raise AcademicAdapterError(
                "无法从登录页提取 _sessionid。"
                f" 前300字：{r.text[:300]}"
            )

        # 2) deskey + nowtime — 串行但独立，任一失败都明确报错
        deskey_r = s.get(f"{base_url}/frame/homepage?method=getTempDeskey", timeout=T)
        if deskey_r.status_code != 200 or not deskey_r.text.strip():
            body = deskey_r.text.strip()[:100] if deskey_r.text else "(empty)"
            raise AcademicAdapterError(
                f"获取 deskey 失败（HTTP {deskey_r.status_code}）：{body}"
            )
        deskey = deskey_r.text.strip()
        if "凭证已失效" in deskey:
            raise AcademicAdapterError(
                "deskey 接口返回了错误页面（凭证失效）。"
                "可能是登录页 cookie / session 未正确建立，"
                "请完全退出 N.E.K.O 重启后再试。"
            )

        nowtime_r = s.get(f"{base_url}/frame/homepage?method=getTempNowtime", timeout=T)
        if nowtime_r.status_code != 200 or not nowtime_r.text.strip():
            body = nowtime_r.text.strip()[:100] if nowtime_r.text else "(empty)"
            raise AcademicAdapterError(
                f"获取 nowtime 失败（HTTP {nowtime_r.status_code}）：{body}"
            )
        nowtime = nowtime_r.text.strip()
        if "凭证已失效" in nowtime:
            raise AcademicAdapterError(
                "nowtime 接口返回了错误页面（凭证失效）。"
                "请完全退出 N.E.K.O 重启后再试。"
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

        post_body = (
            f"params={params_v1_encoded}&token={token}&timestamp={nowtime}"
            f"&deskey={deskey}&ssessionid={session_id}"
        )
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": f"{base_url}/cas/login.action",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        r = s.post(f"{base_url}/cas/logon.action", data=post_body, headers=headers, timeout=T)
        try:
            result = r.json()
        except Exception:
            body_snippet = r.text[:500].replace("\n", " ").replace("\r", " ")
            raise AcademicAdapterError(
                f"登录返回非 JSON：{body_snippet}"
            )
        if str(result.get("status")) != "200":
            raise AcademicAdapterError(
                f"登录失败：{result.get('message', '未知错误')} (code={result.get('status')})"
            )

        return s, username

    # ---- fetch_semesters ---------------------------------------------------

    async def fetch_semesters(self) -> list[dict]:
        """喜鹊儿不暴露学期列表接口，这里根据当前日期 + 用户填的 keyword 生成。"""
        from datetime import date
        today = date.today()
        year = today.year

        if 9 <= today.month <= 12:
            sy, ny, term = year, year + 1, "1"
        else:
            sy, ny, term = year - 1, year, "2"

        if term == "1":
            start = date(sy, 9, 1); end = date(ny, 1, 15)
        else:
            start = date(ny, 2, 25); end = date(ny, 7, 15)

        kw = getattr(self, "_semester_keyword", "")
        if kw:
            m = re.search(r"(\d{4})", kw)
            if m:
                ky = int(m.group(1))
                if "秋" in kw:
                    sy, ny, term = ky, ky + 1, "1"
                    start = date(sy, 9, 1); end = date(ny, 1, 15)
                elif "春" in kw:
                    sy, ny, term = ky - 1, ky, "2"
                    start = date(ny, 2, 25); end = date(ny, 7, 15)

        tw = int((end - start).days / 7) + 1
        return [{
            "name": f"{sy}-{ny} 第{'一' if term == '1' else '二'}学期",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "total_weeks": tw,
            "adapter_id": f"{sy}-{term}",
            "school_year": str(sy),
            "term": term,
        }]

    async def select_semester(self, semester_selector: dict) -> None:
        """把 keyword 存到实例上，供 fetch_semesters() 使用。"""
        if semester_selector and semester_selector.get("keyword"):
            self._semester_keyword = semester_selector["keyword"]

    # ---- fetch_courses -----------------------------------------------------

    async def fetch_courses(self, semester_info: dict) -> list[dict]:
        if not self._session:
            raise AcademicAdapterError("未登录，请先 authenticate")

        self._session.cookie_jar.set_cookie(
            http.cookiejar.Cookie(
                version=0, name="USERNAME", value=self._username,
                port=None, port_specified=False, domain="", domain_specified=False,
                domain_initial_dot=False, path="/", path_specified=True,
                secure=False, expires=None, discard=True, comment=None,
                comment_url=None, rest={}, rfc2109=False,
            )
        )
        self._session.cookie_jar.set_cookie(
            http.cookiejar.Cookie(
                version=0, name="weballow", value="true",
                port=None, port_specified=False, domain="", domain_specified=False,
                domain_initial_dot=False, path="/", path_specified=True,
                secure=False, expires=None, discard=True, comment=None,
                comment_url=None, rest={}, rfc2109=False,
            )
        )

        xnxq = semester_info.get("school_year", "") + "-" + semester_info.get("term", "1")
        r = self._session.get(
            f"{self.base_url}/xskbcx!getKbxxByXs?"
            f"query.xnxq={urllib.parse.quote(xnxq)}"
            f"&query.xsh={urllib.parse.quote(self._username)}"
            f"&query.kbzc=jsxx,jc,jc2,cd,zc,dwmc,xnxqm,xsksxm,xsdm,xsm,xxm,xjx,xsks,pym,zb,zs",
            timeout=15,
        )
        if r.status_code != 200:
            raise AcademicAdapterError(f"获取课程失败：HTTP {r.status_code}")
        text = r.text
        if "登录" in text and ("页面" in text or "错误" in text or "失效" in text):
            raise AcademicAdapterError("抓课返回登录页，cookie 可能已失效")

        try:
            raw = r.json()
        except Exception:
            raise AcademicAdapterError(f"抓课返回非 JSON：{text[:200]}")

        return self._parse_course_payload(raw)

    # ---- _parse_course_payload ---------------------------------------------

    def _parse_course_payload(self, payload: Any) -> list[dict]:
        rows: list[dict] = []

        def fmt_period(raw) -> str:
            # 喜鹊儿返回 1-2,3-4 这种区间
            s = str(raw or "").strip()
            m = re.match(r"(\d+)(?:-(\d+))?", s)
            if not m:
                return ""
            return m.group(1)

        def fmt_weeks(raw) -> str:
            """喜鹊儿可能返回 '1-16' 或具体周期数组。"""
            s = str(raw or "").strip()
            if not s:
                return ""
            return s

        def parse_time_range(raw, fallback_weekday: int) -> tuple[int, str, str]:
            # 喜鹊儿返回 { jc: "1-2", jc2: "", kbzc: "1-16" }
            if isinstance(raw, dict):
                jc = raw.get("jc", "") or raw.get("jszc", "")
                jc2 = raw.get("jc2", "") or raw.get("jswk", "")
                wc = raw.get("kbzc", "") or raw.get("jszc2", "")
                weekday = raw.get("jsjm", raw.get("skxq", fallback_weekday))
                return int(weekday), fmt_period(jc), fmt_weeks(wc)
            return fallback_weekday, fmt_period(raw), ""

        def walk(obj, title_hint=None, fallback_weekday=1):
            if isinstance(obj, list):
                for item in obj:
                    walk(item, title_hint, fallback_weekday)
            elif isinstance(obj, dict):
                title = obj.get("xsm", obj.get("xxm", obj.get("kcname", obj.get("title", title_hint))))
                teacher = obj.get("zpm", obj.get("jsm", obj.get("teacher", obj.get("zprs", ""))))
                location = obj.get("cdmc", obj.get("cd", obj.get("location", "")))

                # 喜鹊儿把时间/周期塞在 kbArr 数组里（每格含 jc、kbzc、jsjm 等字段）
                if "kbArr" in obj and isinstance(obj["kbArr"], list):
                    for cell in obj["kbArr"]:
                        if not isinstance(cell, dict):
                            continue
                        jc = cell.get("jc", "")
                        jc2 = cell.get("jc2", "") or ""
                        wc = cell.get("kbzc", "")
                        weekday = int(cell.get("jsjm", cell.get("skxq", fallback_weekday)))
                        periods = fmt_period(jc2) or fmt_period(jc)
                        if not title or not periods:
                            continue
                        rows.append({
                            "title": str(title).strip(),
                            "teacher": str(teacher).strip() if teacher else "",
                            "location": str(location).strip() if location else "",
                            "periods": periods,
                            "weeks": fmt_weeks(wc),
                            "weekday": weekday,
                        })

                # 或者直接在顶层 dict 有 jc / kbzc 字段（扁平结构）
                elif "jc" in obj and "kbzc" in obj and title:
                    jc_val = obj.get("jc", "")
                    wc_val = obj.get("kbzc", "")
                    weekday = int(obj.get("jsjm", obj.get("skxq", fallback_weekday)))
                    if jc_val and "kbzc" in obj:
                        rows.append({
                            "title": str(title).strip(),
                            "teacher": str(teacher).strip() if teacher else "",
                            "location": str(location).strip() if location else "",
                            "periods": fmt_period(jc_val),
                            "weeks": fmt_weeks(wc_val),
                            "weekday": weekday,
                        })
                    else:
                        walk(obj.get("children", obj.get("siblings", [])), title, weekday)
                else:
                    for v in obj.values():
                        walk(v, title, fallback_weekday)

        walk(payload)

        # 去重（同课程+同星期+同节次）
        seen = set()
        unique: list[dict] = []
        for row in rows:
            key = (row["title"], row["weekday"], row["periods"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

