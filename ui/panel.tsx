import {
  Page,
  Card,
  Grid,
  Stack,
  Inline,
  Text,
  Alert,
  StatCard,
  StatusBadge,
  Button,
  ButtonGroup,
  Field,
  Input,
  PasswordInput,
  NumberInput,
  Select,
  Textarea,
  RefreshButton,
  DataTable,
  EmptyState,
  Steps,
  Step,
  Tip,
  Warning,
  Toolbar,
  ToolbarGroup,
  Divider,
  Tabs,
  Accordion,
  Progress,
  KeyValue,
  Form,
  FormSection,
  FormActions,
  useForm,
  useState,
  useEffect,
  useToast,
  useConfirm,
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
  const confirm = useConfirm()

  const [loading, setLoading] = useState(false)
  const [semesters, setSemesters] = useState<Semester[]>([])
  const [activeSem, setActiveSem] = useState<Semester | null>(null)
  const [todaySessions, setTodaySessions] = useState<Session[]>([])
  const [weekDays, setWeekDays] = useState<any[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [homework, setHomework] = useState<Homework[]>([])
  const [exams, setExams] = useState<Exam[]>([])
  const [countdown, setCountdown] = useState<Countdown | null>(null)

  const [adapters, setAdapters] = useState<{ id: string; name: string }[]>([])
  const [importLoading, setImportLoading] = useState(false)

  // Tab state: today / week / countdown
  const [scheduleTab, setScheduleTab] = useState("today")

  const importForm = useForm({
    adapter: "",
    base_url: "",
    school_code: "",
    username: "",
    password: "",
    semester_keyword: "",
    semester_id: "",
  })

  const [csvText, setCsvText] = useState("")
  const [csvLoading, setCsvLoading] = useState(false)

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
        "导入成功（适配器：" + (r.adapter || f.adapter) + "）",
        stats.courses ? "课程 " + stats.courses + " 门" : "",
        stats.sessions ? "课时 " + stats.sessions + " 节" : "",
        stats.created ? "新增 " + stats.created : "",
        stats.updated ? "更新 " + stats.updated : "",
      ].filter(Boolean).join("，")
      toast.success(msg)
      importForm.setValues({
        ...importForm.values,
        username: "",
        password: "",
      })
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
    finally { setImportLoading(false) }
  }

  async function doImportCsv() {
    if (!csvText.trim()) { toast.error("请粘贴课程表格内容"); return }
    setCsvLoading(true)
    try {
      const r = await callEntry("import_from_structured", {
        format: "csv",
        text: csvText,
        semester_id: activeSem?.id || 0,
      })
      const stats = r.stats || {}
      toast.success("导入成功：课程 " + (stats.courses || 0) + " 门，课时 " + (stats.sessions || 0) + " 节")
      setCsvText("")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
    finally { setCsvLoading(false) }
  }

  async function doExportCsv() {
    try {
      const r = await callEntry("export_schedule", { format: "csv" })
      toast.success("课程表已导出（" + (r.text || r.url || "请查看返回数据") + "）")
    } catch (err: any) { toast.error(String(err?.message || err)) }
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
    const ok = await confirm({
      title: "删除作业",
      message: `确认删除作业「${hw.title}」吗？`,
      tone: "danger",
      confirmLabel: "删除",
      cancelLabel: "取消",
    })
    if (!ok) return
    try {
      await callEntry("delete_homework", { homework_id: hw.id })
      toast.success("已删除")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
  }

  async function deleteExam(ex: Exam) {
    const ok = await confirm({
      title: "删除考试",
      message: `确认删除考试「${ex.title}」吗？`,
      tone: "danger",
      confirmLabel: "删除",
      cancelLabel: "取消",
    })
    if (!ok) return
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
    if (!weekDays.length) return <EmptyState title="暂无本周数据" description="请先创建学期并添加课程" />
    return (
      <Grid cols={7}>
        {weekDays.map((day, i) => (
          <Card key={i} title={WEEKDAYS[i] || `Day${i}`}>
            <Stack gap="xs">
              <Text>{day.date}</Text>
              {day.count > 0 ? (
                <StatusBadge tone="info">{day.count} 节课</StatusBadge>
              ) : (
                <Text>无课</Text>
              )}
            </Stack>
          </Card>
        ))}
      </Grid>
    )
  }

  // ===== 计算派生值 =====
  const activeWeekLabel = countdown?.week ? `${countdown.week}/${countdown.total_weeks}周` : "—"
  const weekProgress = countdown && countdown.total_weeks > 0 && countdown.week
    ? Math.round((countdown.week / countdown.total_weeks) * 100)
    : 0
  const overdueHw = homework.filter((h) => h.overdue).length
  const pendingHw = homework.filter((h) => h.done === 0).length

  return (
    <Page title="课程表" subtitle={activeSem ? `${activeSem.name} · 第 ${activeWeekLabel}` : "请先创建学期"}>
      <Stack gap="md">

        {/* ========== 顶部工具栏：状态 + 刷新 ========== */}
        <Toolbar>
          <ToolbarGroup>
            {activeSem ? (
              <StatusBadge tone="success">{activeSem.name}</StatusBadge>
            ) : (
              <StatusBadge tone="warning">未选择学期</StatusBadge>
            )}
            <StatusBadge tone="info">第 {activeWeekLabel}</StatusBadge>
            {overdueHw > 0 ? (
              <StatusBadge tone="danger">{overdueHw} 项逾期</StatusBadge>
            ) : null}
            {pendingHw > 0 && overdueHw === 0 ? (
              <StatusBadge tone="warning">{pendingHw} 项待完成</StatusBadge>
            ) : null}
          </ToolbarGroup>
          <ToolbarGroup>
            <RefreshButton label={loading ? "刷新中..." : "刷新"} onRefresh={() => { refreshAll() }} />
          </ToolbarGroup>
        </Toolbar>

        {/* ========== 周进度条 ========== */}
        {activeSem && countdown ? (
          <Progress label={`学期进度 ${weekProgress}%`} value={weekProgress} />
        ) : null}

        {/* ========== 统计卡 ========== */}
        <Grid cols={4}>
          <StatCard label="今日课程" value={todaySessions.length} />
          <StatCard label="待完成作业" value={pendingHw} />
          <StatCard label="考试数" value={exams.length} />
          <StatCard
            label="距下次考试"
            value={countdown?.days_until_next_exam != null ? `${countdown.days_until_next_exam} 天` : "-"}
          />
        </Grid>

        {!activeSem ? (
          <Alert tone="warning">还没有学期，请在下方「学期管理」创建一个学期</Alert>
        ) : null}

        {/* ========== 课表三合一：Tabs 切换 ========== */}
        <Card title="课表">
          <Tabs
            activeId={scheduleTab}
            items={[
              {
                id: "today",
                label: `今日 (${todaySessions.length})`,
                content: (
                  todaySessions.length > 0 ? (
                    <Stack gap="xs">
                      {todaySessions.map((s, i) => (
                        <Grid key={i} cols={4}>
                          <Text>第{s.period_no}节</Text>
                          <Text>{s.name}</Text>
                          <Text>{s.location || "-"}</Text>
                          <Text>{s.teacher || "-"}</Text>
                        </Grid>
                      ))}
                    </Stack>
                  ) : (
                    <EmptyState title="今天无课" description="好好休息一下吧" />
                  )
                ),
              },
              {
                id: "week",
                label: "本周",
                content: renderWeekGrid(),
              },
              {
                id: "countdown",
                label: "倒计时",
                content: countdown ? (
                  <Stack gap="md">
                    <KeyValue
                      items={[
                        { key: "exam", label: "距下次考试", value: countdown.days_until_next_exam != null ? `${countdown.days_until_next_exam} 天` : "—" },
                        { key: "hw", label: "距下次作业截止", value: countdown.days_until_next_homework != null ? `${countdown.days_until_next_homework} 天` : "—" },
                        { key: "sem", label: "距学期结束", value: countdown.days_until_semester_end != null ? `${countdown.days_until_semester_end} 天` : "—" },
                        { key: "week", label: "当前周次", value: `第 ${countdown.week || "?"} / ${countdown.total_weeks} 周` },
                      ]}
                    />
                    <Tip>{countdown.summary}</Tip>
                  </Stack>
                ) : (
                  <EmptyState title="暂无倒计时" description="添加考试和作业后可查看倒计时" />
                ),
              },
            ]}
            onChange={(id) => setScheduleTab(id)}
          />
        </Card>

        {/* ========== 快速上手指引（可折叠） ========== */}
        <Accordion id="guide" title="快速上手指引" open={true}>
          <Stack gap="xs">
            <Steps>
              <Step index="1" title="创建学期">
                <Text>在学期管理填写学期名（如 2025秋季）、开始/结束日期，点「添加学期」</Text>
              </Step>
              <Step index="2" title="添加课程（任选其一）">
                <Stack gap="xs">
                  <Text>A. 一键教务导入：填教务地址 + 学号密码 → 自动拉取全部课程</Text>
                  <Text>B. 表格粘贴导入：从教务/Excel 复制课程表 → 粘贴 → 一键导入</Text>
                  <Text>C. 手动录入：逐门填写课程名、教师、地点、周几第几节</Text>
                </Stack>
              </Step>
              <Step index="3" title="作业/考试/提醒（可选）">
                <Text>在下方「作业管理」「考试管理」添加；上课提醒在 plugin.toml 的 [course] 段开启 remind_enabled</Text>
              </Step>
            </Steps>
            <Tip>更多说明见 docs/guide.md，或直接向 AI 询问课程表相关问题</Tip>
          </Stack>
        </Accordion>

        {/* ========== Grid 2列：学期管理 + 一键教务导入 ========== */}
        <Grid cols={2}>

          {/* 学期管理 */}
          <Card title="学期管理">
            <Stack gap="md">
              {semesters.length === 0 ? (
                <EmptyState title="暂无学期" description="创建第一个学期开始使用课程表" />
              ) : (
                <DataTable
                  rowKey="id"
                  columns={[
                    { key: "name", label: "学期" },
                    { key: "start_date", label: "开始" },
                    { key: "end_date", label: "结束" },
                    { key: "total_weeks", label: "周数" },
                    {
                      key: "is_active",
                      label: "状态",
                      render: (row) => row.is_active
                        ? <StatusBadge tone="success">当前</StatusBadge>
                        : <Text>—</Text>,
                    },
                    {
                      key: "actions",
                      label: "操作",
                      render: (row) => (
                        <Button tone="primary" onClick={() => switchSemester(row.id as number)} disabled={!!row.is_active}>
                          切换
                        </Button>
                      ),
                    },
                  ]}
                  data={semesters}
                />
              )}
              <Divider />
              <Form>
                <FormSection title="新建学期">
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
                    <Field label="总周数" help="留空则自动估算">
                      <NumberInput
                        value={semForm.values.total_weeks === "" ? "" : Number(semForm.values.total_weeks)}
                        placeholder="自动估算"
                        onChange={(v) => semForm.setField("total_weeks", String(v))}
                      />
                    </Field>
                  </Grid>
                </FormSection>
                <FormActions>
                  <Button tone="success" onClick={addSemester}>添加学期</Button>
                </FormActions>
              </Form>
            </Stack>
          </Card>

          {/* 一键从教务系统导入 */}
          <Card title="一键从教务系统导入">
            <Stack gap="xs">
              {adapters.length === 0 ? (
                <Alert tone="warning">未检测到可用的教务适配器，请确认插件已完整加载</Alert>
              ) : (
                <Text>可用适配器：{adapters.map((a) => a.name).join("、")}</Text>
              )}
              <Form>
                <FormSection title="教务凭据">
                  <Grid cols={2}>
                    <Field label="教务适配器">
                      <Select
                        value={importForm.values.adapter}
                        options={adapters.map((a) => ({ value: a.id, label: a.name }))}
                        onChange={(v) => importForm.setField("adapter", String(v))}
                      />
                    </Field>
                    <Field label="或 学校代码" help="如 12623（可选）">
                      <Input
                        value={importForm.values.school_code}
                        placeholder="如 12623"
                        onChange={(v) => importForm.setField("school_code", v)}
                      />
                    </Field>
                    <Field label="教务系统地址" help="教务登录页URL">
                      <Input
                        value={importForm.values.base_url}
                        placeholder="https://your-school.jwxt.edu.cn"
                        onChange={(v) => importForm.setField("base_url", v)}
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
                      <PasswordInput
                        value={importForm.values.password}
                        placeholder="教务系统密码"
                        onChange={(v) => importForm.setField("password", v)}
                      />
                    </Field>
                    <Field label="学期关键字" help="如 2025秋（可选）">
                      <Input
                        value={importForm.values.semester_keyword}
                        placeholder="如 2025秋"
                        onChange={(v) => importForm.setField("semester_keyword", v)}
                      />
                    </Field>
                  </Grid>
                </FormSection>
                {activeSem ? (
                  <FormSection title="目标学期">
                    <Field label={"导入到学期（当前：" + activeSem.name + "）"}>
                      <Select
                        value={importForm.values.semester_id}
                        options={[
                          { value: "", label: "自动创建 / 匹配" },
                          ...semesters.map((s) => ({
                            value: String(s.id),
                            label: s.name + (s.is_active ? " (当前)" : ""),
                          })),
                        ]}
                        onChange={(v) => importForm.setField("semester_id", String(v))}
                      />
                    </Field>
                  </FormSection>
                ) : null}
                <FormActions>
                  <Button
                    tone="primary"
                    onClick={doImportAcademic}
                    disabled={importLoading || adapters.length === 0}
                  >
                    {importLoading ? "导入中..." : "一键从教务系统导入"}
                  </Button>
                </FormActions>
              </Form>
              <Warning>学号密码仅在本次请求中使用，不会被保存</Warning>
            </Stack>
          </Card>

        </Grid>

        {/* ========== Grid 2列：手动添加课程 + 表格粘贴导入 ========== */}
        <Grid cols={2}>

          {/* 添加课程 */}
          {activeSem ? (
            <Card title="添加课程">
              <Form>
                <FormSection title="课程信息">
                  <Grid cols={2}>
                    <Field label="课程名">
                      <Input value={courseForm.values.name} placeholder="高等数学" onChange={(v) => courseForm.setField("name", v)} />
                    </Field>
                    <Field label="课程代码" help="可选">
                      <Input value={courseForm.values.code} placeholder="MATH101" onChange={(v) => courseForm.setField("code", v)} />
                    </Field>
                    <Field label="教师" help="可选">
                      <Input value={courseForm.values.teacher} placeholder="张老师" onChange={(v) => courseForm.setField("teacher", v)} />
                    </Field>
                    <Field label="地点" help="可选">
                      <Input value={courseForm.values.location} placeholder="教学楼A-101" onChange={(v) => courseForm.setField("location", v)} />
                    </Field>
                  </Grid>
                </FormSection>
                <FormSection title="上课时间">
                  <Grid cols={2}>
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
                </FormSection>
                <FormActions>
                  <Button tone="success" onClick={addCourse}>添加课程</Button>
                </FormActions>
              </Form>
            </Card>
          ) : (
            <Card title="添加课程">
              <Alert tone="warning">请先创建学期</Alert>
            </Card>
          )}

          {/* 表格粘贴导入（CSV）*/}
          <Card title="表格粘贴导入">
            <Stack gap="xs">
              <Tip>
                从教务系统或 Excel 复制课程表格（支持 CSV / 制表符分隔），粘贴到下方文本框。
                每行格式：课程名, 教师, 地点, 周几(1-7), 节次(如 1-2)
              </Tip>
              <Textarea
                value={csvText}
                placeholder={"示例：\n高等数学,张老师,A-101,1,1-2\n大学英语,李老师,B-202,2,3-4\n线性代数,王老师,C-303,3,5-6"}
                onChange={(v) => setCsvText(v)}
              />
              <Inline gap="xs">
                <Button
                  tone="primary"
                  onClick={doImportCsv}
                  disabled={csvLoading}
                >
                  {csvLoading ? "导入中..." : "从表格导入"}
                </Button>
                <Button tone="default" onClick={doExportCsv}>导出当前课程表</Button>
              </Inline>
            </Stack>
          </Card>

        </Grid>

        {/* ========== 课程列表 ========== */}
        {courses.length > 0 ? (
          <Card title="课程列表">
            <DataTable
              rowKey="id"
              columns={[
                { key: "name", label: "课程" },
                { key: "code", label: "代码" },
                { key: "teacher", label: "教师" },
                { key: "location", label: "地点" },
              ]}
              data={courses}
            />
          </Card>
        ) : null}

        {/* ========== Grid 2列：作业管理 + 考试管理 ========== */}
        <Grid cols={2}>

          {/* 作业管理 */}
          {activeSem ? (
            <Card title="作业管理">
              <Stack gap="md">
                <Form>
                  <FormSection title="新增作业">
                    <Grid cols={2}>
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
                  </FormSection>
                  <FormActions>
                    <Button tone="success" onClick={addHomework}>添加作业</Button>
                  </FormActions>
                </Form>
                {homework.length === 0 ? (
                  <EmptyState title="暂无作业" description="添加第一个作业来跟踪完成进度" />
                ) : (
                  <DataTable
                    rowKey="id"
                    columns={[
                      { key: "title", label: "作业" },
                      { key: "course_name", label: "课程" },
                      { key: "due_at", label: "截止" },
                      {
                        key: "done",
                        label: "状态",
                        render: (row) => row.overdue
                          ? <StatusBadge tone="danger">逾期</StatusBadge>
                          : row.done === 1
                            ? <StatusBadge tone="success">已完成</StatusBadge>
                            : <StatusBadge tone="warning">待完成</StatusBadge>,
                      },
                      {
                        key: "actions",
                        label: "操作",
                        render: (row) => (
                          <ButtonGroup>
                            <Button tone="primary" onClick={() => toggleHomework(row as Homework)}>
                              {(row as Homework).done === 1 ? "取消" : "完成"}
                            </Button>
                            <Button tone="danger" onClick={() => deleteHomework(row as Homework)}>删除</Button>
                          </ButtonGroup>
                        ),
                      },
                    ]}
                    data={homework}
                  />
                )}
              </Stack>
            </Card>
          ) : null}

          {/* 考试管理 */}
          {activeSem ? (
            <Card title="考试管理">
              <Stack gap="md">
                <Form>
                  <FormSection title="新增考试">
                    <Grid cols={2}>
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
                  </FormSection>
                  <FormActions>
                    <Button tone="success" onClick={addExam}>添加考试</Button>
                  </FormActions>
                </Form>
                {exams.length === 0 ? (
                  <EmptyState title="暂无考试" description="添加考试来设置提醒" />
                ) : (
                  <DataTable
                    rowKey="id"
                    columns={[
                      { key: "title", label: "考试" },
                      { key: "course_name", label: "课程" },
                      { key: "due_at", label: "日期" },
                      { key: "location", label: "考场" },
                      {
                        key: "actions",
                        label: "操作",
                        render: (row) => (
                          <Button tone="danger" onClick={() => deleteExam(row as Exam)}>删除</Button>
                        ),
                      },
                    ]}
                    data={exams}
                  />
                )}
              </Stack>
            </Card>
          ) : null}

        </Grid>
      </Stack>
    </Page>
  )
}
