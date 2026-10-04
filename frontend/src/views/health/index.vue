<template>
  <section class="page" data-module="health">
    <header class="page-head">
      <div>
        <h2>职业健康监护档案</h2>
        <p class="page-desc">
          接触粉尘、噪声、有毒有害气体岗位人员一人一档；体检周期按危害因素与累计工龄判定，
          多因素冲突时以更严一档为准。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">新建监护档案</button>
        <button class="btn" type="button" @click="showBackfill = true">纸质体检表回填</button>
        <button class="btn" type="button" @click="refreshStandard">按新标准重排周期</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="rule-box">
      <strong>体检周期判定口径（{{ standard.version }}，全矿唯一一份）：</strong>
      <span v-for="(rule, hazard) in standard.rules" :key="hazard" class="rule-chip">
        {{ hazard }}：累计工龄＜{{ rule.tenure_years }}年 → {{ rule.loose_months }}个月；
        ≥{{ rule.tenure_years }}年 → {{ rule.strict_months }}个月
      </span>
      <span class="rule-note">{{ standard.note }}</span>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>人员编号/姓名</span>
        <input v-model="filters.keyword" placeholder="按人员编号或姓名检索" />
      </label>
      <label class="filter-item">
        <span>危害因素</span>
        <select v-model="filters.hazard">
          <option value="">全部</option>
          <option v-for="h in hazards" :key="h" :value="h">{{ h }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>档案状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option value="在岗监护">在岗监护</option>
          <option value="已归档">已归档</option>
        </select>
      </label>
      <label class="filter-item check">
        <input v-model="filters.pending_only" type="checkbox" /> 只看待办未闭环
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>待办</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-abnormal': row.abnormal }">
          <td v-for="column in columns" :key="column">{{ formatCell(row, column) }}</td>
          <td>
            <span v-for="todo in openTodos(row)" :key="todo.编号" class="todo-tag" :class="todoClass(todo)">
              {{ todo.类型 }}<template v-if="todo.截止日期">（{{ todo.截止日期 }}）</template>
            </span>
            <span v-if="!openTodos(row).length" class="muted-text">无</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">档案明细</button>
            <button
              v-if="row.status !== '已归档'"
              class="link"
              type="button"
              @click="openExam(row)"
            >登记体检</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无监护档案，可先新建</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 份监护档案</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <!-- 建档 -->
    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>新建职业健康监护档案</h3>
        <p class="modal-hint">岗位类别为强制项，岗位类别空着的记录不允许保存。</p>
        <label class="form-line"><span>人员编号 *</span><input v-model="createForm.人员编号" placeholder="如 EMP-1007" /></label>
        <label class="form-line"><span>姓名 *</span><input v-model="createForm.姓名" /></label>
        <label class="form-line"><span>岗位类别 *</span><input v-model="createForm.岗位类别" placeholder="如 掘进工（不允许为空）" /></label>
        <div class="form-line">
          <span>接触危害因素 *</span>
          <label v-for="h in hazards" :key="h" class="check-inline">
            <input v-model="createForm.接触危害因素" :value="h" type="checkbox" /> {{ h }}
          </label>
        </div>
        <label class="form-line"><span>累计工龄（年）*</span><input v-model="createForm.累计工龄" type="number" min="0" step="0.5" /></label>
        <label class="form-line"><span>资质证书编号</span><input v-model="createForm.资质证书编号" placeholder="判职业禁忌时联动停用，可留空" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">保存档案</button>
        </div>
      </div>
    </div>

    <!-- 档案明细 -->
    <div v-if="detail" class="modal-mask wide" @click.self="detail = null">
      <div class="modal wide">
        <h3>档案明细 · {{ detail.档案编号 }} {{ detail.姓名 }}</h3>
        <p class="modal-hint">{{ detail.周期依据 }}</p>
        <div class="detail-grid">
          <span>岗位类别：{{ detail.岗位类别 }}</span>
          <span>接触危害因素：{{ (detail.接触危害因素 || []).join('、') }}</span>
          <span>累计工龄：{{ detail.累计工龄 }} 年</span>
          <span>体检周期：每 {{ detail.体检周期 }} 个月</span>
          <span>档案状态：{{ detail.status }}</span>
          <span>适用版本：{{ detail.适用标准版本 }}</span>
        </div>

        <h4>体检记录（含历史纸质回填，已存档结论不随新标准重算）</h4>
        <table class="data-table inner">
          <thead>
            <tr><th>序号</th><th>体检日期</th><th>类型</th><th>机构</th><th>结论</th><th>来源</th><th>标准版本</th><th>复查</th></tr>
          </thead>
          <tbody>
            <tr v-for="exam in detail.exams" :key="exam.序号">
              <td>{{ exam.序号 }}</td>
              <td>{{ exam.体检日期 }}</td>
              <td>{{ exam.体检类型 }}</td>
              <td>{{ exam.体检机构 }}</td>
              <td>{{ exam.体检结论 }}</td>
              <td>{{ exam.数据来源 }}</td>
              <td>{{ exam.适用标准版本 }}</td>
              <td>
                <template v-if="exam.体检结论 === '复查'">
                  <span v-if="exam.复查结论">已于 {{ exam.复查日期 }} 填报：{{ exam.复查结论 }}</span>
                  <span v-else class="error-text">待复查，截止 {{ exam.复查截止日 }}</span>
                </template>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <h4>待办事项</h4>
        <table class="data-table inner">
          <thead>
            <tr><th>编号</th><th>类型</th><th>截止日期</th><th>状态</th><th>说明</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="todo in detail.todos" :key="todo.编号">
              <td>{{ todo.编号 }}</td>
              <td>{{ todo.类型 }}</td>
              <td>{{ todo.截止日期 || '—' }}</td>
              <td :class="todo.状态 === '待办' ? 'error-text' : 'muted-text'">{{ todo.状态 }}</td>
              <td>{{ todo.说明 }}{{ todo.关闭说明 ? `（${todo.关闭说明}）` : '' }}</td>
              <td>
                <button
                  v-if="todo.状态 === '待办' && (todo.类型 === '复查' || todo.类型 === '职业病诊断')"
                  class="link"
                  type="button"
                  @click="openFollowup(todo)"
                >填报{{ todo.类型 === '复查' ? '复查' : '诊断' }}结论</button>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button
            v-if="detail.status !== '已归档'"
            class="btn primary"
            type="button"
            @click="openExam(detail); detail = null"
          >登记体检</button>
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 登记体检 -->
    <div v-if="examTarget" class="modal-mask" @click.self="examTarget = null">
      <div class="modal">
        <h3>登记体检 · {{ examTarget.姓名 }}</h3>
        <label class="form-line">
          <span>体检日期 *</span><input v-model="examForm.体检日期" type="date" />
        </label>
        <label class="form-line">
          <span>体检类型 *</span>
          <select v-model="examForm.体检类型">
            <option v-for="t in examTypes" :key="t" :value="t">{{ t }}</option>
          </select>
        </label>
        <label class="form-line"><span>体检机构 *</span><input v-model="examForm.体检机构" /></label>
        <label class="form-line">
          <span>体检结论 *</span>
          <select v-model="examForm.体检结论">
            <option v-for="c in conclusions" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="form-line"><span>处理意见</span><input v-model="examForm.处理意见" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="examTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitExam">提交判定</button>
        </div>
      </div>
    </div>

    <!-- 填报复查/诊断结论 -->
    <div v-if="followup" class="modal-mask" @click.self="followup = null">
      <div class="modal">
        <h3>填报{{ followup.类型 }}结论</h3>
        <p class="modal-hint">结论不填报，该待办会一直挂在待办列表里。</p>
        <label class="form-line">
          <span>结论日期 *</span><input v-model="followupForm.结论日期" type="date" />
        </label>
        <label class="form-line">
          <span>{{ followup.类型 === '复查' ? '复查结论' : '诊断结论' }} *</span>
          <select v-model="followupForm.随访结论">
            <option v-for="c in followupOptions" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="followup = null">取消</button>
          <button class="btn primary" type="button" @click="submitFollowup">提交并关闭待办</button>
        </div>
      </div>
    </div>

    <!-- 纸质回填 -->
    <div v-if="showBackfill" class="modal-mask wide" @click.self="showBackfill = false">
      <div class="modal wide">
        <h3>历史纸质体检表回填</h3>
        <p class="modal-hint">
          按体检日期升序统一落档，可乱序粘贴；只存档，不补触发待办、不停用资质；
          历史结论按当时标准保留，新口径不重算。每行一条，字段用逗号分隔：
          人员编号,体检日期,体检类型,体检机构,体检结论。
        </p>
        <textarea v-model="backfillText" class="backfill-input" rows="8"
          placeholder="EMP-1001,2023-05-01,在岗期间,矿务局职业病防治院,目前未见异常&#10;EMP-1002,2022-11-08,在岗期间,矿务局职业病防治院,复查"></textarea>
        <div v-if="backfillResult" class="backfill-result">
          <p :class="backfillResult.errors.length ? 'error-text' : 'ok-text'">{{ backfillResult.message }}</p>
          <ul v-if="backfillResult.errors.length">
            <li v-for="(err, i) in backfillResult.errors" :key="i" class="error-text">{{ err }}</li>
          </ul>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showBackfill = false">关闭</button>
          <button class="btn primary" type="button" @click="submitBackfill">按体检日期顺序回填</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Todo = {
  编号: string
  类型: string
  截止日期: string
  状态: string
  说明: string
  关闭说明: string
}
type Row = Record<string, any>

const ENDPOINT = '/api/health-archive'
const columns = [
  '档案编号', '人员编号', '姓名', '岗位类别', '接触危害因素', '累计工龄',
  '体检周期', '最新结论', '下次体检日期', '适用标准版本', 'status',
]
const hazards = ['粉尘', '噪声', '有毒有害气体']
const examTypes = ['上岗前', '在岗期间', '离岗时']
const conclusions = ['目前未见异常', '复查', '职业禁忌', '疑似职业病', '职业病']
const recheckOptions = ['复查合格', '职业禁忌', '疑似职业病']
const diagnosisOptions = ['确诊职业病', '排除职业病']

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(true)
const filters = reactive({ keyword: '', hazard: '', status: '', pending_only: false })

const showCreate = ref(false)
const detail = ref<Row | null>(null)
const examTarget = ref<Row | null>(null)
const followup = ref<Todo | null>(null)
const showBackfill = ref(false)
const backfillText = ref('')
const backfillResult = ref<{ message: string; errors: string[] } | null>(null)

const createForm = reactive<Record<string, any>>({
  人员编号: '', 姓名: '', 岗位类别: '', 接触危害因素: [] as string[],
  累计工龄: '', 资质证书编号: '',
})
const examForm = reactive({ 体检日期: '', 体检类型: '在岗期间', 体检机构: '', 体检结论: '目前未见异常', 处理意见: '' })
const followupForm = reactive({ 结论日期: '', 随访结论: '' })

const standard = ref<{ version: string; rules: Record<string, any>; note: string }>({
  version: '', rules: {}, note: '',
})

const followupOptions = computed(() =>
  followup.value?.类型 === '职业病诊断' ? diagnosisOptions : recheckOptions
)

const stats = computed(() => {
  const open = rows.value.filter((r) => r.pending)
  const recheck = rows.value.filter((r) =>
    (r.todos || []).some((t: Todo) => t.状态 === '待办' && t.类型 === '复查')
  )
  const transfer = rows.value.filter((r) =>
    (r.todos || []).some((t: Todo) => t.状态 === '待办' && t.类型 === '岗位异动')
  )
  return [
    { label: '本页在档人员', value: rows.value.length },
    { label: '待办未闭环', value: open.length },
    { label: '待复查', value: recheck.length },
    { label: '待调岗（职业禁忌）', value: transfer.length },
  ]
})

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function formatCell(row: Row, column: string) {
  if (column === '接触危害因素') return (row[column] || []).join('、')
  if (column === '体检周期') return `每 ${row[column]} 个月`
  return row[column] ?? '—'
}

function openTodos(row: Row): Todo[] {
  return (row.todos || []).filter((t: Todo) => t.状态 === '待办')
}

function todoClass(todo: Todo) {
  if (todo.类型 === '复查' || todo.类型 === '岗位异动' || todo.类型 === '职业病诊断') return 'danger'
  return ''
}

function resetFilters() {
  filters.keyword = ''
  filters.hazard = ''
  filters.status = ''
  filters.pending_only = false
  void reload()
}

async function reload() {
  message.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.hazard) params.set('hazard', filters.hazard)
  if (filters.status) params.set('status', filters.status)
  if (filters.pending_only) params.set('pending_only', 'true')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('监护档案列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    flash(error instanceof Error ? error.message : '监护档案列表读取失败', false)
  }
}

async function loadStandard() {
  try {
    const response = await request(`${ENDPOINT}/standard`)
    if (response.ok) standard.value = await response.json()
  } catch {
    /* 口径加载失败不阻塞列表 */
  }
}

function openCreate() {
  Object.assign(createForm, {
    人员编号: '', 姓名: '', 岗位类别: '', 接触危害因素: [],
    累计工龄: '', 资质证书编号: '',
  })
  showCreate.value = true
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      flash(payload.message, false)
      return
    }
    showCreate.value = false
    flash(payload.message)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '建档失败', false)
  }
}

async function openDetail(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('档案明细读取失败')
    detail.value = await response.json()
  } catch (error) {
    flash(error instanceof Error ? error.message : '档案明细读取失败', false)
  }
}

function openExam(row: Row) {
  examTarget.value = row
  Object.assign(examForm, {
    体检日期: '', 体检类型: '在岗期间', 体检机构: '', 体检结论: '目前未见异常', 处理意见: '',
  })
}

async function submitExam() {
  if (!examTarget.value) return
  try {
    const response = await request(`${ENDPOINT}/${examTarget.value.id}/exams`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...examForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      flash(payload.message, false)
      return
    }
    examTarget.value = null
    flash(payload.message)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '体检登记失败', false)
  }
}

function openFollowup(todo: Todo) {
  followup.value = todo
  followupForm.结论日期 = ''
  followupForm.随访结论 = ''
}

async function submitFollowup() {
  if (!detail.value || !followup.value) return
  const archiveId = detail.value.id
  try {
    const response = await request(`${ENDPOINT}/${archiveId}/followups`, {
      method: 'POST',
      body: JSON.stringify({ values: { 待办编号: followup.value.编号, ...followupForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      flash(payload.message, false)
      return
    }
    followup.value = null
    detail.value = null
    flash(payload.message)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '结论填报失败', false)
  }
}

async function submitBackfill() {
  backfillResult.value = null
  const records = backfillText.value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [人员编号, 体检日期, 体检类型, 体检机构, 体检结论] = line.split(',').map((s) => s.trim())
      return { 人员编号, 体检日期, 体检类型, 体检机构, 体检结论 }
    })
  if (!records.length) {
    backfillResult.value = { message: '没有可回填的行', errors: [] }
    return
  }
  try {
    const response = await request(`${ENDPOINT}/backfill`, {
      method: 'POST',
      body: JSON.stringify({ values: { records } }),
    })
    const payload = await response.json()
    backfillResult.value = {
      message: payload.message,
      errors: payload.entry?.errors ?? [],
    }
    if (payload.ok) backfillText.value = ''
    await reload()
  } catch (error) {
    backfillResult.value = {
      message: error instanceof Error ? error.message : '回填失败',
      errors: [],
    }
  }
}

async function refreshStandard() {
  try {
    const response = await request(`${ENDPOINT}/standard/refresh`, { method: 'POST' })
    const payload = await response.json()
    flash(payload.message, payload.ok)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '标准换版失败', false)
  }
}

onMounted(() => {
  void loadStandard()
  void reload()
})
</script>

<style scoped>
.rule-box {
  background: #fff; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; margin-bottom: 12px; font-size: 13px;
  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
}
.rule-chip { background: #eef4ff; border-radius: 4px; padding: 2px 8px; }
.rule-note { color: var(--muted); }
.check { display: flex; align-items: center; gap: 4px; }
.row-abnormal { background: #fff5f5; }
.todo-tag { display: inline-block; font-size: 12px; background: #f1f5f9; border-radius: 4px; padding: 1px 6px; margin-right: 4px; }
.todo-tag.danger { background: #fee4e2; color: #b42318; }
.muted-text { color: var(--muted); }
.ok-text { color: #027a48; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: #fff; border-radius: 10px; padding: 18px 20px; width: 460px;
  max-height: 88vh; overflow: auto;
}
.modal.wide { width: 880px; }
.modal h3 { margin: 0 0 8px; }
.modal h4 { margin: 14px 0 6px; font-size: 14px; }
.modal-hint { color: var(--muted); font-size: 12px; margin: 0 0 10px; }
.form-line { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; }
.form-line > span { width: 110px; color: var(--muted); flex-shrink: 0; }
.form-line input, .form-line select { flex: 1; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
.check-inline { display: flex; align-items: center; gap: 4px; margin-right: 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 16px; font-size: 13px; margin-bottom: 8px; }
.data-table.inner { font-size: 12px; }
.backfill-input { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-family: monospace; }
.backfill-result { margin-top: 8px; font-size: 13px; }
</style>
