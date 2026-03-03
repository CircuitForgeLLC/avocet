import { createApp } from 'vue'
import { createPinia } from 'pinia'
// Self-hosted fonts — no Google Fonts CDN (privacy requirement)
import '@fontsource/fraunces/400.css'
import '@fontsource/fraunces/700.css'
import '@fontsource/atkinson-hyperlegible/400.css'
import '@fontsource/atkinson-hyperlegible/700.css'
import '@fontsource/jetbrains-mono/400.css'
import 'virtual:uno.css'
import './assets/theme.css'
import './assets/avocet.css'
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
