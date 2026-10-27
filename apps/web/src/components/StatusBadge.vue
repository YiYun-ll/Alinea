<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, CircleHelp, CircleX, Clock3, TriangleAlert } from 'lucide-vue-next'

const props = defineProps<{ status: string; label?: string }>()

const presentation = computed(() => {
  const status = props.status.toUpperCase()
  if (['PASS', 'SUCCEEDED', 'APPROVED', 'FIXED', 'LOCATED', 'SAFE_SINGLE_TARGET'].includes(status)) return { className: 'status-pass', icon: CircleCheck, text: '通过' }
  if (['FAIL', 'FAILED', 'BLOCKED', 'ERROR', 'STILL_FAILING'].includes(status)) return { className: 'status-danger', icon: CircleX, text: '失败' }
  if (['WARN', 'WARNING', 'PARTIAL', 'AMBIGUOUS', 'NEEDS_REVIEW', 'POSSIBLE_VIOLATION', 'INDETERMINATE'].includes(status)) return { className: 'status-warn', icon: TriangleAlert, text: '需复核' }
  if (['RUNNING', 'QUEUED', 'PENDING', 'CREATED', 'DRAFT', 'PLANNED'].includes(status)) return { className: 'status-info', icon: Clock3, text: '进行中' }
  if (['UNKNOWN', 'UNLOCATED', 'NOT_RENDERED', 'UNSUPPORTED', 'NOT_RUN'].includes(status)) return { className: 'status-neutral', icon: CircleHelp, text: '未确定' }
  return { className: 'status-neutral', icon: CircleHelp, text: status }
})

const labels: Record<string, string> = {
  PASS: '通过', SUCCEEDED: '已完成', APPROVED: '已批准', FIXED: '已修复', LOCATED: '位置已验证',
  FAIL: '未通过', FAILED: '失败', BLOCKED: '已阻断', ERROR: '确认违规', STILL_FAILING: '仍未通过',
  WARN: '警告', WARNING: '警告', PARTIAL: '部分通过', AMBIGUOUS: '位置有歧义', NEEDS_REVIEW: '需人工复核',
  RUNNING: '运行中', QUEUED: '排队中', PENDING: '等待中', CREATED: '已创建', DRAFT: '草案', PLANNED: '已纳入计划',
  UNKNOWN: '无法检测', UNLOCATED: '未定位', NOT_RENDERED: '未渲染', UNSUPPORTED: '不支持', NOT_RUN: '未运行',
  OPEN: '待处理', INFO: '信息', CONFIRMED_VIOLATION: '确认违规', POSSIBLE_VIOLATION: '可能违规',
  SAFE_SINGLE_TARGET: '可定向修复', INDETERMINATE: '无法判定', CANCELLED: '已取消', STALE: '已失效',
}
</script>

<template>
  <span class="status" :class="presentation.className">
    <component :is="presentation.icon" :size="13" aria-hidden="true" />
    {{ label ?? labels[status.toUpperCase()] ?? presentation.text }}
  </span>
</template>
