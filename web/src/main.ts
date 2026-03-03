import { createApp } from 'vue'
import { createPinia } from 'pinia'
import 'virtual:uno.css'
import './assets/theme.css'
import './assets/avocet.css'
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')
