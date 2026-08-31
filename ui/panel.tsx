import {
  Page,
  Card,
  Grid,
  Stack,
  Text,
  Alert,
  StatCard,
  StatusBadge,
  Button,
  Field,
  Input,
  Select,
  Switch,
  RefreshButton,
  DataTable,
  Divider,
  useForm,
  useState,
  useEffect,
  useToast,
} from "@neko/plugin-ui"
import type { PluginSurfaceProps } from "@neko/plugin-ui"

type Session = {
  period_no: number
  name: string
  location?: string | null
  teacher?: string | null
  weekday?: number
  start_time?: string
  end_time?: string
}

type Course = {
  id: number
  name: string
  code?: string | null
  teacher?: string | null
  location?: string | null
}

type Homework = {
  id: number
  title: string
  due_at?: string | null
  done: number
  course_name?: string | null
  note?: string | null
  overdue?: boolean
}

type Exam = {
  id: number
  title: string
  due_at?: string | null
  location?: string | null
  note?: string | null
  course_name?: string | null
  overdue?: boolean
}

type Semester = {
  id: number
  name: string
  start_date: string
  end_date: string
  total_weeks: number
  is_active?: number | boolean
}

type Countdown = {
  days_until_next_exam: number | null
  days_until_next_homework: number | null
  days_until_semester_end: number | null
  week: number | null
  total_weeks: number
  summary: string
}

const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
const PERIOD_SLOTS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

function unwrap(result: any): any {
  if (!result) return {}
  if (result.data) return result.data
  if (result.result) return result.result
  return result
}

export default function CourseSchedulePanel(props: PluginSurfaceProps<Record<string, any>>) {
  const toast = useToast()

  const [loading, setLoading] = useState(false)
  const [semesters, setSemesters] = useState<Semester[]>([])
  const [activeSem, setActiveSem] = useState<Semester | null>(null)
  const [todaySessions, setTodaySessions] = useState<Session[]>([])
  const [weekDays, setWeekDays] = useState<any[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [homework, setHomework] = useState<Homework[]>([])
  const [exams, setExams] = useState<Exam[]>([])
  const [countdown, setCountdown] = useState<Countdown | null>(null)
  const [todayInfo, setTodayInfo] = useState<any>({})

  // 教务系统导入
  const [adapters, setAdapters] = useState<{ id: string; name: string }[]>([])
  const [importLoading, setImportLoading] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)

  const importForm = useForm({
    adapter: "",
    base_url: "",
    school_code: "",
    username: "",
    password: "",
    semester_keyword: "",
    semester_id: "",
  })

  const semForm = useForm({
    name: "",
    start_date: "",
    end_date: "",
    total_weeks: "",
  })

  const courseForm = useForm({
    name: "",
    code: "",
    teacher: "",
    location: "",
    weekday: "1",
    period_no: "1",
  })

  const hwForm = useForm({
    title: "",
    course_id: "",
    due_at: "",
    note: "",
  })

  const examForm = useForm({
    title: "",
    course_id: "",
    due_at: "",
    location: "",
    note: "",
  })

  async function callEntry(entryId: string, args: Record<string, any> = {}): Promise<any> {
    const result = await props.api.call(entryId, args)
    return unwrap(result)
  }

  async function refreshAll() {
    setLoading(true)
    try {
      const sems = await callEntry("list_semesters")
      const semList: Semester[] = sems.semesters || []
      setSemesters(semList)
      const active = semList.find((s) => s.is_active) || semList[0] || null
      setActiveSem(active)

      if (active) {
        const [today, week, cs, hw, ex, cd] = await Promise.all([
          callEntry("get_today_schedule"),
          callEntry("get_week_schedule"),
          callEntry("list_courses"),
          callEntry("list_homework"),
          callEntry("list_exams"),
          callEntry("get_countdown"),
        ])
        setTodayInfo(today)
        setTodaySessions(today.sessions || [])
        setWeekDays(week.days || [])
        setCourses(cs.courses || [])
        setHomework(hw.homework || [])
        setExams(ex.exams || [])
        setCountdown(cd)
      } else {
        setTodaySessions([])
        setWeekDays([])
        setCourses([])
        setHomework([])
        setExams([])
        setCountdown(null)
      }
    } catch (err: any) {
      toast.error(String(err?.message || err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshAll()
    // 加载可用教务适配器
    callEntry("list_academic_adapters").then((r: any) => {
      setAdapters(r.adapters || [])
      if ((r.adapters || []).length > 0) {
        importForm.setField("adapter", r.adapters[0].id)
      }
    }).catch(() => {})
  }, [])

  async function doImportAcademic() {
    const f = importForm.values
    if (!f.adapter) { toast.error("请选择教务适配器"); return }
    if (!f.username || !f.password) { toast.error("请填写学号和密码"); return }
    // base_url 和 school_code 至少要有一个
    if (!f.base_url && !f.school_code) { toast.error("请填写教务系统地址或学校代码"); return }
    setImportLoading(true)
    try {
      const args: Record<string, any> = {
        adapter: f.adapter,
        username: f.username,
        password: f.password,
      }
      if (f.base_url) args.base_url = f.base_url
      if (f.school_code) args.school_code = f.school_code
      if (f.semester_keyword) args.semester_selector = { keyword: f.semester_keyword }
      const sid = Number(f.semester_id)
      if (sid > 0) args.semester_id = sid

      const r = await callEntry("import_from_academic", args)
      const stats = r.stats || {}
      const msg = [
        `✅ 导入成功（适配器：${r.adapter || f.adapter}）`,
        r.semester_fetched ? `学期：${r.semester_fetched.name || r.semester_fetched}` : null,
        `课程：${stats.courses_created ?? "-"} 新建，${stats.courses_updated ?? "-"} 更新`,
        `课时：${stats.sessions_created ?? "-"}`,
        stats.skipped ? `跳过：${stats.skipped}` : null,
      ].filter(Boolean).join(" | ")
      toast.success(msg)
      importForm.setValues({
        ...importForm.values,
        username: "",
        password: "",
        semester_keyword: "",
        semester_id: "",
      })
      await refreshAll()
    } catch (err: any) {
      toast.error(String(err?.message || err))
    } finally {
      setImportLoading(false)
    }
  }

  async function addSemester() {
    if (!semForm.values.name || !semForm.values.start_date || !semForm.values.end_date) {
      toast.error("请填写学期名、开始和结束日期")
      return
    }
    try {
      await callEntry("add_semester", {
        name: semForm.values.name,
        start_date: semForm.values.start_date,
        end_date: semForm.values.end_date,
        total_weeks: Number(semForm.values.total_weeks) || 0,
      })
      toast.success("学期已创建")
      semForm.setValues({ name: "", start_date: "", end_date: "", total_weeks: "" })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function addCourse() {
    if (!courseForm.values.name) { toast.error("请填写课程名"); return }
    try {
      await callEntry("add_course", {
        name: courseForm.values.name,
        code: courseForm.values.code || undefined,
        teacher: courseForm.values.teacher || undefined,
        location: courseForm.values.location || undefined,
        sessions: [{
          weekday: Number(courseForm.values.weekday),
          period_no: Number(courseForm.values.period_no),
        }],
      })
      toast.success("课程已添加")
      courseForm.setValues({ name: "", code: "", teacher: "", location: "", weekday: "1", period_no: "1" })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function addHomework() {
    if (!hwForm.values.title) { toast.error("请填写作业标题"); return }
    try {
      await callEntry("add_homework", {
        title: hwForm.values.title,
        course_id: Number(hwForm.values.course_id) || undefined,
        due_at: hwForm.values.due_at || undefined,
        note: hwForm.values.note || undefined,
      })
      toast.success("作业已添加")
      hwForm.setValues({ title: "", course_id: "", due_at: "", note: "" })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function addExam() {
    if (!examForm.values.title) { toast.error("请填写考试名称"); return }
    try {
      await callEntry("add_exam", {
        title: examForm.values.title,
        course_id: Number(examForm.values.course_id) || undefined,
        due_at: examForm.values.due_at || undefined,
        location: examForm.values.location || undefined,
        note: examForm.values.note || undefined,
      })
      toast.success("考试已添加")
      examForm.setValues({ title: "", course_id: "", due_at: "", location: "", note: "" })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function toggleHomework(hw: Homework) {
    try {
      await callEntry("done_homework", {
        homework_id: hw.id,
        undone: hw.done === 1,
      })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function deleteHomework(hw: Homework) {
    try {
      await callEntry("delete_homework", { homework_id: hw.id })
      toast.success("已删除")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function deleteExam(ex: Exam) {
    try {
      await callEntry("delete_exam", { exam_id: ex.id })
      toast.success("已删除")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function switchSemester(semId: number) {
    try {
      await callEntry("switch_semester", { semester_id: semId })
      toast.success("已切换学期")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  function renderWeekGrid() {
    if (!weekDays.length) return <Alert tone="info">暂无本周课表数据</Alert>
    return (
      <Grid cols={7}>
        {weekDays.map((day, i) => (
          <Card key={i} title={WEEKDAYS[i] || `Day${i}`} subtitle={day.date}>
            <Stack gap="xs">
              {day.count > 0 ? (
                <Text tone="success" size="sm">{day.count} 节课</Text>
              ) : (
                <Text tone="muted" size="sm">无课</Text>
              )}
              <Text size="xs" tone="muted">{day.summary?.split("\n").slice(1).join(" · ")}</Text>
            </Stack>
          </Card>
        ))}
      </Grid>
    )
  }

  return (
    <Page title="课程表" subtitle={activeSem ? `${activeSem.name} · 第 ${countdown?.week || "?"}/${activeSem.total_weeks} 周` : "请先创建学期"}>
      <Stack>
        <Grid cols={4}>
          <StatCard label="今日课程" value={todaySessions.length} />
          <StatCard label="待完成作业" value={homework.filter((h) => h.done === 0).length} />
          <StatCard label="考试数" value={exams.length} />
          <StatCard
            label="距下次考试"
            value={countdown?.days_until_next_exam != null ? `${countdown.days_until_next_exam} 天` : "-"}
          />
        </Grid>

        <RefreshButton onClick={refreshAll} loading={loading} label="刷新" />

        {!activeSem ? (
          <Alert tone="warning">还没有学期，请在下方创建一个学期</Alert>
        ) : null}

        {/* 使用教程 */}
        <Card title="快速上手指引">
          <Stack gap="md">
            <Button size="sm" tone="primary" onClick={() => setGuideOpen((v) => !v)}>
              {guideOpen ? "▼ 收起教程" : "▶ 展开教程"}
            </Button>
            {guideOpen ? (
              <Stack gap="md">
                <Alert tone="info">
                  按下面 3 步走，即可完成初始化。最简单的方式是使用教务系统一键导入。
                </Alert>
                <Stack gap="xs">
                  <Text tone="bold">① 创建学期</Text>
                  <Text size="sm" tone="muted">
                    在下方「学期管理」里填写学期名（如 2025 秋季）、开始 / 结束日期，点「添加学期」。
                  </Text>
                </Stack>
                <Stack gap="xs">
                  <Text tone="bold">② 添加课程（两种方式任选其一）</Text>
                  <Text size="sm" tone="muted">
                    A. 一键从教务系统导入：填写教务系统地址（或学校代码）+ 学号密码 → 自动拉取所有课程。
                  </Text>
                  <Text size="sm" tone="muted">
                    B. 手动录入：在下方「添加课程」里逐门填写课程名、教师、地点、周几第几节。
                  </Text>
                </Stack>
                <Stack gap="xs">
                  <Text tone="bold">③ 作业 / 考试 / 提醒（可选）</Text>
                  <Text size="sm" tone="muted">
                    添加完课程后，可以在下方「作业管理」「考试管理」里添加作业和考试。上课提醒需在
                    plugin.toml 的 [course] 段里把 remind_enabled 设为 true。
                  </Text>
                </Stack>
                <Divider />
                <Text tone="muted" size="sm">
                  💡 更多功能（周重复 / 单双周 / 例外调课 / AI 查询）请见插件附带的使用指南文档，
                  或直接向 AI 询问课程表相关问题。
                </Text>
              </Stack>
            ) : (
              <Text tone="muted" size="sm">创建学期 → 一键教务导入（或手动添加课程）→ 完成</Text>
            )}
          </Stack>
        </Card>

        {/* 今日课表 */}
        <Card title="今日课表">
          {todaySessions.length > 0 ? (
            <Stack gap="xs">
              {todaySessions.map((s, i) => (
                <Grid key={i} cols={4}>
                  <Text size="sm">第{s.period_no}节</Text>
                  <Text size="sm" tone="bold">{s.name}</Text>
                  <Text size="sm" tone="muted">{s.location || "-"}</Text>
                  <Text size="sm" tone="muted">{s.teacher || "-"}</Text>
                </Grid>
              ))}
            </Stack>
          ) : (
            <Text tone="muted">今天无课</Text>
          )}
        </Card>

        {/* 本周网格 */}
        <Card title="本周课表">
          {renderWeekGrid()}
        </Card>

        {/* 倒计时 */}
        {countdown ? (
          <Card title="倒计时">
            <Text>{countdown.summary}</Text>
          </Card>
        ) : null}

        {/* 学期管理 */}
        <Card title="学期管理">
          <Stack>
            {semesters.length > 0 ? (
              <DataTable
                columns={[
                  { key: "name", label: "学期" },
                  { key: "start_date", label: "开始" },
                  { key: "end_date", label: "结束" },
                  { key: "total_weeks", label: "周数" },
                  { key: "is_active", label: "状态" },
                ]}
                rows={semesters.map((s) => ({
                  ...s,
                  is_active: s.is_active ? "当前" : "—",
                  _actions: (
                    <Button size="sm" tone="primary" onClick={() => switchSemester(s.id)} disabled={!!s.is_active}>
                      切换
                    </Button>
                  ),
                }))}
              />
            ) : null}
            <Divider />
            <Grid cols={4}>
              <Field label="学期名">
                <Input value={semForm.values.name} placeholder="2025秋季" onChange={(v) => semForm.setField("name", v)} />
              </Field>
              <Field label="开始日期">
                <Input value={semForm.values.start_date} placeholder="2025-09-01" onChange={(v) => semForm.setField("start_date", v)} />
              </Field>
              <Field label="结束日期">
                <Input value={semForm.values.end_date} placeholder="2026-01-15" onChange={(v) => semForm.setField("end_date", v)} />
              </Field>
              <Field label="总周数（可选）">
                <Input value={semForm.values.total_weeks} placeholder="自动估算" onChange={(v) => semForm.setField("total_weeks", v)} />
              </Field>
            </Grid>
            <Button tone="success" onClick={addSemester}>添加学期</Button>
          </Stack>
        </Card>

        {/* 一键从教务系统导入 */}
        <Card
          title="🚀 一键从教务系统导入"
          subtitle="最快的初始化方式 — 填账号密码即可拉取全部课程"
        >
          <Stack>
            {adapters.length === 0 ? (
              <Alert tone="warning">
                未检测到可用的教务适配器。请确认插件已完整加载，或联系开发者添加适配器。
              </Alert>
            ) : (
              <Text tone="muted" size="sm">
                可用适配器：{adapters.map((a) => a.name).join("、")}
              </Text>
            )}
            <Grid cols={3}>
              <Field label="教务适配器">
                <Select
                  value={importForm.values.adapter}
                  options={adapters.map((a) => ({ value: a.id, label: a.name }))}
                  onChange={(v) => importForm.setField("adapter", String(v))}
                />
              </Field>
              <Field label="教务系统地址">
                <Input
                  value={importForm.values.base_url}
                  placeholder="https://your-school.jwxt.edu.cn"
                  onChange={(v) => importForm.setField("base_url", v)}
                />
              </Field>
              <Field label="或 学校代码">
                <Input
                  value={importForm.values.school_code}
                  placeholder="如 12623（可选，有预设时不用填地址）"
                  onChange={(v) => importForm.setField("school_code", v)}
                />
              </Field>
              <Field label="学号 / 工号">
                <Input
                  value={importForm.values.username}
                  placeholder="你的学号"
                  onChange={(v) => importForm.setField("username", v)}
                />
              </Field>
              <Field label="密码">
                <Input
                  value={importForm.values.password}
                  placeholder="教务系统密码（仅本次请求）"
                  onChange={(v) => importForm.setField("password", v)}
                />
              </Field>
              <Field label="学期关键字（可选）">
                <Input
                  value={importForm.values.semester_keyword}
                  placeholder="如 '2025秋'，不填则默认最新学期"
                  onChange={(v) => importForm.setField("semester_keyword", v)}
                />
              </Field>
            </Grid>
            {activeSem ? (
              <Field label={`导入到学期（当前：${activeSem.name}，可选）`}>
                <Select
                  value={importForm.values.semester_id}
                  options={[
                    { value: "", label: "自动创建 / 匹配" },
                    ...semesters.map((s) => ({ value: String(s.id), label: s.name + (s.is_active ? " (当前)" : "") })),
                  ]}
                  onChange={(v) => importForm.setField("semester_id", String(v))}
                />
              </Field>
            ) : null}
            <Button
              tone="primary"
              onClick={doImportAcademic}
              loading={importLoading}
              disabled={importLoading || adapters.length === 0}
            >
              {importLoading ? "导入中…" : "🚀 一键导入"}
            </Button>
            <Alert tone="info">
              导入时将自动创建 / 更新课程与课时。学号密码仅在本次请求中使用，不会被保存。
            </Alert>
          </Stack>
        </Card>

        {/* 添加课程 */}
        {activeSem ? (
          <Card title="添加课程">
            <Grid cols={3}>
              <Field label="课程名">
                <Input value={courseForm.values.name} placeholder="高等数学" onChange={(v) => courseForm.setField("name", v)} />
              </Field>
              <Field label="课程代码">
                <Input value={courseForm.values.code} placeholder="MATH101" onChange={(v) => courseForm.setField("code", v)} />
              </Field>
              <Field label="教师">
                <Input value={courseForm.values.teacher} placeholder="张老师" onChange={(v) => courseForm.setField("teacher", v)} />
              </Field>
              <Field label="地点">
                <Input value={courseForm.values.location} placeholder="教学楼A-101" onChange={(v) => courseForm.setField("location", v)} />
              </Field>
              <Field label="周几">
                <Select
                  value={courseForm.values.weekday}
                  options={WEEKDAYS.map((d, i) => ({ value: String(i + 1), label: d }))}
                  onChange={(v) => courseForm.setField("weekday", String(v))}
                />
              </Field>
              <Field label="第几节">
                <Select
                  value={courseForm.values.period_no}
                  options={PERIOD_SLOTS.map((p) => ({ value: String(p), label: `第${p}节` }))}
                  onChange={(v) => courseForm.setField("period_no", String(v))}
                />
              </Field>
            </Grid>
            <Button tone="success" onClick={addCourse}>添加课程</Button>
          </Card>
        ) : null}

        {/* 课程列表 */}
        {courses.length > 0 ? (
          <Card title="课程列表">
            <DataTable
              columns={[
                { key: "name", label: "课程" },
                { key: "code", label: "代码" },
                { key: "teacher", label: "教师" },
                { key: "location", label: "地点" },
              ]}
              rows={courses}
            />
          </Card>
        ) : null}

        {/* 作业管理 */}
        {activeSem ? (
          <Card title="作业管理">
            <Grid cols={4}>
              <Field label="作业标题">
                <Input value={hwForm.values.title} placeholder="第一章习题" onChange={(v) => hwForm.setField("title", v)} />
              </Field>
              <Field label="关联课程">
                <Select
                  value={hwForm.values.course_id}
                  options={[{ value: "", label: "无" }, ...courses.map((c) => ({ value: String(c.id), label: c.name }))]}
                  onChange={(v) => hwForm.setField("course_id", String(v))}
                />
              </Field>
              <Field label="截止日期">
                <Input value={hwForm.values.due_at} placeholder="2026-09-05" onChange={(v) => hwForm.setField("due_at", v)} />
              </Field>
              <Field label="备注">
                <Input value={hwForm.values.note} placeholder="1-20题" onChange={(v) => hwForm.setField("note", v)} />
              </Field>
            </Grid>
            <Button tone="success" onClick={addHomework}>添加作业</Button>
            {homework.length > 0 ? (
              <DataTable
                columns={[
                  { key: "title", label: "作业" },
                  { key: "course_name", label: "课程" },
                  { key: "due_at", label: "截止" },
                  { key: "done", label: "状态" },
                ]}
                rows={homework.map((h) => ({
                  ...h,
                  done: h.done === 1 ? "已完成" : h.overdue ? "逾期" : "待完成",
                  _actions: (
                    <Stack direction="inline" gap="xs">
                      <Button size="sm" tone="primary" onClick={() => toggleHomework(h)}>
                        {h.done === 1 ? "取消" : "完成"}
                      </Button>
                      <Button size="sm" tone="danger" onClick={() => deleteHomework(h)}>删除</Button>
                    </Stack>
                  ),
                }))}
              />
            ) : null}
          </Card>
        ) : null}

        {/* 考试管理 */}
        {activeSem ? (
          <Card title="考试管理">
            <Grid cols={4}>
              <Field label="考试名称">
                <Input value={examForm.values.title} placeholder="期中考试" onChange={(v) => examForm.setField("title", v)} />
              </Field>
              <Field label="关联课程">
                <Select
                  value={examForm.values.course_id}
                  options={[{ value: "", label: "无" }, ...courses.map((c) => ({ value: String(c.id), label: c.name }))]}
                  onChange={(v) => examForm.setField("course_id", String(v))}
                />
              </Field>
              <Field label="考试日期">
                <Input value={examForm.values.due_at} placeholder="2026-09-15" onChange={(v) => examForm.setField("due_at", v)} />
              </Field>
              <Field label="考场">
                <Input value={examForm.values.location} placeholder="考试楼A" onChange={(v) => examForm.setField("location", v)} />
              </Field>
            </Grid>
            <Field label="考试范围">
              <Input value={examForm.values.note} placeholder="第1-5章" onChange={(v) => examForm.setField("note", v)} />
            </Field>
            <Button tone="success" onClick={addExam}>添加考试</Button>
            {exams.length > 0 ? (
              <DataTable
                columns={[
                  { key: "title", label: "考试" },
                  { key: "course_name", label: "课程" },
                  { key: "due_at", label: "日期" },
                  { key: "location", label: "考场" },
                ]}
                rows={exams.map((e) => ({
                  ...e,
                  _actions: (
                    <Button size="sm" tone="danger" onClick={() => deleteExam(e)}>删除</Button>
                  ),
                }))}
              />
            ) : null}
          </Card>
        ) : null}
      </Stack>
    </Page>
  )
}
