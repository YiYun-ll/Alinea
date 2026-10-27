import { createRouter, createWebHashHistory } from 'vue-router'
import HomeView from './views/HomeView.vue'

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView, meta: { title: '文档排版，得以验证' } },
    { path: '/new', name: 'new', component: () => import('./views/NewProjectView.vue'), meta: { title: '新建检查' } },
    {
      path: '/projects/:id', component: () => import('./views/ProjectShell.vue'),
      children: [
        { path: '', redirect: (to) => `/projects/${to.params.id}/rules` },
        { path: 'rules', name: 'rules', component: () => import('./views/RulesView.vue'), meta: { title: '规范审阅' } },
        { path: 'inspection', name: 'inspection', component: () => import('./views/InspectionView.vue'), meta: { title: '检查与选择' } },
        { path: 'repairs', name: 'repairs', component: () => import('./views/RepairsView.vue'), meta: { title: '批准与修复' } },
        { path: 'results/:revisionId', name: 'results', component: () => import('./views/ResultsView.vue'), meta: { title: '报告与下载' } },
        { path: 'history', name: 'history', component: () => import('./views/HistoryView.vue'), meta: { title: '任务与版本' } },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? `${to.meta.title} · Alinea` : 'Alinea'
  document.title = title
})
