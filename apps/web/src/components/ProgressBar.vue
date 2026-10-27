<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  value?: number | null
  max?: number
  label: string
  message?: string
  compact?: boolean
}>(), { value: null, max: 100, message: '', compact: false })

const normalized = computed(() => props.value === null ? null : Math.min(props.max, Math.max(0, props.value)))
const progressValue = computed(() => normalized.value ?? undefined)
const indeterminate = computed(() => normalized.value === null)
</script>

<template>
  <div class="job-progress" :class="{ 'job-progress-compact': compact }">
    <div class="job-progress-heading"><span>{{ label }}</span><span v-if="!indeterminate" class="job-progress-value">{{ normalized }}%</span></div>
    <progress :value="progressValue" :max="max" :aria-label="label" />
    <span v-if="message" class="job-progress-message" role="status">{{ message }}</span>
  </div>
</template>
