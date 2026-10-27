<script setup lang="ts">
import { Inbox } from 'lucide-vue-next'

withDefaults(defineProps<{ title: string; description?: string }>(), { description: '' })
</script>

<template>
  <div class="empty-state">
    <Inbox :size="30" aria-hidden="true" />
    <strong>{{ title }}</strong>
    <p v-if="description" class="mb-0 max-w-prose">{{ description }}</p>
    <slot />
  </div>
</template>
