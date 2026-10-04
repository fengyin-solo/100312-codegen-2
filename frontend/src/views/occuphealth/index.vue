<template>
  <section class="page" data-module="occuphealth">
    <header class="page-head">
      <div>
        <h2>职业健康监护</h2>
        <p class="page-desc">按危害因素和累计工龄定体检周期，多条判定冲突时以更严档为准；复查未销号前一直挂在待办。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记体检记录</button>
        <button class="btn" type="button" @click="showBackfill = !showBackfill">历史纸质回填</button>
        <button class="btn" type="button" @click="exportRows">导出监护清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="panel" @submit.prevent="submitCreate">
      <h3 class="panel-title">登记体检记录（岗位类别必填，周期与结论由判定口径自动合并）</h3>
      <div class="filter-bar">
        <label class="filter-item"><span>姓名</span><input v-model="createForm.姓名" required /></label>
        <label class="filter-item"><span>人员编号</span><input v-model="createForm.人员编号" placeholder="关联持证管理" /></label>
        <label class="filter-item"><span>岗位类别</span><input v-model="createForm.岗位类别" required placeholder="不允许为空" /></label>
        <label class="filter-item"><span>接触危害因素</span><input v-model="createForm.接触危害因素" required placeholder="粉尘、噪声、有毒有害气体" /></label>
        <label class="filter-item"><span>累计工龄(年)</span><input v-model="createForm.累计工龄" required type="number" min="0" step="0.5" /></label>
        <label class="filter-item"><span>体检日期</span><input v-model="createForm.体检日期" required type="date" /></label>
        <label class="filter-item">
          <span>体检类别</span>
          <select v-model="createForm.体检类别">
            <option v-for="item in examTypes" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
      </div>
      <div class="filter-bar">
        <label v-for="hazard in hazards" :key="hazard" class="filter-item">
          <span>{{ hazard }}判定</span>
          <select v-model="createForm.detail[hazard]">
            <option value="">未判定</option>
            <option v-for="item in conclusions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>体检结论（无分项判定时必填）</span>
          <select v-model="createForm.体检结论">
            <option value="">请选择</option>
            <option v-for="item in conclusions" :key="item" :value="item">{{ item }}</option>
          </select>
        </label>
        <button class="btn primary" type="submit">提交登记</button>
      </div>
    </form>

    <form v-if="showBackfill" class="panel" @submit.prevent="submitBackfill">
      <h3 class="panel-title">历史纸质体检表回填（每行一条，入库后按体检日期顺序排列，结论保留原口径不重算）</h3>
      <textarea
        v-model="backfillText"
        class="backfill-input"
        rows="5"
        placeholder="姓名,岗位类别,接触危害因素,累计工龄,体检日期,体检结论[,人员编号]&#10;多种危害因素用 / 分隔，例如：张三,采煤工,粉尘/噪声,12,2023-05-11,目前未见异常,EMP-0001"
      ></textarea>
      <div class="filter-bar">
        <button class="btn primary" type="submit">校验并回填</button>
        <span class="panel-hint">任何一条不合格整批退回；岗位类别为空的行不允许保存</span>
      </div>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>姓名 / 档案编号</span>
        <input v-model="keyword" placeholder="按姓名或档案编号检索" />
      </label>
      <label class="filter-item">
        <span>档案状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button v-if="row.status === '待复查'" class="link" type="button" @click="submitReview(row)">登记复查结论</button>
            <button v-if="row.status === '已完成'" class="link" type="button" @click="runAction('归档', row)">归档</button>
            <span v-if="row.status === '已存档'">已封存</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无职业健康监护数据，可先登记体检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条监护档案记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/occuphealth'
const columns = ["档案编号", "姓名", "岗位类别", "接触危害因素", "累计工龄", "体检日期", "体检周期(月)", "下次体检日期", "体检结论", "复查到期日", "判定标准版本", "档案状态"]
const statuses = ["待复查", "已完成", "已存档"]
const conclusions = ["目前未见异常", "其他疾病或异常", "复查", "疑似职业病", "职业禁忌证"]
const hazards = ["粉尘", "噪声", "有毒有害气体"]
const examTypes = ["上岗前", "在岗期间", "离岗时"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: "监护档案", value: 0 }, { label: "待复查", value: 0 }, { label: "职业禁忌/疑似", value: 0 }])
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const status = ref('')
const showCreate = ref(false)
const showBackfill = ref(false)
const backfillText = ref('')

const createForm = ref({
  姓名: '',
  人员编号: '',
  岗位类别: '',
  接触危害因素: '',
  累计工龄: '',
  体检日期: '',
  体检类别: '在岗期间',
  体检结论: '',
  detail: { 粉尘: '', 噪声: '', 有毒有害气体: '' } as Record<string, string>,
})

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function postJson(path: string, values: Record<string, unknown>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify({ values }) })
  return (await response.json()) as { ok: boolean; message: string }
}

async function submitCreate() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const detail = Object.fromEntries(Object.entries(createForm.value.detail).filter(([, v]) => v))
  const values: Record<string, unknown> = { ...createForm.value }
  delete values.detail
  if (Object.keys(detail).length) {
    values.判定明细 = detail
  }
  try {
    const result = await postJson(ENDPOINT, values)
    if (!result.ok) {
      throw new Error(result.message)
    }
    noticeMessage.value = result.message
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '体检记录登记失败'
  }
}

async function submitBackfill() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const lines = backfillText.value.split('\n').map((line) => line.trim()).filter(Boolean)
  if (!lines.length) {
    errorMessage.value = '请按行粘贴历史体检记录'
    return
  }
  try {
    const items = lines.map((line, index) => {
      const parts = line.split(/[,，]/).map((part) => part.trim())
      if (parts.length < 6) {
        throw new Error(`第 ${index + 1} 行字段不足 6 列`)
      }
      const [姓名, 岗位类别, 接触危害因素, 累计工龄, 体检日期, 体检结论, 人员编号] = parts
      return { 姓名, 岗位类别, 接触危害因素, 累计工龄, 体检日期, 体检结论, 人员编号: 人员编号 ?? '' }
    })
    const response = await request(`${ENDPOINT}/backfill`, { method: 'POST', body: JSON.stringify({ items }) })
    const result = (await response.json()) as { ok: boolean; message: string }
    if (!result.ok) {
      throw new Error(result.message)
    }
    noticeMessage.value = result.message
    backfillText.value = ''
    showBackfill.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '历史体检记录回填失败'
  }
}

async function submitReview(row: Row) {
  const conclusion = window.prompt(`登记 ${row.姓名} 的复查结论（${conclusions.filter((item) => item !== '复查').join(' / ')}）`)
  if (!conclusion) {
    return
  }
  await runAction('登记复查结论', row, { 复查结论: conclusion.trim() })
}

async function runAction(action: string, row: Row, extra: Record<string, unknown> = {}) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const result = await postJson(`${ENDPOINT}/${row.id}/actions`, { action, ...extra })
    if (!result.ok) {
      throw new Error(result.message)
    }
    noticeMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '职业健康监护操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (status.value) {
    query.set('status', status.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('监护档案列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: "监护档案", value: total.value },
      { label: "待复查", value: rows.value.filter((row) => row.status === '待复查').length },
      { label: "职业禁忌/疑似", value: rows.value.filter((row) => row.体检结论 === '职业禁忌证' || row.体检结论 === '疑似职业病').length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '监护档案列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel-title { font-size: 13px; margin: 0 0 8px; }
.panel-hint { color: var(--muted); font-size: 12px; }
.backfill-input { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-size: 12px; margin-bottom: 8px; }
.notice-text { color: #067647; }
</style>
