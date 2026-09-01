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
import type { CSSProperties, ReactNode, ChangeEvent as ReactChangeEvent } from "react"

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

  // Tab state: today / week / fullgrid / countdown
  const [scheduleTab, setScheduleTab] = useState("fullgrid")

  // 文件上传
  const [fileUploadName, setFileUploadName] = useState("")
  const [fileUploadLoading, setFileUploadLoading] = useState(false)

  // 高级工具：清空/诊断
  const [dangerLoading, setDangerLoading] = useState(false)
  const [previewName, setPreviewName] = useState("")
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewResult, setPreviewResult] = useState<any>(null)

  // 完整周课表网格数据
  const [scheduleView, setScheduleView] = useState<{
    grid?: Record<number, Record<number, any[]>>
    periods?: number[]
    period_times?: Record<number, { start_time: string; end_time: string }>
  }>({})

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
        const [today, week, cs, hw, ex, cd, sv] = await Promise.all([
          callEntry("get_today_schedule"),
          callEntry("get_week_schedule"),
          callEntry("list_courses"),
          callEntry("list_homework"),
          callEntry("list_exams"),
          callEntry("get_countdown"),
          callEntry("get_schedule_view", { semester_id: active.id }),
        ])
        setTodaySessions(today.sessions || [])
        setWeekDays(week.days || [])
        setCourses(cs.courses || [])
        setHomework(hw.homework || [])
        setExams(ex.exams || [])
        setCountdown(cd)
        setScheduleView(sv)
      } else {
        setTodaySessions([])
        setWeekDays([])
        setCourses([])
        setHomework([])
        setExams([])
        setCountdown(null)
        setScheduleView({})
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
      const r = await callEntry("import_schedule", {
        format: "csv",
        content: csvText,
        semester_id: activeSem?.id || 0,
      })
      const stats = r.stats || {}
      const nCourses = stats.created_courses ?? stats.courses ?? 0
      const nSessions = stats.created_sessions ?? stats.sessions ?? 0
      toast.success("导入成功：课程 " + nCourses + " 门，课时 " + nSessions + " 节")
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

  async function doUploadFile(file: File) {
    setFileUploadLoading(true)
    try {
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          const dataUrl = reader.result as string
          // data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,....
          const r = await callEntry("import_schedule_file", {
            file_base64: dataUrl,
            filename: file.name,
            semester_id: activeSem?.id || 0,
          })
          const stats = r.stats || {}
          const nCourses = stats.created_courses ?? stats.courses ?? 0
          const nSessions = stats.created_sessions ?? stats.sessions ?? 0
          const detected = r.courses_detected ?? 0
          toast.success("文件导入成功：识别 " + detected + " 门课，新增 " + nCourses + " 门 / " + nSessions + " 节")
          setFileUploadName("")
          await refreshAll()
        } catch (err: any) { toast.error(String(err?.message || err)) }
        finally { setFileUploadLoading(false) }
      }
      reader.onerror = () => {
        toast.error("文件读取失败")
        setFileUploadLoading(false)
      }
      reader.readAsDataURL(file)
    } catch (err: any) {
      toast.error(String(err?.message || err))
      setFileUploadLoading(false)
    }
  }

  function onFileInputChange(e: ReactChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFileUploadName(f.name + "  (" + Math.round(f.size / 1024) + " KB)")
    doUploadFile(f)
    // 重置 input，允许连续选同一个文件
    e.target.value = ""
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

  async function doClearSchedule(alsoDeleteSemester = false) {
    const semName = activeSem?.name ?? "当前学期"
    const ok = await confirm({
      title: alsoDeleteSemester ? "删除整个学期" : "清空课表数据",
      message: alsoDeleteSemester
        ? `确定要删除学期「${semName}」及其下所有课程、课时、作业、考试记录吗？学期本身也会被移除，此操作不可恢复！`
        : `确定要清空学期「${semName}」的所有课程、上课安排、作业和考试吗？学期本身保留，此操作不可恢复！`,
      tone: "danger",
      confirmLabel: alsoDeleteSemester ? "彻底删除" : "全部清空",
      cancelLabel: "取消",
    })
    if (!ok) return
    setDangerLoading(true)
    try {
      const r = await callEntry("clear_schedule_data", { also_delete_semester: alsoDeleteSemester })
      const d = r.deleted || {}
      const parts = []
      if (alsoDeleteSemester) parts.push("学期已删除")
      if (d.courses) parts.push(`课程 ${d.courses} 门`)
      if (d.sessions) parts.push(`课时 ${d.sessions} 节`)
      if (d.exceptions) parts.push(`例外 ${d.exceptions} 条`)
      if (d.assignments) parts.push(`作业/考试 ${d.assignments} 项`)
      toast.success(parts.join("，") || "完成")
      await refreshAll()
    } catch (err: any) { toast.error(String(err?.message || err)) }
    finally { setDangerLoading(false) }
  }

  async function doPreviewFile(file: File) {
    setPreviewLoading(true)
    setPreviewName(file.name + "  (" + Math.round(file.size / 1024) + " KB)")
    setPreviewResult(null)
    try {
      const reader = new FileReader()
      reader.onload = async () => {
        try {
          const dataUrl = reader.result as string
          const r = await callEntry("preview_schedule_file", {
            file_base64: dataUrl,
            filename: file.name,
          })
          setPreviewResult(r)
          const n = r.courses_found ?? 0
          if (n > 0) toast.success(`解析成功，识别 ${n} 门课`)
          else toast.warning("未能从文件中识别到课程数据，请查看下方诊断信息")
        } catch (err: any) {
          toast.error(String(err?.message || err))
          setPreviewResult({ error: String(err?.message || err) })
        } finally { setPreviewLoading(false) }
      }
      reader.onerror = () => { setPreviewLoading(false); toast.error("文件读取失败") }
      reader.readAsDataURL(file)
    } catch (err: any) { setPreviewLoading(false); toast.error(String(err?.message || err)) }
  }

  function onPreviewFileChange(e: ReactChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    doPreviewFile(f)
    e.target.value = ""
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

  /** 把课程色（hex/rgba/空）安全地转成半透明 rgba，用作卡片背景 */
  function tintColor(raw: any, alpha = 0.12): string {
    const s = String(raw || "").trim()
    // hex #rgb 或 #rrggbb
    const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(s)
    if (hex) {
      let h = hex[1]
      if (h.length === 3) h = h.split("").map((c) => c + c).join("")
      const r = parseInt(h.slice(0, 2), 16)
      const g = parseInt(h.slice(2, 4), 16)
      const b = parseInt(h.slice(4, 6), 16)
      return `rgba(${r},${g},${b},${alpha})`
    }
    // 原生 rgba()/rgb() 直接返回（不做 tint，保持原样）
    if (/^rgba?\(/i.test(s)) return s
    return `rgba(79,148,205,${alpha})`
  }

  /** 对 block 数组做去重键；同一格可能多门课，但合并 rowspan 只看首门课的身份 */
  function blockIdentity(block: any): string {
    // 颜色归一化（空色用默认），避免前后端大小写/空白差异
    const color = (block.color || "#4f94cd").toLowerCase().trim()
    return JSON.stringify([
      block.name || "",
      block.teacher || "",
      block.location || "",
      color,
    ])
  }

  /** 把 weeks 数组格式化成可读范围，如 [1..16] -> "1-16周"，[1,3,5] -> "第1/3/5周" */
  function formatWeeks(weeks: any[] | undefined | null): string {
    if (!weeks || !weeks.length) return ""
    const nums = weeks
      .map((w: any) => Number(w))
      .filter((n: number) => Number.isFinite(n))
      .sort((a: number, b: number) => a - b)
    if (!nums.length) return ""
    // 检测是否连续
    let isRange = true
    for (let i = 1; i < nums.length; i++) {
      if (nums[i] !== nums[i - 1] + 1) { isRange = false; break }
    }
    if (isRange && nums.length > 1) return `${nums[0]}-${nums[nums.length - 1]}周`
    return `第${nums.join("/")}周`
  }

  function renderFullScheduleGrid() {
    const grid = scheduleView.grid || {}
    const periods = scheduleView.periods || PERIOD_SLOTS
    const pt = scheduleView.period_times || {}

    if (!periods.length) {
      return <EmptyState title="暂无课表数据" description="请先创建学期、导入或添加课程" />
    }

    // ---- 只保留实际有课的 weekday ----
    const ALL_WEEKDAYS = [1, 2, 3, 4, 5, 6, 7]
    const presentWeekdays = ALL_WEEKDAYS.filter((wd) =>
      periods.some((p) => (grid[wd]?.[p]?.length ?? 0) > 0),
    )
    if (presentWeekdays.length === 0) {
      return <EmptyState title="课表为空" description="请先导入或添加课程" />
    }
    const usedWeekdays = presentWeekdays

    // ---- 只保留头尾非空的 period 区间 ----
    const hasCoursePerPeriod = periods.map((p) =>
      usedWeekdays.some((wd) => (grid[wd]?.[p]?.length ?? 0) > 0),
    )
    let firstIdx = hasCoursePerPeriod.findIndex(Boolean)
    let lastIdx = hasCoursePerPeriod.lastIndexOf(Boolean)
    if (firstIdx === -1) { firstIdx = 0; lastIdx = periods.length - 1 }
    const usedPeriods = periods.slice(firstIdx, lastIdx + 1)

    // ---- 为每个 weekday 构建 rowspan 合并计划 ----
    // 每一项: { startIdx, span, blocks }
    type MergePlan = { startIdx: number; span: number; blocks: any[] }
    const mergePlans: Record<number, MergePlan[]> = {}
    for (const wd of usedWeekdays) {
      const plans: MergePlan[] = []
      let i = 0
      while (i < usedPeriods.length) {
        const pno = usedPeriods[i]
        const curBlocks = (grid[wd] && grid[wd][pno]) || []
        // 连续相同课程合并：当前与上一个计划的 blocks 首门课的 identity 相等
        let span = 1
        const baseBlocks = curBlocks
        if (baseBlocks.length > 0) {
          while (i + span < usedPeriods.length) {
            const nextBlocks = (grid[wd] && grid[wd][usedPeriods[i + span]]) || []
            if (
              nextBlocks.length === baseBlocks.length &&
              baseBlocks.every((b, k) => blockIdentity(b) === blockIdentity(nextBlocks[k]))
            ) {
              span++
            } else break
          }
        }
        plans.push({ startIdx: i, span, blocks: baseBlocks })
        i += span
      }
      mergePlans[wd] = plans
    }

    // ---- 样式 ----
    const cellStyle: CSSProperties = {
      border: "1px solid rgba(0,0,0,0.08)",
      padding: "4px 6px",
      verticalAlign: "top",
      fontSize: 12,
      minHeight: 48,
    }
    const headerStyle: CSSProperties = {
      ...cellStyle,
      background: "rgba(0,0,0,0.035)",
      fontWeight: 600,
      textAlign: "center",
      minHeight: 30,
    }
    const cornerStyle: CSSProperties = {
      ...headerStyle,
      width: 72,
      textAlign: "center",
      whiteSpace: "nowrap",
    }

    // ---- 渲染行 ----
    const rows: ReactNode[] = []
    for (let ri = 0; ri < usedPeriods.length; ri++) {
      const pno = usedPeriods[ri]
      const pinfo = pt[pno]
      const timeLabel = pinfo ? `${pinfo.start_time}-${pinfo.end_time}` : ""
      const cells: React.ReactNode[] = [
        <td key="c" style={cornerStyle}>
          <div>第{pno}节</div>
          {timeLabel ? <div style={{ fontWeight: 400, fontSize: 11, opacity: 0.65 }}>{timeLabel}</div> : null}
        </td>,
      ]
      for (const wd of usedWeekdays) {
        const plans = mergePlans[wd]
        // 找到当前 ri 所在的 plan
        const plan = plans.find((p) => p.startIdx === ri)
        // 如果 ri 不是 plan 起点，说明已被 rowspan 吃掉，跳过
        if (!plan) continue
        const firstColor = plan.blocks[0]?.color || "#4f94cd"
        const blockStyle: CSSProperties = {
          background: tintColor(firstColor, 0.12),
          borderRadius: 4,
          padding: "3px 6px",
          marginBottom: 3,
          borderLeft: "3px solid " + firstColor,
          overflowWrap: "anywhere",
        }
        cells.push(
          <td
            key={"w" + wd}
            style={{ ...cellStyle, background: plan.blocks.length === 0 ? undefined : "rgba(255,255,255,0.3)" }}
            rowSpan={plan.span > 1 ? plan.span : undefined}
          >
            {plan.blocks.map((b: any, bi: number) => {
              const wtext = formatWeeks(b.weeks)
              return (
                <div key={bi} style={blockStyle}>
                  <div style={{ fontWeight: 600, fontSize: 12, lineHeight: 1.3, overflowWrap: "anywhere" }}>{b.name}</div>
                  {b.teacher ? <div style={{ opacity: 0.75, fontSize: 11, lineHeight: 1.4 }}>{b.teacher}</div> : null}
                  {b.location ? <div style={{ opacity: 0.75, fontSize: 11, lineHeight: 1.4, overflowWrap: "anywhere" }}>{b.location}</div> : null}
                  {wtext ? <div style={{ opacity: 0.55, fontSize: 10, lineHeight: 1.4, marginTop: 1 }}>{wtext}</div> : null}
                </div>
              )
            })}
          </td>,
        )
      }
      rows.push(<tr key={"r" + ri}>{cells}</tr>)
    }

    return (
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            borderCollapse: "collapse",
            tableLayout: "auto",
            width: "100%",
          }}
        >
          <thead>
            <tr>
              <th style={cornerStyle}>节次</th>
              {usedWeekdays.map((wd) => (
                <th key={wd} style={headerStyle}>{WEEKDAYS[wd - 1]}</th>
              ))}
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
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
                id: "fullgrid",
                label: "周课表",
                content: renderFullScheduleGrid(),
              },
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
                label: "本周概览",
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

        {/* ========== Stack 单列：学期管理 + 一键教务导入 ========== */}
        <Stack gap="md">

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

        </Stack>

        {/* ========== Stack 单列：手动添加课程 + 表格粘贴导入 ========== */}
        <Stack gap="md">

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

          {/* 文件上传导入 */}
          <Card title="上传课表文件">
            <Stack gap="xs">
              <Tip>
                支持 .xlsx（Excel 2007+，推荐） / .csv / .json / .ics。选择文件后会自动识别格式、提取课程名/时间/教师/地点。
                .xls 旧格式请用 Excel 另存为 .xlsx 后上传。
              </Tip>
              <Inline gap="xs">
                <input
                  type="file"
                  accept=".xlsx,.xls,.csv,.json,.ics"
                  onChange={onFileInputChange}
                  style={{
                    border: "1px dashed var(--border-color, rgba(0,0,0,0.2))",
                    borderRadius: 6,
                    padding: "8px 12px",
                    cursor: "pointer",
                    flex: 1,
                  }}
                />
                {fileUploadLoading ? (
                  <StatusBadge tone="info">上传中...</StatusBadge>
                ) : fileUploadName ? (
                  <StatusBadge tone="success">{fileUploadName}</StatusBadge>
                ) : null}
              </Inline>
              <Text style={{ fontSize: 11, opacity: 0.6 }}>
                或直接把 Excel/教务系统表格内容复制到下方「表格粘贴导入」文本框
              </Text>
            </Stack>
          </Card>

          {/* 高级工具：清空 + 诊断 */}
          <Card title="高级工具">
            <Stack gap="md">
              <Warning>从错误的来源导入了垃圾数据？点下面的按钮一键清空重来。</Warning>

              <Inline gap="xs">
                <Button
                  tone="danger"
                  onClick={() => doClearSchedule(false)}
                  disabled={dangerLoading || !activeSem}
                >
                  {dangerLoading ? "处理中..." : "清空课表数据（保留学期）"}
                </Button>
                <Button
                  tone="danger"
                  onClick={() => doClearSchedule(true)}
                  disabled={dangerLoading || !activeSem}
                >
                  删除整个学期
                </Button>
                {!activeSem ? (
                  <StatusBadge tone="warning">没有当前学期</StatusBadge>
                ) : null}
              </Inline>

              <Divider />

              <Stack gap="xs">
                <Text style={{ fontSize: 12, opacity: 0.85 }}>
                  上传文件但解析不出课程？试试「预览/诊断」看看程序在文件里检测到了什么。
                  预览只读取文件不会写入数据库。
                </Text>
                <Inline gap="xs">
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={onPreviewFileChange}
                    style={{
                      border: "1px dashed var(--border-color, rgba(0,0,0,0.2))",
                      borderRadius: 6,
                      padding: "8px 12px",
                      cursor: "pointer",
                      flex: 1,
                    }}
                  />
                  {previewLoading ? (
                    <StatusBadge tone="info">分析中...</StatusBadge>
                  ) : previewName ? (
                    <StatusBadge tone="success">{previewName}</StatusBadge>
                  ) : null}
                </Inline>

                {previewResult ? (
                  <div style={{
                    background: "rgba(0,0,0,0.03)",
                    borderRadius: 6,
                    padding: 12,
                    fontSize: 12,
                    maxHeight: 360,
                    overflowY: "auto",
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-all",
                  }}>
                    {previewResult.error ? (
                      <span style={{ color: "#c33" }}>❌ {previewResult.error}</span>
                    ) : (
                      <>
                        <div style={{ fontWeight: 600, marginBottom: 600 / 10000 }}>
                          📊 文件分析结果
                        </div>
                        <div>文件格式: {previewResult.file_format}</div>
                        <div>矩阵大小: {previewResult.matrix_rows} 行 × {previewResult.matrix_cols} 列</div>
                        <div>课表网格检测: {previewResult.grid_detected ? "✅ 已检测到" : "❌ 未检测到（表头不含星期几？）"}</div>
                        {previewResult.grid_info ? (
                          <>
                            <div style={{ marginTop: 6, fontWeight: 600 }}>网格定位:</div>
                            <div>  数据起始行: 第 {previewResult.grid_info.top_row} 行</div>
                            <div>  数据结束行: 第 {previewResult.grid_info.bottom_row} 行</div>
                            <div>  星期列: {JSON.stringify(previewResult.grid_info.weekday_cols)}</div>
                            <div>  节次列: {previewResult.grid_info.period_col ?? "未检测到"}</div>
                          </>
                        ) : null}
                        <div style={{ marginTop: 6, fontWeight: 600 }}>
                          解析课程数: {previewResult.courses_found}
                        </div>
                        {previewResult.courses && previewResult.courses.length > 0 ? (
                          <div>
                            {previewResult.courses.slice(0, 20).map((c: any, i: number) => (
                              <div key={i} style={{ marginTop: 3 }}>
                                • {c.name}
                                {c.teacher ? `  教师=${c.teacher}` : ""}
                                {c.location ? `  地点=${c.location}` : ""}
                              </div>
                            ))}
                            {previewResult.courses.length > 20 ? (
                              <div style={{ opacity: 0.6 }}>
                                ...还有 {previewResult.courses.length - 20} 门
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        {previewResult.raw_grid_preview && previewResult.raw_grid_preview.length > 0 ? (
                          <>
                            <div style={{ marginTop: 8, fontWeight: 600 }}>原始网格预览:</div>
                            {previewResult.raw_grid_preview.map((row: string[], ri: number) => (
                              <div key={ri} style={{ opacity: 0.75 }}>
                                {row.join(" | ")}
                              </div>
                            ))}
                          </>
                        ) : null}
                      </>
                    )}
                  </div>
                ) : null}
              </Stack>
            </Stack>
          </Card>

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

        </Stack>

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

        {/* ========== Stack 单列：作业管理 + 考试管理 ========== */}
        <Stack gap="md">

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

        </Stack>
      </Stack>
    </Page>
  )
}
