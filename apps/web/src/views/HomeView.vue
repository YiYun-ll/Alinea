<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, BookOpenCheck, CheckCircle2, FileSearch, FileText, FlaskConical, LoaderCircle, ShieldCheck } from 'lucide-vue-next'
import { useProjectStore } from '../stores/project'
import { errorMessage, formatDate } from '../lib/format'
import ErrorNotice from '../components/ErrorNotice.vue'

const project = useProjectStore()
const router = useRouter()
const demoLoading = ref(false)
const demoError = ref<string | null>(null)

async function openDemo(): Promise<void> {
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
        <p class="eyebrow">Alinea / Document editing desk</p>
        <h1 id="home-title">排版有据，<br />修改有界。</h1>
        <p class="hero-lead">从明确的格式规范出发，定位 Word 排版偏差，展示证据，并在你批准后生成可复检的修订版本。</p>
        <div class="hero-proof motion-stagger">
          <span><FileSearch :size="18" aria-hidden="true" /> 结构化检查</span>
          <span><ShieldCheck :size="18" aria-hidden="true" /> 独立批准</span>
          <span><BookOpenCheck :size="18" aria-hidden="true" /> 完整复检</span>
        </div>
      </div>
      <div class="hero-stage">
        <div class="hero-stage-grid" aria-hidden="true"></div>
        <aside class="hero-actions motion-card" aria-labelledby="start-title">
          <span class="edition">WORKSPACE · 0.2 MVP</span>
          <h2 id="start-title">开始一次<br />可验证的检查</h2>
          <p>原稿保持不变。规范解析、问题检测与修复执行是三个独立步骤。</p>
          <ErrorNotice v-if="demoError" :message="demoError" />
          <RouterLink class="button button-primary hero-button motion-button" to="/new">上传 DOCX 开始 <ArrowRight :size="17" aria-hidden="true" /></RouterLink>
          <button type="button" class="button button-secondary hero-button motion-button" :disabled="demoLoading" @click="openDemo">
            <LoaderCircle v-if="demoLoading" class="spinner" :size="17" aria-hidden="true" />
            <FlaskConical v-else :size="17" aria-hidden="true" />
            {{ demoLoading ? '正在创建真实演示项目…' : '使用真实演示文档' }}
          </button>
          <small>演示入口调用服务端 `/demo`，文档、规则与检查结果均来自真实后端。</small>
        </aside>
        <div class="hero-evidence motion-card" aria-label="可验证修复流程">
          <span class="evidence-kicker">VERIFIABLE WORKFLOW</span>
          <ol class="evidence-steps">
            <li><span>01</span><div><strong>原稿</strong><small>不可变 DOCX</small></div></li>
            <li><span>02</span><div><strong>定向补丁</strong><small>仅批准属性</small></div></li>
            <li><span>03</span><div><strong>G1–G5</strong><small>独立质量 Gate</small></div></li>
          </ol>
          <span class="evidence-status motion-pulse">可复核</span>
        </div>
      </div>
    </section>

    <ol class="home-workflow motion-stagger" aria-label="产品工作流">
      <li><span>01</span><div><strong>规范有来源</strong><small>预设、文本或 PDF，逐条确认</small></div></li>
      <li><span>02</span><div><strong>问题可定位</strong><small>有效值、目标值与页面证据</small></div></li>
      <li><span>03</span><div><strong>修改需批准</strong><small>只执行白名单格式操作</small></div></li>
      <li><span>04</span><div><strong>结果可复检</strong><small>独立预览、报告与真实下载</small></div></li>
    </ol>

    <section v-if="project.recentProjects.length" class="recent-section" aria-labelledby="recent-title">
      <div class="section-heading">
        <div><p class="eyebrow">Local workspace</p><h2 id="recent-title">继续最近的工作</h2></div>
        <span class="muted small">仅记录此浏览器中的项目入口</span>
      </div>
      <ul class="recent-list motion-stagger">
        <li v-for="item in project.recentProjects" :key="item.project_id">
          <RouterLink class="motion-card" :to="`/projects/${item.project_id}/rules`">
            <FileText :size="22" aria-hidden="true" />
            <span><strong>{{ item.name }}</strong><small>{{ formatDate(item.updated_at) }} · {{ item.project_id }}</small></span>
            <ArrowRight :size="18" aria-hidden="true" />
          </RouterLink>
        </li>
      </ul>
    </section>

    <section class="principles" aria-labelledby="principles-title">
      <p class="eyebrow">Editorial principles</p>
      <h2 id="principles-title">不把推断包装成结论</h2>
      <div class="principle-grid motion-stagger">
        <article class="motion-card"><span>01</span><h3>证据先于高亮</h3><p>只有定位状态为 LOCATED 的问题才绘制页面框。歧义、未定位与渲染失败保留文字证据，不猜测坐标。</p></article>
        <article class="motion-card"><span>02</span><h3>检查不等于修复</h3><p>问题选择只形成修复计划。计划摘要、影响范围和 digest 经独立批准后，才会创建新的候选版本。</p></article>
        <article class="motion-card"><span>03</span><h3>结果必须可复核</h3><p>原版与修订版分别预览，G1–G5 报告呈现结构、文本、资源、白名单与复检结果，并提供真实文件下载。</p></article>
      </div>
      <p class="support-note"><CheckCircle2 :size="17" aria-hidden="true" /> MVP 聚焦常规 DOCX 格式；复杂对象、扫描 PDF 与任意原文改写不在自动修复范围内。</p>
    </section>
  </div>
</template>

<style scoped>
.home-page { position: relative; isolation: isolate; width: min(1440px, 100%); margin-inline: auto; }
.home-hero { position: relative; min-height: min(720px, calc(100dvh - 72px)); display: grid; grid-template-columns: minmax(0, 7fr) minmax(320px, 5fr); background: radial-gradient(ellipse at 88% 18%, rgba(86, 117, 168, .10), transparent 58%), linear-gradient(135deg, #f6f7f9, #fcfdfe); }
.hero-copy { position: relative; z-index: 1; display: flex; flex-direction: column; justify-content: center; padding: clamp(48px, 7vw, 104px); border-right: 1px solid #d8dde5; }
.hero-copy h1 { margin-bottom: 28px; font-size: clamp(3.4rem, 2.2rem + 5vw, 7.2rem); letter-spacing: -.055em; }
.hero-lead { max-width: 37rem; margin-bottom: 36px; color: #536174; font-family: 'Noto Serif SC', 'Source Han Serif SC', serif; font-size: clamp(1.05rem, .95rem + .4vw, 1.3rem); line-height: 1.9; }
.hero-proof { display: flex; flex-wrap: wrap; gap: 18px 28px; color: #465268; font-size: .8125rem; }
.hero-proof span { display: inline-flex; align-items: center; gap: 7px; }
.hero-stage { position: relative; display: grid; align-content: center; padding: clamp(32px, 4vw, 64px); }
.hero-stage-grid { position: absolute; inset: 0; pointer-events: none; opacity: .45; background-image: linear-gradient(#dce4ef 1px, transparent 1px), linear-gradient(90deg, #dce4ef 1px, transparent 1px); background-size: 30px 30px; mask-image: linear-gradient(to bottom, transparent, #000); }
.hero-actions { position: relative; z-index: 2; align-self: center; margin: 0; padding: clamp(24px, 3vw, 40px); background: rgba(252, 253, 254, .97); border: 1px solid #cfd5de; border-top: 4px solid #273449; border-radius: 6px 6px 12px 12px; box-shadow: 0 16px 40px rgba(39, 52, 73, .07); }
.edition { display: block; margin-bottom: 34px; color: #5675a8; font-size: .7rem; letter-spacing: .12em; }
.hero-actions h2 { margin-bottom: 18px; font-size: clamp(1.8rem, 1.4rem + 1.5vw, 2.6rem); }
.hero-actions > p { margin-bottom: 26px; color: #5e6979; }
.hero-button { width: 100%; min-height: 48px; margin-top: 10px; }
.hero-actions > small { display: block; margin-top: 18px; color: #6b7482; line-height: 1.7; }
.hero-evidence { position: absolute; z-index: 3; inset-inline-end: 18px; inset-block-end: -30px; width: min(310px, 88%); padding: 16px 18px; background: rgba(252, 253, 254, .98); border: 1px solid #cfd7e2; border-radius: 10px; box-shadow: 0 14px 36px rgba(39, 52, 73, .12); }
.evidence-kicker { display: block; margin-bottom: 12px; color: #5675a8; font-size: .65rem; letter-spacing: .1em; }
.evidence-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; padding: 0; margin: 0; list-style: none; }
.evidence-steps li { display: flex; align-items: flex-start; gap: 7px; }
.evidence-steps li > span { color: #5675a8; font-size: .62rem; }
.evidence-steps strong, .evidence-steps small { display: block; }
.evidence-steps strong { font-size: .75rem; }
.evidence-steps small { margin-top: 2px; color: #6b7482; font-size: .62rem; }
.evidence-status { position: absolute; inset-block-start: -11px; inset-inline-end: 14px; padding: 2px 8px; color: #1d6c55; background: #edf7f2; border: 1px solid #a7cec0; border-radius: 999px; font-size: .65rem; }
.home-workflow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding: 0; margin: 0; background: #fff; border-block: 1px solid #d8dde5; list-style: none; }
.home-workflow li { display: flex; gap: 12px; padding: 22px 24px; border-right: 1px solid #e1e5eb; }
.home-workflow li:last-child { border-right: 0; }
.home-workflow li > span { color: #5675a8; font-size: .68rem; }
.home-workflow strong, .home-workflow small { display: block; }
.home-workflow strong { font-size: .82rem; }
.home-workflow small { margin-top: 5px; color: #6b7482; font-size: .7rem; line-height: 1.6; }
.recent-section, .principles { padding: clamp(36px, 5vw, 72px) clamp(24px, 6vw, 88px); border-top: 1px solid #d8dde5; content-visibility: auto; contain-intrinsic-size: auto 360px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.section-heading h2, .principles > h2 { margin-bottom: 0; font-size: clamp(1.65rem, 1.4rem + 1vw, 2.25rem); }
.recent-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; padding: 0; margin: 0; list-style: none; }
.recent-list a { display: flex; align-items: center; gap: 14px; padding: 18px; background: #fff; border: 1px solid #d8dde5; border-radius: 8px; text-decoration: none; }
.recent-list a:hover { border-color: #8fa2bf; }
.recent-list a > span { min-width: 0; flex: 1; }
.recent-list strong, .recent-list small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recent-list small { margin-top: 3px; color: #6b7482; }
.principles { background: #fff; }
.principle-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px; margin-top: 40px; }
.principle-grid article { padding: 18px 14px 14px; border: 1px solid transparent; border-top: 2px solid #273449; border-radius: 0 0 8px 8px; }
.principle-grid article > span { color: #5675a8; font-family: 'Noto Serif SC', serif; font-size: .8rem; }
.principle-grid h3 { margin: 16px 0 10px; font-size: 1.2rem; }
.principle-grid p { color: #5e6979; font-size: .875rem; }
.support-note { display: flex; gap: 8px; margin: 32px 0 0; padding-top: 20px; color: #536174; border-top: 1px solid #e1e5eb; font-size: .8125rem; }
@media (max-width: 900px) {
  .home-hero { min-height: auto; grid-template-columns: 1fr; }
  .hero-copy { padding: 56px 24px; border-right: 0; }
  .hero-stage { padding: 0 24px 48px; }
  .hero-evidence { position: relative; inset: auto; width: 100%; margin-top: 18px; }
  .home-workflow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .home-workflow li:nth-child(2) { border-right: 0; }
  .home-workflow li:nth-child(-n+2) { border-bottom: 1px solid #e1e5eb; }
  .recent-list, .principle-grid { grid-template-columns: 1fr; }
  .section-heading { align-items: flex-start; flex-direction: column; }
}
@media (max-width: 600px) {
  .home-workflow { grid-template-columns: 1fr; }
  .home-workflow li { border-right: 0; border-bottom: 1px solid #e1e5eb; }
  .home-workflow li:last-child { border-bottom: 0; }
}
</style>
