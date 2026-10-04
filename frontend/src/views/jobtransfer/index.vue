<template>
  <section class="page" data-module="jobtransfer">
    <header class="page-head">
      <div>
        <h2>岗位异动登记</h2>
        <p class="page-desc">
          职业健康判定为职业禁忌/职业病的自动生成调岗待办并停用对应资质；
          调岗完成需填写新岗位类别，健康监护侧待办同步闭环。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">手工登记异动</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>人员编号/姓名</span>
        <input v-model="filters.keyword" placeholder="按人员编号或姓名检索" />
      </label>
      <label class="filter-item">
        <span>异动状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option value="待调岗">待调岗</option>
          <option value="已调岗">已调岗</option>
          <option value="已撤销">已撤销</option>
        </select>
      </label>
      <label class="filter-item check">
        <input v-model="filters.pending_only" type="checkbox" /> 只看待调岗
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr><th v-for="column in columns" :key="column">{{ column }}</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-pending': row.pending }">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <template v-if="row.status === '待调岗'">
              <button class="link" type="button" @click="openComplete(row)">完成调岗</button>
              <button class="link danger-link" type="button" @click="cancelRow(row)">撤销</button>
            </template>
            <span v-else class="muted-text">已闭环</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无岗位异动记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条异动记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal">
        <h3>手工登记岗位异动</h3>
        <p class="modal-hint">职业健康判定产生的异动由系统自动开单，这里只登记普通调岗。</p>
        <label class="form-line"><span>人员编号 *</span><input v-model="createForm.人员编号" /></label>
        <label class="form-line"><span>姓名 *</span><input v-model="createForm.姓名" /></label>
        <label class="form-line"><span>原岗位类别 *</span><input v-model="createForm.原岗位类别" /></label>
        <label class="form-line"><span>新岗位类别</span><input v-model="createForm.新岗位类别" placeholder="确定后可在完成调岗时补填" /></label>
        <label class="form-line"><span>异动原因 *</span><input v-model="createForm.异动原因" /></label>
        <label class="form-line"><span>申请日期</span><input v-model="createForm.申请日期" type="date" /></label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">登记</button>
        </div>
      </div>
    </div>

    <div v-if="completeTarget" class="modal-mask" @click.self="completeTarget = null">
      <div class="modal">
        <h3>完成调岗 · {{ completeTarget.姓名 }}</h3>
        <p v-if="completeTarget.档案id" class="modal-hint">
          来源：职业健康监护判定（体检日期 {{ completeTarget.体检日期 }}）。
          {{ completeTarget.证书处置 }}
        </p>
        <label class="form-line"><span>原岗位类别</span><input :value="completeTarget.原岗位类别" disabled /></label>
        <label class="form-line">
          <span>新岗位类别 *</span><input v-model="completeForm.新岗位类别" placeholder="调离接害岗位后的岗位" />
        </label>
        <label class="form-line">
          <span>完成日期 *</span><input v-model="completeForm.完成日期" type="date" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="completeTarget = null">取消</button>
          <button class="btn primary" type="button" @click="submitComplete">确认调岗完成</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/jobtransfer'
const columns = [
  '异动编号', '人员编号', '姓名', '原岗位类别', '新岗位类别', '异动原因',
  '体检日期', '申请日期', '完成日期', '证书处置', 'status',
]

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const messageOk = ref(true)
const filters = reactive({ keyword: '', status: '', pending_only: false })

const showCreate = ref(false)
const completeTarget = ref<Row | null>(null)
const createForm = reactive<Record<string, string>>({
  人员编号: '', 姓名: '', 原岗位类别: '', 新岗位类别: '', 异动原因: '', 申请日期: '',
})
const completeForm = reactive({ 新岗位类别: '', 完成日期: '' })

const stats = computed(() => [
  { label: '本页记录', value: rows.value.length },
  { label: '待调岗', value: rows.value.filter((r) => r.status === '待调岗').length },
  { label: '职业禁忌来源', value: rows.value.filter((r) => r.档案id).length },
  { label: '已调岗', value: rows.value.filter((r) => r.status === '已调岗').length },
])

function flash(text: string, ok = true) {
  message.value = text
  messageOk.value = ok
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.pending_only = false
  void reload()
}

async function reload() {
  message.value = ''
  const params = new URLSearchParams()
  if (filters.keyword) params.set('keyword', filters.keyword)
  if (filters.status) params.set('status', filters.status)
  if (filters.pending_only) params.set('pending_only', 'true')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('岗位异动列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    flash(error instanceof Error ? error.message : '岗位异动列表读取失败', false)
  }
}

function openCreate() {
  Object.assign(createForm, {
    人员编号: '', 姓名: '', 原岗位类别: '', 新岗位类别: '', 异动原因: '', 申请日期: '',
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
    flash(error instanceof Error ? error.message : '登记失败', false)
  }
}

function openComplete(row: Row) {
  completeTarget.value = row
  completeForm.新岗位类别 = row.新岗位类别 || ''
  completeForm.完成日期 = ''
}

async function submitComplete() {
  if (!completeTarget.value) return
  try {
    const response = await request(`${ENDPOINT}/${completeTarget.value.id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ values: { ...completeForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      flash(payload.message, false)
      return
    }
    completeTarget.value = null
    flash(payload.message)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '调岗完成失败', false)
  }
}

async function cancelRow(row: Row) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/cancel`, { method: 'POST' })
    const payload = await response.json()
    flash(payload.message, payload.ok)
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '撤销失败', false)
  }
}

onMounted(reload)
</script>

<style scoped>
.check { display: flex; align-items: center; gap: 4px; }
.row-pending { background: #fff8eb; }
.muted-text { color: var(--muted); }
.ok-text { color: #027a48; }
.danger-link { color: #b42318; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.modal {
  background: #fff; border-radius: 10px; padding: 18px 20px; width: 460px;
  max-height: 88vh; overflow: auto;
}
.modal h3 { margin: 0 0 8px; }
.modal-hint { color: var(--muted); font-size: 12px; margin: 0 0 10px; }
.form-line { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; }
.form-line > span { width: 110px; color: var(--muted); flex-shrink: 0; }
.form-line input { flex: 1; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
.form-line input:disabled { background: #f1f5f9; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
</style>
