<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { History, LoaderCircle, Trash2 } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useInspectionStore } from '../stores/inspection'
import { useRepairStore } from '../stores/repair'
import { usePreviewStore } from '../stores/preview'
import { useJobStore } from '../stores/job'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import ErrorNotice from '../components/ErrorNotice.vue'
import WorkflowRail from '../components/WorkflowRail.vue'

const route = useRoute()
const router = useRouter()
const project = useProjectStore()
const rules = useRulesStore()
const inspection = useInspectionStore()
const repair = useRepairStore()
const preview = usePreviewStore()
const jobs = useJobStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const loadedProjectId = ref<string | null>(null)
const projectId = computed(() => String(route.params.id))
const syncLabel = computed(() => jobs.connectionStatus === 'error' ? '连接重试' : jobs.activeJobs.length ? '正在同步' : '已保存')

async function loadWorkspace(): Promise<void> {
  const id = projectId.value
  jobs.stopAll()
  if (project.projectId !== id) {
    rules.reset()
    inspection.reset()
    repair.reset()
    preview.clear()
  }
  loadedProjectId.value = null
  try {
    await project.load(id)
    if (projectId.value !== id) return
    loadedProjectId.value = id
    jobs.restore(id)
  } catch {
    if (projectId.value === id) loadedProjectId.value = null
  }
}

watch(projectId, () => { void loadWorkspace() }, { immediate: true })
onBeforeUnmount(() => jobs.stopAll())

async function deleteProject(): Promise<void> {
  try {
    await project.remove()
    await router.push('/')
  } catch {
    confirmDialog.value?.close()
  }
}
</script>

<template>
  <div class="project-layout">
    <template v-if="loadedProjectId === projectId && project.project">
      <div class="project-bar">
        <div class="project-identity">
          <strong>{{ project.project.name }}</strong>
        </div>
        <div class="button-group project-actions">
          <span class="project-sync" :data-state="jobs.connectionStatus" role="status"><span class="status-dot" aria-hidden="true" />{{ syncLabel }}</span>
          <RouterLink class="button button-ghost button-small" :to="`/projects/${projectId}/history`"><History :size="15" aria-hidden="true" /> 任务记录</RouterLink>
          <button type="button" class="button button-ghost button-small project-delete" aria-label="删除项目" @click="confirmDialog?.open()"><Trash2 :size="14" aria-hidden="true" /></button>
        </div>
      </div>
      <WorkflowRail />
      <ErrorNotice v-if="project.error" :message="project.error" />
      <RouterView />
    </template>
    <div v-else-if="project.loading" class="empty-state"><LoaderCircle class="spinner" :size="30" aria-hidden="true" /><strong>正在恢复项目工作区</strong></div>
    <div v-else class="page-container">
      <ErrorNotice :message="project.error ?? '项目不存在或访问凭证已失效。'" retry-label="重新加载" @retry="loadWorkspace" />
      <RouterLink class="button button-secondary" to="/">返回首页</RouterLink>
    </div>
    <ConfirmDialog
      ref="confirmDialog" title="永久删除此项目？" confirm-label="删除项目与文件" :busy="project.deleting" destructive
      description="此操作会删除原稿、修订版、预览、检查记录和任务轨迹，并使既有访问链接失效。删除无法撤销。"
      @confirm="deleteProject"
    />
  </div>
</template>
