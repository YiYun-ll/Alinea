import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './style.css'
import './styles/motion.css'
import 'pdfjs-dist/web/pdf_viewer.css'

createApp(App).use(createPinia()).use(router).mount('#app')
