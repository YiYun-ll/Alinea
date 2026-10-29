<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Check, FileText, LoaderCircle } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { errorMessage, formatDate } from '../lib/format'
import ErrorNotice from '../components/ErrorNotice.vue'

const project = useProjectStore()
const router = useRouter()
const demoLoading = ref(false)
const demoError = ref<string | null>(null)

async function openDemo(): Promise<void> {
  if (demoLoading.value) return
  demoLoading.value = true
  demoError.value = null
  try {
    const projectId = await project.createDemo()
    await router.push(`/projects/${projectId}/inspection?setup=1`)
  } catch (error) {
    demoError.value = errorMessage(error, '演示项目创建失败，请稍后重试。')
  } finally {
    demoLoading.value = false
  }
}
</script>

<template>
  <div class="home-page motion-page">
    <section class="home-hero" aria-labelledby="home-title">
      <div class="hero-copy">
        <h1 id="home-title">让好内容，<br />有好排版。</h1>
        <p class="hero-lead">核对 Word 格式，逐项审阅修改。<br />从第一处细节，到最后一页。</p>
        <div class="hero-actions">
          <RouterLink class="button button-primary hero-button" to="/new">开始检查 <ArrowRight :size="17" aria-hidden="true" /></RouterLink>
          <button type="button" class="button button-ghost" :disabled="demoLoading" aria-label="使用真实演示文档" @click="openDemo"><LoaderCircle v-if="demoLoading" class="spinner" :size="16" aria-hidden="true" />{{ demoLoading ? '正在打开…' : '体验演示' }}<ArrowRight v-if="!demoLoading" :size="15" aria-hidden="true" /></button>
        </div>
        <ErrorNotice v-if="demoError" :message="demoError" />
        <p class="hero-footnote">每次修改，经你确认。原稿始终保留。</p>
      </div>
      <div class="document-stage" aria-label="格式审阅示意">
        <div class="sample-sheet" aria-hidden="true">
          <div class="sheet-masthead"><span>ALINEA</span><span>文档审阅</span></div>
          <h2>细节，构成秩序。</h2>
          <p class="sheet-intro">清晰的层次、恰当的留白，<br />让阅读回归内容本身。</p>
          <div class="sample-lines"><i /><i /><i /><i /></div>
          <div class="sample-highlight"><span>统一正文格式</span><span>01</span></div>
          <div class="sample-lines short"><i /><i /><i /></div>
          <div class="sheet-footer"><span>格式审阅示意</span><span>01</span></div>
        </div>
        <div class="sample-change" aria-hidden="true"><span class="change-check"><Check :size="16" /></span><div><strong>正文 · 字号</strong><p><del>10.5 pt</del><ArrowRight :size="13" /><span>12 pt</span></p></div><span class="change-label">修改预览</span></div>
      </div>
    </section>
    <section v-if="project.recentProjects.length" class="recent-section" aria-labelledby="recent-title">
      <div class="section-heading"><h2 id="recent-title">最近文档</h2><RouterLink to="/new" class="text-link">新建检查 <ArrowRight :size="14" aria-hidden="true" /></RouterLink></div>
      <ul class="recent-list">
        <li v-for="item in project.recentProjects" :key="item.project_id">
          <RouterLink :to="`/projects/${item.project_id}/inspection`"><FileText :size="20" aria-hidden="true" /><strong>{{ item.name }}</strong><time>{{ formatDate(item.updated_at) }}</time><ArrowRight :size="16" aria-hidden="true" /></RouterLink>
        </li>
      </ul>
    </section>
    <footer class="home-footer"><span>Alinea</span><p>让每一处排版都有依据。</p><span>DOCX 格式检查与修复</span></footer>
  </div>
</template>

<style scoped>
.home-page { width: min(1280px, 100%); margin-inline: auto; }
.home-hero { min-height: 660px; display: grid; grid-template-columns: 1.05fr 1fr; align-items: center; gap: 60px; padding: 72px 64px 88px; }
.hero-copy h1 { margin: 0 0 28px; font-size: clamp(3rem, 4.7vw, 4.6rem); font-weight: 500; letter-spacing: -.05em; line-height: 1.3; }
.hero-lead { margin: 0 0 32px; color: var(--muted); font-size: 1rem; line-height: 1.95; }
.hero-actions { display: flex; align-items: center; gap: 16px; margin-bottom: 22px; }
.hero-button { min-width: 164px; min-height: 48px; justify-content: space-between; padding-inline: 22px; }
.hero-footnote { margin: 0; color: var(--muted); font-size: .75rem; }
.document-stage { position: relative; padding: 24px 26px 42px; }
.sample-sheet { width: 100%; max-width: 356px; min-height: 438px; padding: 28px 34px 22px; margin: auto; background: var(--white); border: 1px solid var(--line); border-radius: 3px; transform: rotate(-3deg); box-shadow: 0 12px 40px rgb(41 57 78 / 5%); }
.sheet-masthead, .sheet-footer { display: flex; justify-content: space-between; color: var(--muted); font-size: .6rem; letter-spacing: .1em; }
.sheet-masthead { padding-bottom: 18px; border-bottom: 1px solid var(--line); }
.sample-sheet h2 { margin: 32px 0 16px; font-size: 1.45rem; font-weight: 500; }
.sheet-intro { color: var(--muted); font-family: 'SimSun', serif; font-size: .75rem; line-height: 1.9; }
.sample-lines { display: grid; gap: 9px; margin: 22px 0; }
.sample-lines i { display: block; height: 3px; background: #e2e7ef; }
.sample-lines i:last-child { width: 73%; }
.sample-lines.short { margin-bottom: 28px; }
.sample-highlight { display: flex; justify-content: space-between; padding: 9px 10px; margin-inline: -10px; color: var(--accent); background: #edf2f9; border-inline-start: 2px solid var(--accent); font-size: .7rem; }
.sheet-footer { padding-top: 14px; border-top: 1px solid var(--line); }
.sample-change { position: absolute; inset: auto 0 36px auto; display: flex; align-items: center; gap: 14px; min-width: 288px; padding: 18px 22px; background: var(--white); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 8px 24px rgb(41 57 78 / 6%); }
.change-check { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%; color: var(--accent); background: #edf2f9; }
.sample-change strong { font-size: .78rem; font-weight: 500; }
.sample-change p { display: flex; align-items: center; gap: 10px; margin: 6px 0 0; font-size: .75rem; }
.sample-change del, .change-label { color: var(--muted); }
.sample-change p > span { color: var(--accent); }
.change-label { margin-left: auto; font-size: .65rem; }
.recent-section { padding: 0 64px 64px; }
.section-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.section-heading h2 { margin: 0; font-family: inherit; font-size: 1rem; font-weight: 500; }
.recent-list { padding: 0; margin: 0; list-style: none; border-top: 1px solid var(--line); }
.recent-list a { display: flex; align-items: center; gap: 16px; min-height: 72px; padding: 14px 8px; border-bottom: 1px solid var(--line); text-decoration: none; }
.recent-list a:hover { background: var(--white); }
.recent-list strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: .88rem; font-weight: 500; }
.recent-list time { color: var(--muted); font-size: .75rem; }
.recent-list svg { flex-shrink: 0; color: var(--muted); }
.home-footer { display: flex; align-items: center; gap: 20px; padding: 26px 64px; color: var(--muted); border-top: 1px solid var(--line); font-size: .72rem; }
.home-footer p { flex: 1; margin: 0; }
@media (max-width: 900px) { .home-hero { gap: 24px; padding: 52px 32px 64px; min-height: 580px; } .document-stage { padding-inline: 10px; } .sample-sheet { padding-inline: 24px; } .recent-section { padding-inline: 32px; } .home-footer { padding-inline: 32px; } }
@media (max-width: 640px) { .home-hero { grid-template-columns: 1fr; padding: 48px 24px 36px; gap: 24px; } .hero-copy h1 { font-size: 3rem; } .document-stage { width: min(390px, 100%); margin-inline: auto; padding: 16px 18px 30px; } .sample-sheet { min-height: 410px; } .sample-change { min-width: 260px; inset-block-end: 20px; padding: 14px 18px; } .recent-section { padding: 24px 24px 40px; } .recent-list time { display: none; } .home-footer { padding: 24px; flex-wrap: wrap; gap: 8px 16px; } .home-footer > span:last-child { flex-basis: 100%; } }
</style>
