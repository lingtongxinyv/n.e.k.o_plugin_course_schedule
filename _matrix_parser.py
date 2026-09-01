"""从二维矩阵直接解析「周课表网格」+「详细课表列表」。

替代 parse_table_paste 的文本正则方案，利用矩阵的行/列结构语义：
  - 周课表网格：行 = 时间片（节次），列 = 星期几
  - 详细列表：扁平表格，每一行 = 一门课

两种格式输出统一的 normalized courses dict。

v2 重构：锚点驱动解析
  - 先用 "XX周" 锚定周次块（必须以"周"结尾，每段数字 ≤ 2 位）
  - 周次块后括号 = 节次锚点
  - 锚点之间的文本块 = [课程名+教师+地点]
  - 右切 teacher（2-4 字中文），左定位 location（楼/教/馆/室...）
  - 解决了 v1 的致命 bug：教室号尾数字 + 周次粘连被误判为周次块
"""

from __future__ import annotations

import re

# ── 常量 ──────────────────────────────────────────────

_WD_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "日": 7, "天": 7,
}

# 课程代码前缀：[XXX] 或 (XXX) 或 【XXX】
_CODE_PREFIX_RE = re.compile(r"^\s*[\(\[【]\s*[A-Za-z0-9\-:]*\s*[\)\]】]\s*")

# 周次锚点：必须以 "周" 结尾，每段数字 ≤ 2 位
# 例: 1-14周, 1,3,5周, 1-9,11-16周
_WEEK_RE = re.compile(
    r"(\d{1,2}(?:[-~到至]\d{1,2})*(?:[,，]\s*\d{1,2}(?:[-~到至]\d{1,2})*)*)周"
)

# 节次锚点：在任何括号里的 1-2 位数字范围
# 例: (1-2), [3-4], （5-6）
_PERIOD_BRACKET_RE = re.compile(
    r"[(\[【]\s*(\d{1,2}(?:[-~到至]\d{1,2})*(?:[,，]\s*\d{1,2}(?:[-~到至]\d{1,2})*)*)\s*[)\]】]"
)

# location 关键词：必须用列表，多字关键词优先匹配
# 长度 ≥ 2 的是复合关键词，单个字符的是兜底
_LOC_KEYWORDS: list[str] = [
    # 复合关键词（优先匹配）
    "体育中心", "实验实训", "实训中心", "教学楼", "实验楼", "办公楼",
    "图书馆", "体育馆", "体育场", "训练馆", "活动中心", "校区", "中心大楼",
    "机电楼", "教学生活",
    # 常见双字/三字关键词
    "体育", "训练", "体育馆", "体育场",
    # 单字兜底（最后匹配）
    "楼", "栋", "教", "馆", "室", "场", "厅", "院",
]
_LOC_HINT_CHARS = set("楼栋教馆室场厅院")  # 用于简单检查

# location 单字正则（用于快速匹配 hint 位置）
_LOC_TOKEN_RE = re.compile(
    r"([" + "".join(set("".join(_LOC_KEYWORDS))) + r"]{1,6})"
    r"([A-Za-z0-9\-]{0,10})"
)

# 常见课程名结尾词（用于判断切分点是否合理）
_COURSE_SUFFIXES = (
    "技术", "原理", "基础", "设计", "控制", "网络", "编程", "方法",
    "理论", "系统", "信息", "工程", "应用", "实验", "实训", "课程",
    "概论", "导论", "分析", "综合", "集成", "数学", "物理", "化学",
    "英语", "语文", "体育", "健康", "教育", "哲学", "政治", "经济",
    "管理", "心理", "法律", "历史", "地理",
)


# ── 紧急垃圾过滤（在 _add_session 入口处拦截） ──

_GARBAGE_LOC_KEYWORDS = set("楼栋教馆室场厅院楼训练实训实验教学楼办公楼图书馆体育馆体育场机房")
_COURSE_NAME_HINTS = (
    "原理", "技术", "基础", "设计", "控制", "网络", "编程", "方法",
    "理论", "系统", "信息", "工程", "应用", "实验", "实训", "课程",
    "概论", "导论", "分析", "综合", "集成", "数学", "物理", "化学",
    "英语", "体育", "健康", "教育", "哲学", "政治", "经济", "形势",
    "管理", "心理", "法律", "历史", "地理", "建模", "计算", "接口",
    "单片", "智能", "机械", "电子", "数据", "大学", "高等", "线性",
    "离散", "程序", "三维", "概论", "新时代", "特色社会主义",
)


def _is_likely_garbage_name(name: str) -> bool:
    """判断 name 是否很可能是垃圾（节次范围、纯地点、纯人名、残缺片段）。
    返回 True 表示应该丢弃。
    """
    name = name.strip()
    if not name:
        return True

    # ── Category A: 节次/周次范围（纯数字和符号） ──
    if re.match(r"^\s*\d[\d\-~到至,\[\]\(\)【】、\s]*\s*$", name):
        return True
    if re.search(r"\d+\s*[-~到至,]\s*\d+\s*周", name):
        return True

    # ── Category B: location（优先级最高） ──
    # B1: 含 location hint + ASCII 数字后缀 → 100% location（如 "实验楼509"、"301-PLC"）
    _LOC_HINTS_FOR_SUFFIX = ("楼", "馆", "室", "场", "厅", "院", "机房")
    has_loc_hint = any(h in name for h in _LOC_HINTS_FOR_SUFFIX)
    has_num_suffix = bool(re.search(r"\d+[A-Za-z\-]*$", name))
    if has_loc_hint and has_num_suffix:
        return True

    # B2: 纯 location 关键词（name 等于或以它们结尾）
    _PURE_LOC_KWS = (
        "实训室", "实训中心", "体育馆", "体育场", "训练馆", "活动中心",
        "体育中心", "教学楼", "实验楼", "办公楼", "图书馆", "合教楼",
        "机电楼", "实验实训", "中心大楼", "机房",
        "PLC", "-PLC",
    )
    if name in _PURE_LOC_KWS:
        return True
    # 或以它们结尾（如 "综合工程实训室"）
    for kw in _PURE_LOC_KWS:
        if name.endswith(kw) and len(name) >= len(kw):
            return True

    # B3: 含 "-PLC" 结尾或独立 PLC → location 后缀
    if ("-PLC" in name or name.endswith("PLC")):
        return True

    # B4: 纯 location（3字以下+location hint字 → 人名也不会带 location 字）
    if len(name) <= 3 and has_loc_hint:
        return True

    # B5: 含 location hint 字 + 括号残缺（如 "电)机房"、"综合(机)"）
    if has_loc_hint and re.search(r"[\(（\)\）]", name):
        return True

    # B6: 纯 ASCII location 编号（如 "A201"、"B-105"、"301-PLC"）
    if re.match(r"^[A-Za-z0-9\-]{2,8}$", name) and re.search(r"\d", name):
        return True

    # ── Category C: 残缺片段 / 人名 ──
    # 2字及以下 → 残缺
    if len(name) <= 2:
        return True

    # 3字 + 不含任何课程关键词 → 大概率人名
    _COURSE_KW = (
        "原理", "技术", "基础", "设计", "控制", "网络", "编程", "方法",
        "理论", "系统", "信息", "工程", "应用", "实验", "实训", "课程",
        "概论", "导论", "分析", "综合", "集成", "数学", "物理", "化学",
        "英语", "体育", "健康", "教育", "哲学", "政治", "经济", "形势",
        "管理", "心理", "法律", "历史", "地理", "建模", "计算", "接口",
        "单片", "智能", "机械", "电子", "数据", "大学", "高等", "线性",
        "离散", "程序", "三维", "新时代", "特色社会主义", "马克思",
        "毛泽东", "邓小平", "中国特色",
    )
    if len(name) <= 3 and not any(k in name for k in _COURSE_KW):
        return True

    # 含孤立括号片段（如 "(机)"、"综合(机)"）
    if re.search(r"[\(（]\s*[\u4e00-\u9fff]\s*[\)）]", name) and len(name) <= 6:
        return True

    return False




def _clean_name(raw: str) -> str:
    s = raw.strip()
    s = _CODE_PREFIX_RE.sub("", s)
    # 去掉尾部的 (课序号) 标记 —— 课程名里常带 (12) 这样的课序号
    s = re.sub(r"\s*[\(\（\[【]\d+[\)\）\]】]\s*$", "", s)
    # 去掉尾部孤立的 location 痕迹（课程名不会以"教/楼/馆"结尾）
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_location(loc: str) -> str | None:
    loc = loc.strip()
    if not loc:
        return None
    loc = re.sub(r"第\s*\d+\s*节?", "", loc).strip()
    loc = re.sub(r"[(\[【（】\)\]\s]", "", loc)
    loc = re.sub(r"\s+", "", loc)
    return loc or None


def _parse_weeks(text: str) -> list[int] | None:
    """'1-14,17-18' → [1..14, 17, 18]"""
    if not text:
        return None
    nums: list[int] = []
    text = re.sub(r"\s+", "", text)
    for part in text.split(","):
        if not part:
            continue
        m = re.match(r"^(\d{1,2})\s*[-~到至]\s*(\d{1,2})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            lo, hi = min(a, b), max(a, b)
            # 合理校验：学期不会超过 30 周
            if lo >= 1 and hi <= 30:
                nums.extend(range(lo, hi + 1))
        elif re.match(r"^\d{1,2}$", part):
            n = int(part)
            if 1 <= n <= 30:
                nums.append(n)
    return nums or None


def _parse_periods(text: str) -> list[int] | None:
    """'1-2' → [1,2]"""
    if not text:
        return None
    text = text.strip(" \t[]【】()（）")
    nums: list[int] = []
    for part in re.split(r"[,\s]+", text):
        if not part:
            continue
        m = re.match(r"^(\d{1,2})\s*[-~到至]\s*(\d{1,2})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            nums.extend(range(min(a, b), max(a, b) + 1))
        elif re.match(r"^\d{1,2}$", part):
            nums.append(int(part))
    return nums or None


def _extract_bracket_periods(text: str) -> list[int] | None:
    """从含周次+节次的字符串提取节次号。
    '1-14,17-18[1-2]' → [1,2]
    '5-8[1-2]' → [1,2]
    多个括号时合并。
    """
    if not text:
        return None
    periods: list[int] = []
    # 匹配 [...] 或 （...） 里的内容
    for m in re.finditer(r"[\[【\(（]([\d\s,，\-~到至]+)[\]】\)）]", text):
        inner = m.group(1)
        parsed = _parse_periods(inner)
        if parsed:
            periods.extend(parsed)
    # 同时匹配纯时间范围 → 节次
    # 8:00-9:30 → periods 1-2, 10:00-11:30 → 3-4, 14:30-16:00 → 5-6
    if not periods:
        m = re.search(r"(\d{1,2}):\d{2}\s*[-~到至]\s*(\d{1,2}):\d{2}", text)
        if m:
            h1, h2 = int(m.group(1)), int(m.group(2))
            periods = _time_range_to_periods(h1, h2)
    return sorted(set(periods)) if periods else None


def _extract_weeks(text: str) -> str | None:
    """从 '1-14,17-18[1-2]' 或 '5-8[1-2]' 提取周次 '1-14,17-18' / '5-8'。
    就是把方括号里的节次部分去掉，返回纯周次范围。
    """
    if not text:
        return None
    # 去掉节次括号里的内容
    cleaned = re.sub(r"[\[【\(（].*?[\]】\)）]", "", text).strip()
    # 去掉末尾的 "周" 字
    cleaned = cleaned.rstrip("周").strip()
    if cleaned and re.search(r"\d", cleaned):
        return cleaned
    return None


def _time_range_to_periods(h1: int, h2: int) -> list[int] | None:
    """根据中国大学标准时间表把时间段转为节次。"""
    schedule = [
        (8, 9, [1, 2]),
        (10, 11, [3, 4]),
        (14, 15, [5, 6]),
        (16, 17, [7, 8]),
        (19, 20, [9, 10]),
    ]
    for start_h, end_h, ps in schedule:
        if h1 == start_h and h2 == end_h:
            return ps
    return None


# ── 单元格核心解析（v2 锚点驱动） ──────────────────────

# 非粘连分隔符：周次块开头前应该有这些字符之一
_SEPARATOR_CHARS = set(" \t\n,，;:：/|\\-—_()（）[]【】")


def _all_weeks_valid(weeks_str: str) -> bool:
    """验证 weeks_str 里所有数字是否都是合法周次（1-30）。"""
    if not weeks_str:
        return False
    text = re.sub(r"\s+", "", weeks_str)
    for part in text.split(","):
        if not part:
            continue
        m = re.match(r"^(\d{1,2})\s*[-~到至]\s*(\d{1,2})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if not (1 <= a <= 30 and 1 <= b <= 30):
                return False
        elif re.match(r"^\d{1,2}$", part):
            n = int(part)
            if not (1 <= n <= 30):
                return False
        else:
            return False
    return True


def _find_week_anchors(cell: str) -> list[tuple[int, int, str]]:
    """找所有周次锚点，解决教室号尾数字与周次粘连的问题。

    返回 [(seg_boundary, week_end, weeks_str), ...] 按位置排序。
      seg_boundary: 用于切分前面 name+teacher+location 文本块的边界
                    会往前扩展把粘连的教室号尾数字也包含进来
      week_end:     周次在 cell 中的实际结束位置
      weeks_str:    正确的周次数字范围（跳过粘连后的修正值）
    """
    candidates: list[tuple[float, int, int, int, str]] = []
    # (score, seg_boundary, week_start, week_end, weeks_str)

    for m in _WEEK_RE.finditer(cell):
        raw_start, raw_end = m.start(), m.end()
        raw_weeks = m.group(1)

        # seg_boundary 先用 raw_start（regex 匹配起点）
        # 如果后面找到更好的周次起点（alt_start），seg_boundary 也用它
        seg_boundary = raw_start

        # ── 尝试找到更好的周次起点（跳过粘连） ──
        best_start = raw_start
        best_weeks = raw_weeks
        best_end = raw_end
        score = 0.0

        prev = cell[raw_start - 1] if raw_start > 0 else ""
        if prev in _SEPARATOR_CHARS or raw_start == 0:
            score += 10
        elif prev.isdigit() or prev.isalpha() or '\u4e00' <= prev <= '\u9fff':
            score -= 5

        # 关键：即使 raw_weeks 不 valid，也尝试 jump 找更好的起点
        if raw_start > 0 and cell[raw_start - 1].isdigit():
            raw_nums = _parse_weeks(raw_weeks) or []
            raw_span = len(raw_nums)
            for jump in range(1, 8):
                alt_start = raw_start + jump
                if alt_start >= len(cell):
                    break
                alt = _WEEK_RE.match(cell, alt_start)
                if alt and alt.start() == alt.start():
                    ns, ne = alt.start(), alt.end()
                    nweeks = alt.group(1)
                    if not _all_weeks_valid(nweeks):
                        continue
                    alt_nums = _parse_weeks(nweeks) or []
                    alt_span = len(alt_nums)
                    # 接受 jump 条件：跨度更大 → 说明 raw 被截断/粘连了
                    if alt_span > raw_span:
                        best_start, best_weeks, best_end = ns, nweeks, ne
                        seg_boundary = ns
                        score += 20
                        break
                    # 跨度相等但 alt 的前字符不是数字（更干净）
                    if alt_span == raw_span and alt_span >= 4:
                        nprev = cell[ns - 1] if ns > 0 else ""
                        if not nprev.isdigit():
                            best_start, best_weeks, best_end = ns, nweeks, ne
                            seg_boundary = ns
                            score += 10
                            break

        # 原始匹配 valid 才加基础分
        if _all_weeks_valid(raw_weeks):
            score += 2

        # 跨度加分
        nums = _parse_weeks(best_weeks) or []
        if len(nums) >= 4:
            score += 3

        candidates.append((score, seg_boundary, best_start, best_end, best_weeks))

    if not candidates:
        return []

    # 按分数排序，贪心选不重叠的（按 seg_boundary ~ week_end 区间）
    candidates.sort(key=lambda x: -x[0])
    chosen: list[tuple[int, int, str]] = []
    used_ranges: list[tuple[int, int]] = []
    for score, seg_boundary, _ws, week_end, weeks_str in candidates:
        if any(not (week_end <= us or seg_boundary >= ue) for us, ue in used_ranges):
            continue
        chosen.append((seg_boundary, week_end, weeks_str))
        used_ranges.append((seg_boundary, week_end))

    chosen.sort(key=lambda x: x[0])
    return chosen


def _find_period_anchors(cell: str) -> list[tuple[int, int, str]]:
    """找所有括号里的节次锚点，返回 [(start, end, periods_str), ...]。"""
    anchors: list[tuple[int, int, str]] = []
    for m in _PERIOD_BRACKET_RE.finditer(cell):
        anchors.append((m.start(), m.end(), m.group(1)))
    return anchors


def _split_teacher(text: str) -> tuple[str, str | None]:
    """从文本里切出 teacher，返回 (课程名, teacher_or_None)。

    前置条件：调用者通常已经去掉了 location，text 是课程名 + 教师名的拼接。
    策略：显式标记优先，然后启发式从右往左切，优先选切完后剩余部分像课程名的。
    """
    text = text.strip()
    if not text:
        return "", None

    # ── 清理残留垃圾（周次/节次） ──
    cleaned = re.sub(r"\d{1,2}[-~到至]\d{1,2}周?$", "", text)
    cleaned = re.sub(r"\d{1,2}周$", "", cleaned)
    cleaned = re.sub(r"[\(\[【]\d{0,3}[\)\]】]\s*$", "", cleaned).strip()
    if not cleaned:
        return text, None

    # ── 显式标记 1: [编号]姓名 或 (课序号)姓名 ──
    m = re.search(r"[\(\[【]\s*(\d{4,})\s*[\)\]】]\s*([\u4e00-\u9fff]{2,6})\s*$", cleaned)
    if m:
        return cleaned[:m.start()].strip(), m.group(2)

    m = re.match(r"^(.*?)\s*[\(\（\[【](\d+)[\)\）\]】]\s*([\u4e00-\u9fff]{2,4})\s*$", cleaned)
    if m:
        base = m.group(1).strip()
        course_num = m.group(2)
        if base:
            base = base + f"（{course_num}）"
        return base, m.group(3)

    # ── 显式标记 2: 多 teacher "张三/李四" 在末尾 ──
    m = re.match(r"^(.*?)\s*([\u4e00-\u9fff]{2,4}\s*[/／,，、]\s*[\u4e00-\u9fff]{2,4})\s*$", cleaned)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # ── 启发式：从右往左切 2/3/4 字中文 ──
    LOC_SUFFIX = set("楼栋教馆室场厅院")
    _BRACKETS = set("()（）[]【】{},，、/／")
    candidates: list[tuple[int, str, str]] = []

    for tlen in (4, 3, 2):
        if len(cleaned) <= tlen + 1:
            continue
        teacher_part = cleaned[-tlen:]
        name_part = cleaned[:-tlen].strip()

        # 跳过明显不是 teacher 的
        if teacher_part[-1] in LOC_SUFFIX:
            continue
        if teacher_part[0] in _BRACKETS or teacher_part[-1] in _BRACKETS:
            continue
        if any(teacher_part.endswith(suf) for suf in _COURSE_SUFFIXES):
            continue
        # teacher 不能包含 location hint 字
        if any(h in teacher_part for h in LOC_SUFFIX):
            continue

        # —— 关键修复 1: 切完 name 必须 ≥ 3 字，且不能以连词结尾 ——
        if not name_part or len(name_part) < 3:
            continue
        if name_part[-1] in ("与", "及", "和", "或", "、"):
            continue
        # —— 关键修复 2: teacher part 不能太短（tlen=2 且 teacher 只有 2 字 且 name 看起来像完整课程名时跳过） ——
        if tlen == 2 and len(name_part) <= 4:
            # 短 name + 2字 teacher 大概率切错了
            continue

        candidates.append((tlen, name_part, teacher_part))

    if not candidates:
        return text, None

    # 优先选 name_part 以课程后缀结尾的
    for _tlen, name_part, teacher_part in candidates:
        if any(name_part.endswith(suf) for suf in _COURSE_SUFFIXES):
            return name_part, teacher_part

    # 再优先选 teacher 以常见教师后缀结尾的（老师/教授/博士/教练/师）
    _TEACHER_SUFFIXES = ("老师", "教授", "博士", "教练", "讲师")
    teacher_suffix_hits = [(t, n, tc) for t, n, tc in candidates
                           if any(tc.endswith(s) for s in _TEACHER_SUFFIXES)]
    if teacher_suffix_hits:
        # 优先 teacher 长度是 3（XX老师 最常见格式），然后 4，然后 2
        def _score_hit(x):
            tlen, name, teacher = x
            if tlen == 3:  # 3字teacher最优
                return (3, len(name))
            if tlen == 4:
                return (2, len(name))
            return (1, len(name))  # 2字teacher最低
        teacher_suffix_hits.sort(key=_score_hit, reverse=True)
        return teacher_suffix_hits[0][1], teacher_suffix_hits[0][2]

    # 再优先选 name_part 包含课程关键词的
    COURSE_HINTS = ("大学", "高等", "线性", "离散", "程序", "形势",
                    "工程", "机械", "电子", "计算", "数据", "计算机",
                    "信息", "控制", "经济", "管理", "英语", "数学", "物理")
    for _tlen, name_part, teacher_part in candidates:
        if any(h in name_part for h in COURSE_HINTS):
            return name_part, teacher_part

    # 兜底：teacher 字数多的优先
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][1], candidates[0][2]


def _split_location(text: str) -> tuple[str, str]:
    """从文本中定位 location，返回 (location, 剩余文本)。

    策略：location 必须带 ASCII 字母/数字后缀（如教一A201），或者匹配复合关键词。
    后缀只吃 [A-Za-z0-9\-]，不吃中文，避免把"王教练体育馆"吃成一个大串。
    更靠右的匹配优先（前面通常是课程名+教师）。
    """
    text = text.strip()
    if not text:
        return "", ""

    HINT_CHARS = "楼栋教馆室场厅院"

    # Step 1: 单字 hint + 可选 1 汉字 + 必须 ASCII 后缀（最可靠）
    # 例: "教一A201" → "教" + "一" + "A201"; "合教楼301" → "楼" 不是 hint... 要用复合关键词
    HINT_WITH_SUFFIX = re.compile(
        r"([" + HINT_CHARS + r"])"          # 1 个 hint 字
        r"([\u4e00-\u9fff]?)"            # 可选 1 个汉字
        r"([A-Za-z0-9][A-Za-z0-9\-]{0,9})"  # 必须以 ASCII 开头，1-10 位
    )

    best_location = ""
    best_start = -1
    best_end = 0

    for m in HINT_WITH_SUFFIX.finditer(text):
        start = m.start()
        end = m.end()
        loc_candidate = text[start:end]

        # 排除：hint 前是中文但长度只有 3 字以内
        if start > 0 and len(loc_candidate) <= 3:
            prev = text[start - 1]
            if '\u4e00' <= prev <= '\u9fff' and prev not in "北东南西新老主分":
                continue

        # 更靠右的优先
        if start > best_start:
            best_start = start
            best_end = end
            best_location = loc_candidate

    # Step 1.5: 如果 Step 1 找到 location，尝试往左扩展复合关键词
    # 例: 找到 "楼301"(start=9) → 检查 "合教楼" 跨在位置 8-10 → 扩展成 "合教楼301"
    COMPOSITE_KWS_LEFT = sorted([
        "合教楼", "合教", "体育馆", "体育场", "实验楼", "教学楼",
        "办公楼", "图书馆", "训练馆", "活动中心", "体育中心",
        "实验实训", "实训中心", "机电楼", "中心大楼",
    ], key=len, reverse=True)
    if best_start >= 0:
        for kw in COMPOSITE_KWS_LEFT:
            klen = len(kw)
            # 复合关键词的最后一个字对齐到 best_start - (klen-1) ~ best_start - 1 范围
            # 即 kw 跨在 [best_start - (klen-1), best_start] 位置
            for shift in range(klen - 1):
                left_idx = best_start - (klen - 1 - shift)
                if left_idx < 0:
                    continue
                kw_start = left_idx
                kw_end = left_idx + klen
                if kw_end > len(text):
                    continue
                if text[kw_start:kw_end] == kw:
                    # 复合关键词完全匹配！扩展
                    extended_loc = text[kw_start:best_end]
                    if 2 <= len(extended_loc) <= 15:
                        best_start = kw_start
                        best_location = extended_loc
                        break
            else:
                continue
            break

    # Step 2: 复合关键词（不带数字后缀但本身是完整 location）
    # 例: "体育馆"、"体育场"、"实验楼"
    if best_start < 0:
        COMPOSITE_KWS = sorted([
            "体育馆", "体育场", "实验楼", "教学楼", "办公楼", "图书馆",
            "训练馆", "活动中心", "体育中心", "实验实训", "实训中心",
            "合教楼", "合教",
        ], key=len, reverse=True)
        for kw in COMPOSITE_KWS:
            idx = text.rfind(kw)  # 从右找最靠右的
            if idx >= 0:
                best_start = idx
                best_end = idx + len(kw)
                best_location = kw
                break

    if best_start >= 0:
        rest = (text[:best_start] + text[best_end:]).strip()
        return best_location, rest

    return "", text


def _parse_course_cell(cell: str) -> list[dict]:
    """解析一个单元格 → 可能含多门课（v2 锚点驱动）。

    核心思路：
      1. 找所有周次锚点（"XX周" 格式，带粘连保护）
      2. 找所有节次锚点（括号里的数字范围）
      3. 按锚点切分 cell 成段：
           [0 .. wb[0].start]              = 第0门课的 [name+teacher+location?]
           [wb[i].end .. wb[i+1].start]   = 第i门的 location + 第i+1门的 name+teacher
           [wb[-1].end .. 末尾]           = 最后一门课的 location + 可能的垃圾
      4. 段内解析：先右切 teacher，再左定位 location
    """
    # 规范化：压缩空白、统一换行
    cell = cell.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cell:
        return []

    # ── Step 1: 找所有锚点 ──
    week_anchors = _find_week_anchors(cell)
    if not week_anchors:
        # 没有周次锚点 —— 可能是简写格式（只写课程名+教师+地点，无周次节次）
        result = _parse_no_week_cell(cell)
        return result

    # ── Step 2: 为每个周次锚点找紧随其后的节次锚点 ──
    # periods_for_week[i] = periods_str or None
    periods_for_week: list[str | None] = []
    period_anchors = _find_period_anchors(cell)
    for ws, we, _wt in week_anchors:
        # 找第一个起点 >= we 的 period anchor
        matched = None
        for ps, pe, pstr in period_anchors:
            if ps >= we and ps <= we + 10:  # 允许最多 10 字符间隔（比如 "周(1-2)"）
                matched = pstr
                break
        periods_for_week.append(matched)

    # ── Step 3: 构建课程片段 ──
    N = len(week_anchors)
    courses: list[dict] = []

    for i in range(N):
        # 第 i 门课的 [name+teacher+location] 文本范围
        if i == 0:
            seg_start = 0
        else:
            seg_start = week_anchors[i - 1][1]  # 上一个周次锚点的结束
        seg_end = week_anchors[i][0]  # 当前周次锚点的开始

        seg_text = cell[seg_start:seg_end].strip()

        name_part, teacher, location = _parse_name_teacher_loc_block(seg_text)
        weeks = _parse_weeks(week_anchors[i][2])
        periods = _parse_periods(periods_for_week[i]) if periods_for_week[i] else None

        if name_part:
            courses.append({
                "name": name_part,
                "teacher": teacher,
                "weeks": weeks,
                "periods": periods,
                "location": location,
            })

    return [c for c in courses if c["name"]]


def _parse_no_week_cell(cell: str) -> list[dict]:
    """没有周次锚点的单元格 —— 简化解析。"""
    # 先拆 location
    location, rest = _split_location(cell)
    # 再拆 teacher（在剩下的 name+teacher 里）
    name_part, teacher = _split_teacher(rest) if rest else ("", None)
    if not name_part and rest:
        name_part = rest
    name_part = _clean_name(name_part or cell)
    location_clean = _clean_location(location) if location else None

    if not name_part or len(name_part) < 2:
        return []

    return [{
        "name": name_part,
        "teacher": teacher,
        "weeks": None,
        "periods": None,
        "location": location_clean,
    }]


def _parse_name_teacher_loc_block(text: str) -> tuple[str, str | None, str | None]:
    """解析一个文本块 → (name, teacher_or_None, location_or_None)。

    策略：先定位 location（在中间），然后在剩下的 name+teacher 里右切 teacher。
    这样 "高等数学张玉鑫教一A201" → 先找 location="教一A201"，剩下 "高等数学张玉鑫"
    → 再右切 teacher="张玉鑫"，name="高等数学"。
    """
    if not text:
        return "", None, None

    # Step 1: 先定位 location
    location, rest = _split_location(text)

    # Step 2: 在剩下的 name+teacher 里右切 teacher
    if rest:
        name_part, teacher = _split_teacher(rest)
    else:
        name_part, teacher = text, None

    # Step 3: 清理
    location_clean = _clean_location(location) if location else None
    name_clean = _clean_name(name_part) if name_part else _clean_name(rest or text)

    # 如果 split_location 没分出 location，name_part 就是 rest
    if not location_clean and name_part == "" and rest:
        name_clean = _clean_name(rest)

    return name_clean, teacher, location_clean


# ── 周课表网格检测 ─────────────────────────────────────

def _detect_weekly_grid(matrix: list[list[str]]) -> tuple[int, int, int, int, dict[int, int]] | None:
    """定位周课表网格区域。返回 (top_row, bottom_row, left_col, right_col, {col: weekday})。

    v2：支持三种表头格式：
      1. "星期一"/"周X" 完整格式
      2. 单独 "一"/"二"/"三" 单字（需确认这一列是 weekday 列）
      3. "周一"/"周二" 简写
    """
    if not matrix or len(matrix) < 2:
        return None

    # 先找完整格式表头
    header_row_idx = -1
    best_count = 0
    for i, row in enumerate(matrix):
        count = 0
        for cell in row:
            if re.search(r"(?:星期|周)\s*[一二三四五六日天]", cell):
                count += 1
        if count >= 2 and count > best_count:
            best_count = count
            header_row_idx = i

    # 如果完整格式不够，试单字格式
    if header_row_idx < 0:
        for i, row in enumerate(matrix):
            count = 0
            for cell in row:
                cell_clean = cell.strip()
                if cell_clean in _WD_MAP:
                    count += 1
            # 放宽到 >=3（至少有 3 个 weekday 列才像课表）
            if count >= 2 and count > best_count:
                best_count = count
                header_row_idx = i

    if header_row_idx < 0:
        return None

    header = matrix[header_row_idx]
    wd_map: dict[int, int] = {}
    for ci, cell in enumerate(header):
        cell = cell.strip()
        # 完整格式
        m = re.search(r"(?:星期|周)\s*([一二三四五六日天])", cell)
        if m and m.group(1) in _WD_MAP:
            wd_map[ci] = _WD_MAP[m.group(1)]
            continue
        # 单字格式
        if cell in _WD_MAP:
            wd_map[ci] = _WD_MAP[cell]

    if not wd_map:
        return None

    bottom_row = len(matrix)
    _TERMINATOR_KEYWORDS = (
        # 原有关键词
        "上课班级代码", "总学时", "修读性质", "选课状态", "学分", "课程性质", "先修课程",
        # 底部详细列表表头（这些一出现就说明 grid 结束了）
        "课程名称", "任课教师", "起止周次", "上课时间", "总学时", "学分",
        # 其他表格终止关键词
        "备注", "教材", "课程简介", "考核方式",
    )
    for r in range(header_row_idx + 1, len(matrix)):
        row = matrix[r]
        row_text = " ".join(row)
        # 关键词匹配（出现任意 1 个）
        if any(kw in row_text for kw in _TERMINATOR_KEYWORDS):
            # 排除：如果这一行同时也是 grid 的有效数据行（含有周次/节次标记），则不能终止
            if re.search(r"\d{1,2}\s*[-~到至]\s*\d{1,2}\s*周", row_text):
                continue
            if re.search(r"\d{1,2}\s*\[\d{1,2}", row_text):  # 含 [1-2] 格式节次
                continue
            bottom_row = r
            break
        # 空白行：不立即终止！上午/下午/晚上之间会有空白间隔
        # 只终止在表格末尾连续很多空白（≥ 6 行），且之后没有任何 grid 数据了
        empty_count = 0
        for r2 in range(r, min(r + 6, len(matrix))):
            if not any(c.strip() for c in matrix[r2]):
                empty_count += 1
            else:
                break
        if empty_count >= 6:
            bottom_row = r
            break

    left_col = min(wd_map.keys())
    right_col = max(wd_map.keys())
    return (header_row_idx + 1, bottom_row, left_col, right_col, wd_map)


def _find_period_col(matrix: list[list[str]], grid_top: int) -> int | None:
    """找最左侧的节次号列（含 1,2,3... 或 1-2,3-4 等节次标记）。

    返回列索引（0-based），没找到返回 None。
    """
    if grid_top >= len(matrix):
        return None

    for ci in range(0, 5):  # 最多检查前 5 列
        col_values = []
        for r in range(grid_top, min(grid_top + 8, len(matrix))):
            if ci < len(matrix[r]):
                col_values.append(matrix[r][ci].strip())

        # 跳过空列
        non_empty = [v for v in col_values if v]
        if len(non_empty) < 2:
            continue

        # 检查是否有节次号模式
        period_count = 0
        for v in non_empty:
            if re.search(r"\d{1,2}", v):
                period_count += 1
            elif v in ("上午", "下午", "晚上", "中午"):
                period_count += 1

        # 超过一半的非空值含节次号 → 这是节次列
        if period_count >= len(non_empty) * 0.5:
            return ci

    return None


def _extract_periods_from_row(row: list[str], period_col: int | None) -> list[int] | None:
    """从节次列提取节次号列表（只看 period_col，不拼整行避免多段合并）。"""
    if period_col is None or period_col >= len(row):
        return None

    text = row[period_col].strip()
    if not text:
        return None

    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    nums: list[int] = []
    # 数字范围
    for m in re.finditer(r"(\d{1,2})\s*[-~到至]\s*(\d{1,2})", text):
        a, b = int(m.group(1)), int(m.group(2))
        # 合理校验：period 不会超过 16
        if 1 <= a <= 16 and 1 <= b <= 16:
            nums.extend(range(min(a, b), max(a, b) + 1))
    if nums:
        return sorted(set(nums))
    # 单个数字（可能有多个，逐个提取）
    single = re.findall(r"(?<!\d)(\d{1,2})(?!\d)", text)
    if single:
        valid = [int(x) for x in single if 1 <= int(x) <= 16]
        if valid:
            return valid
    # 中文数字
    m = re.search(r"([一二三四五六七八九十]+)", text)
    if m and all(c in mapping for c in m.group(1)):
        n = mapping[m.group(1)[0]]
        if 1 <= n <= 16:
            return [n]

    return None


# ── 主入口 ─────────────────────────────────────────────

def parse_matrix_to_courses(matrix: list[list[str]]) -> dict:
    """从矩阵提取课程字典（替代 parse_table_paste 文本方案）。"""
    if not matrix:
        return {"courses": []}

    courses_map: dict[str, dict] = {}

    def _add_session(name, wd, periods, weeks, teacher, location):
        if not name:
            return
        clean = _clean_name(name)
        if not clean:
            return
        # 紧急垃圾过滤：节次范围、纯地点、纯人名
        if _is_likely_garbage_name(clean):
            return
        # 修复：不再默认兜底 periods=[1]，那是 session 错乱的根因之一
        if not periods:
            return  # 没有 period 信息不入库，避免 fake data
        # session 必须有 weekday（grid 扫描时 wd 应该有值）
        if wd is None:
            return
        course = courses_map.setdefault(
            clean,
            {
                "name": clean,
                "teacher": teacher,
                "location": location,
                "sessions": [],
            },
        )
        if teacher and not course.get("teacher"):
            course["teacher"] = teacher
        if location and not course.get("location"):
            course["location"] = location
        for p in periods:
            if wd is None:
                continue
            key = (wd, p)
            if not any((s["weekday"], s["period_no"]) == key for s in course["sessions"]):
                course["sessions"].append(
                    {
                        "weekday": wd,
                        "period_no": p,
                        "weeks": weeks,
                    }
                )

    # ── 周课表网格 ──
    grid_info = _detect_weekly_grid(matrix)
    if grid_info:
        top, bottom, left, right, wd_map = grid_info
        period_col = _find_period_col(matrix, top)

        # ── 检测 split-rows 模式 ──
        # 有些课表把 name/teacher/time/location 分成 4 行
        # 检测：找 4 个连续行，weekday 列在第一行有课程名，第二行有教师，第三行有 [节次] 格式，第四行有地点
        split_mode = False
        split_period_stride = 4  # name/teacher/time/location 4 行一组
        if bottom - top >= 4:
            sample_col = min(wd_map.keys())
            for c in wd_map.keys():
                if c < len(matrix[top]):
                    sample_col = c
                    break
            for r in range(top, bottom - 3, 4):
                r0 = matrix[r] if r < len(matrix) else []
                r1 = matrix[r + 1] if r + 1 < len(matrix) else []
                r2 = matrix[r + 2] if r + 2 < len(matrix) else []
                r3 = matrix[r + 3] if r + 3 < len(matrix) else []
                name_cell = r0[sample_col].strip() if sample_col < len(r0) else ""
                teacher_cell = r1[sample_col].strip() if sample_col < len(r1) else ""
                time_cell = r2[sample_col].strip() if sample_col < len(r2) else ""
                loc_cell = r3[sample_col].strip() if sample_col < len(r3) else ""
                if (name_cell and teacher_cell
                        and re.search(r"\[\d{1,2}[-~]\d{1,2}\]", time_cell)
                        and (loc_cell or True)):  # location 可以为空
                    split_mode = True
                    break

        if split_mode:
            # ── split-rows 合并模式：4 行一组 ──
            r = top
            while r < bottom - 3:
                # 跳过完全空白的 4 行组（上午/下午之间的间隔）
                row0 = matrix[r]
                if not any(
                    (c.strip() for c in row0[left:right + 1] if c)
                ):
                    r += 1
                    continue

                # 每个 4 行组内迭代 weekday 列
                for c in range(left, right + 1):
                    wd = wd_map.get(c)
                    if not wd:
                        continue
                    name_cell = (matrix[r][c] if c < len(matrix[r]) else "").strip()
                    teacher_cell = (
                        (matrix[r + 1][c] if c < len(matrix[r + 1]) else "")
                        if r + 1 < len(matrix)
                        else ""
                    ).strip()
                    time_cell = (
                        (matrix[r + 2][c] if c < len(matrix[r + 2]) else "")
                        if r + 2 < len(matrix)
                        else ""
                    ).strip()
                    loc_cell = (
                        (matrix[r + 3][c] if c < len(matrix[r + 3]) else "")
                        if r + 3 < len(matrix)
                        else ""
                    ).strip()

                    if not name_cell:
                        continue

                    # ── split-mode：直接从各字段提取，更精确 ──
                    clean_name = _clean_name(name_cell)
                    if not clean_name or _is_likely_garbage_name(clean_name):
                        continue

                    # 周次从 time_cell 提取
                    weeks = _extract_weeks(time_cell) if time_cell else None
                    # 节次从 time_cell 的括号提取
                    periods = _extract_bracket_periods(time_cell) if time_cell else None

                    # teacher：信任 split-mode 的结构——第二行就是教师
                    # 只要是 2-4 个中文字符（人名形态）就接受
                    teacher = None
                    if teacher_cell:
                        t = teacher_cell.strip()
                        if re.match(r"^[\u4e00-\u9fff]{2,4}$", t):
                            teacher = t

                    # location：信任 split-mode——第四行就是地点，用 _clean_location 清理
                    location = None
                    if loc_cell:
                        loc = _clean_location(loc_cell)
                        if loc:
                            location = loc

                    _add_session(
                        name=clean_name,
                        wd=wd,
                        periods=periods,
                        weeks=weeks,
                        teacher=teacher,
                        location=location,
                    )

                r += split_period_stride
        else:
            # ── 标准模式：单单元格含所有信息 ──
            for r in range(top, bottom):
                row = matrix[r]
                if not row:
                    continue
                row_periods = _extract_periods_from_row(row, period_col)

                for c in range(left, right + 1):
                    if c >= len(row):
                        continue
                    cell = row[c] or ""
                    wd = wd_map.get(c)
                    if not cell.strip() or not wd:
                        continue

                    for unit in _parse_course_cell(cell):
                        # 节次优先级：单元格内显式节次 > 行上节次列
                        periods = unit.get("periods") or row_periods
                        _add_session(
                            name=unit.get("name", ""),
                            wd=wd,
                            periods=periods,
                            weeks=unit.get("weeks"),
                            teacher=unit.get("teacher"),
                            location=unit.get("location"),
                        )

    # ── 底部详细列表（补充 grid 没覆盖到的课） ──
    # 安全检查：grid 扫描已经覆盖了大部分课程
    # 只有当 grid 没覆盖到时才启用详细列表解析，且必须有可靠的 name+teacher 双列匹配
    header_idx = -1
    for i, row in enumerate(matrix):
        cells = [c.strip() for c in row]
        # 更严格的表头识别：必须同时有"课程"和"教师"关键词
        has_course = any("课程" in c for c in cells)
        has_teacher = any("教师" in c for c in cells)
        if has_course and has_teacher:
            header_idx = i
            break

    if header_idx >= 0:
        header = [c.strip() for c in matrix[header_idx]]
        name_col = teacher_col = loc_col = -1
        for ci, h in enumerate(header):
            if name_col < 0 and h in ("课程", "课程名", "名称", "课程名称"):
                name_col = ci
            if teacher_col < 0 and "教师" in h:
                teacher_col = ci
            if loc_col < 0 and ("地点" in h or "教室" in h):
                loc_col = ci

        # 安全检查：必须同时找到 name_col 和 teacher_col 才启动（只有课程名列容易误匹配）
        if name_col >= 0 and teacher_col >= 0:
            for r in range(header_idx + 1, len(matrix)):
                row = matrix[r]
                if not any(c.strip() for c in row):
                    continue
                raw_name = row[name_col].strip() if name_col < len(row) else ""
                if not raw_name:
                    continue
                clean = _clean_name(raw_name)
                # 关键：垃圾 name 直接跳过
                if not clean or _is_likely_garbage_name(clean):
                    continue
                # 已经由 grid 扫描过的课程跳过
                if clean in courses_map:
                    continue
                teacher = None
                if teacher_col >= 0 and teacher_col < len(row):
                    t = row[teacher_col].strip()
                    if t and re.search(r"[\u4e00-\u9fff]{2,6}", t):
                        teacher = re.search(r"[\u4e00-\u9fff]{2,6}", t).group(0)
                location = None
                if loc_col >= 0 and loc_col < len(row):
                    loc = _clean_location(row[loc_col])
                    if loc and not _is_likely_garbage_name(loc):
                        location = loc
                # 详细列表的课程没有具体 weekday/period，只加 name+teacher+location 元数据
                # 不再调用 _add_session（因为没有 wd/periods，避免制造假数据）
                if clean not in courses_map:
                    courses_map[clean] = {
                        "name": clean,
                        "teacher": teacher,
                        "location": location,
                        "sessions": [],  # 空 sessions —— UI 上可能不显示在周课表里但课程列表里有
                    }

    return {"courses": list(courses_map.values())}
