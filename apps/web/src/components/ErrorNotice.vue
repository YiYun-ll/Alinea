<script setup lang="ts">
import { CircleAlert, RotateCcw } from 'lucide-vue-next'

defineProps<{ message: string; retryLabel?: string }>()
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="notice notice-error" role="alert">
    <CircleAlert :size="20" class="mt-0.5 shrink-0" aria-hidden="true" />
    <div class="min-w-0 flex-1">
      <strong>操作未完成</strong>
      <p class="mb-0 mt-1">{{ message }}</p>
      <button v-if="retryLabel" type="button" class="button button-secondary button-small mt-3" @click="emit('retry')">
        <RotateCcw :size="14" aria-hidden="true" /> {{ retryLabel }}
      </button>
    </div>
  </div>
</template>
