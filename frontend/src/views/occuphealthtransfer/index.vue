<template>
  <section class="page" data-module="occuphealthtransfer">
    <header class="page-head">
      <div>
        <h2>岗位异动登记</h2>
        <p class="page-desc">职业健康判定落下的异动待办在这里跟踪，落实调岗后才销号。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出岗位异动清单</button>
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
        <span>姓名 / 异动编号</span>
        <input v-model="keyword" placeholder="按姓名或异动编号检索" />
      </label>
      <label class="filter-item">
        <span>异动状态</span>
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
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无岗位异动待办</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条岗位异动记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/occuphealthtransfer'
const columns = ["异动编号", "姓名", "人员编号", "原岗位类别", "触发结论", "建议措施", "来源档案编号", "登记日期", "异动状态"]
const actions = ["落实异动", "暂缓异动"]
const statuses = ["待落实", "已落实", "暂缓"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref([{ label: "异动待办", value: 0 }, { label: "已落实", value: 0 }, { label: "暂缓", value: 0 }])
const errorMessage = ref('')
const noticeMessage = ref('')
const keyword = ref('')
const status = ref('')

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = (await response.json()) as { ok: boolean; message: string }
    if (!result.ok) {
      throw new Error(result.message)
    }
    noticeMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '岗位异动操作失败'
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
      throw new Error('岗位异动列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: "异动待办", value: rows.value.filter((row) => row.status === '待落实').length },
      { label: "已落实", value: rows.value.filter((row) => row.status === '已落实').length },
      { label: "暂缓", value: rows.value.filter((row) => row.status === '暂缓').length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '岗位异动列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.notice-text { color: #067647; }
</style>
