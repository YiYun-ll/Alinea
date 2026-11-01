<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { History, LoaderCircle, Sparkles, Trash2 } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { useRulesStore } from '../stores/rules'
import { useInspectionStore } from '../stores/inspection'
import { useRepairStore } from '../stores/repair'
import { usePreviewStore } from '../stores/preview'
import { useJobStore } from '../stores/job'
import { useAgentStore } from '../stores/agent'
import AgentPanel from '../components/AgentPanel.vue'
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
const agent = useAgentStore()
const confirmDialog = ref<InstanceType<typeof ConfirmDialog> | null>(null)
const agentDialog = ref<HTMLDialogElement | null>(null)
const loadedProjectId = ref<string | null>(null)
const agentOpen = ref(false)
const isMobile = ref(false)
const projectId = computed(() => String(route.params.id))
const syncLabel = computed(() => jobs.connectionStatus === 'error' ? '连接重试' : jobs.activeJobs.length ? '正在同步' : '已保存')
let mobileQuery: MediaQueryList | null = null
let modalOpen = false

function synchronizeAgentDialog(): void {
  const dialog = agentDialog.value
  if (!dialog) return
  if (isMobile.value) {
    if (agentOpen.value && !dialog.open) {
      dialog.showModal()
      modalOpen = true
    } else if (!agentOpen.value && dialog.open) {
      dialog.close()
    }
  } else {
    if (dialog.open && modalOpen) dialog.close()
    if (!dialog.open) dialog.show()
    modalOpen = false
  }
}

function closeAgent(): void {
  if (isMobile.value && agentDialog.value?.open) agentDialog.value.close()
  else agentOpen.value = false
}

async function loadWorkspace(): Promise<void> {
  const id = projectId.value
  jobs.stopAll()
  agentOpen.value = false
  if (project.projectId !== id) {
    rules.reset()
    inspection.reset()
    repair.reset()
    preview.clear()
    agent.reset()
  }
  loadedProjectId.value = null
  try {
    await project.load(id)
    if (projectId.value !== id) return
    loadedProjectId.value = id
    jobs.restore(id)
    await agent.load(id)
  } catch {
    if (projectId.value === id) loadedProjectId.value = null
  }
}

function handleMobileChange(event: MediaQueryListEvent): void {
  isMobile.value = event.matches
}

watch(projectId, () => { void loadWorkspace() }, { immediate: true })
watch([agentOpen, isMobile, loadedProjectId], () => { void nextTick(synchronizeAgentDialog) })
onMounted(() => {
  mobileQuery = window.matchMedia('(max-width: 960px)')
  isMobile.value = mobileQuery.matches
  mobileQuery.addEventListener('change', handleMobileChange)
  void nextTick(synchronizeAgentDialog)
})
onBeforeUnmount(() => {
  jobs.stopAll()
  agent.reset()
  mobileQuery?.removeEventListener('change', handleMobileChange)
  agentDialog.value?.close()
})

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
        <div class="project-identity"><strong>{{ project.project.name }}</strong></div>
        <div class="button-group project-actions">
          <span class="project-sync" :data-state="jobs.connectionStatus" role="status"><span class="status-dot" aria-hidden="true" />{{ syncLabel }}</span>
          <RouterLink class="button button-ghost button-small" :to="`/projects/${projectId}/history`"><History :size="15" aria-hidden="true" /> 任务记录</RouterLink>
          <button type="button" class="button button-ghost button-small agent-toggle" aria-label="打开智能体" :aria-expanded="agentOpen" @click="agentOpen = true"><Sparkles :size="15" aria-hidden="true" /></button>
          <button type="button" class="button button-ghost button-small project-delete" aria-label="删除项目" @click="confirmDialog?.open()"><Trash2 :size="14" aria-hidden="true" /></button>
        </div>
      </div>
      <WorkflowRail />
      <ErrorNotice v-if="project.error" :message="project.error" />
      <div class="project-workspace">
        <div class="project-main"><RouterView /></div>
        <dialog ref="agentDialog" class="agent-dialog" aria-label="Alinea 智能体" @close="agentOpen = false; modalOpen = false">
          <AgentPanel :project-id="projectId" :mobile="isMobile" @close="closeAgent" />
        </dialog>
      </div>
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

<style scoped>
.project-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 350px; align-items: start; }
.project-main { min-inline-size: 0; }
.agent-dialog { position: fixed; inset-block: 72px 0; inset-inline: auto 0; inline-size: min(350px, 100%); max-inline-size: 100%; block-size: calc(100dvh - 72px); max-block-size: 100dvh; padding: 0; margin: 0; color: #29394e; background: #fff; border: 0; overscroll-behavior: contain; }
.agent-dialog::backdrop { overflow: hidden; background: #29394e55; overscroll-behavior: contain; }
.agent-dialog:modal { overscroll-behavior: contain; }
.agent-toggle { display: none; }
@media (max-width: 1400px) {
  .project-workspace { grid-template-columns: minmax(0, 1fr) 320px; }
  .agent-dialog { inline-size: min(320px, 100%); }
}
@media (max-width: 960px) {
  .project-workspace { display: block; }
  .agent-toggle { display: inline-flex; }
  .agent-dialog { inset-block-start: 0; inline-size: min(390px, 100%); block-size: 100dvh; box-shadow: -20px 0 50px #29394e24; }
}
@media (prefers-reduced-motion: no-preference) {
  .agent-dialog[open] { animation: agent-enter .2s ease-out; }
}
@keyframes agent-enter { from { opacity: 0; transform: translateX(18px); } to { opacity: 1; transform: translateX(0); } }
</style>
