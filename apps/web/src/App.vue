<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { AlignLeft, FilePlus2, FolderOpen } from 'lucide-vue-next'
import ToastViewport from './components/ToastViewport.vue'

const route = useRoute()
const announcement = ref('')
const projectId = computed(() => typeof route.params.id === 'string' ? route.params.id : null)

watch(() => route.fullPath, async () => {
  announcement.value = document.title
  await nextTick()
  document.getElementById('main-content')?.focus({ preventScroll: true })
})
</script>

<template>
  <a class="skip-link" href="#main-content">跳至主要内容</a>
  <header class="app-header">
    <RouterLink class="brand" to="/" aria-label="Alinea 首页">
      <span class="brand-mark" aria-hidden="true"><AlignLeft :size="21" /></span>
      <span>
        <span class="brand-word">Alinea</span>
      </span>
    </RouterLink>
    <nav class="header-nav" aria-label="主导航">
      <RouterLink v-if="projectId" :to="`/projects/${projectId}/inspection`"><FolderOpen :size="16" aria-hidden="true" /> 当前项目</RouterLink>
      <RouterLink to="/new"><FilePlus2 :size="16" aria-hidden="true" /> 新建检查</RouterLink>
    </nav>
  </header>
  <main id="main-content" tabindex="-1">
    <RouterView v-slot="{ Component }">
      <Transition name="route" mode="out-in">
        <component :is="Component" :key="projectId ?? route.name ?? route.path" />
      </Transition>
    </RouterView>
  </main>
  <ToastViewport />
  <div class="sr-only" aria-live="polite" aria-atomic="true">{{ announcement }}</div>
</template>
