import { defineConfig } from 'vite';
export default defineConfig({server:{proxy:{'/api':'http://127.0.0.1:8186','/files':'http://127.0.0.1:8186'}},build:{target:'es2020'}});
