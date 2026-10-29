<script setup lang="ts">
import { useId } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

withDefaults(defineProps<{ title: string; description?: string; open: boolean }>(), { description: '' })
const emit = defineEmits<{ toggle: [] }>()
const buttonId = useId()
const panelId = useId()
</script>

<template>
  <div class="disclosure-panel">
    <button :id="buttonId" type="button" class="disclosure-trigger" :aria-expanded="open" :aria-controls="open ? panelId : undefined" @click="emit('toggle')">
      <span><strong>{{ title }}</strong><small v-if="description">{{ description }}</small></span>
      <span class="disclosure-action"><ChevronDown class="disclosure-icon" :size="16" aria-hidden="true" /></span>
    </button>
    <Transition name="fold">
      <section v-if="open" :id="panelId" class="disclosure-region" role="region" :aria-labelledby="buttonId">
        <slot />
      </section>
    </Transition>
  </div>
</template>

<style scoped>
.disclosure-panel { min-width: 0; }
.disclosure-trigger { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; min-height: 48px; padding: 10px 2px; color: #647186; background: transparent; border: 0; text-align: left; }
.disclosure-trigger strong { display: block; color: #29394e; font-size: .85rem; font-weight: 650; }
.disclosure-trigger small { display: block; margin-top: 3px; color: #748095; font-size: .74rem; line-height: 1.55; }
.disclosure-action { display: inline-flex; align-items: center; flex-shrink: 0; gap: 5px; color: #4b6588; font-size: .75rem; }
.disclosure-icon { transition: transform var(--motion-fast) var(--motion-ease-out); }
.disclosure-trigger[aria-expanded='true'] .disclosure-icon { transform: rotate(180deg); }
.disclosure-trigger:hover strong { color: #4b6588; }
.disclosure-region { padding-block: 6px 18px; }
</style>
