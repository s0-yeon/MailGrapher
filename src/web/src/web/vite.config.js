import { defineConfig } from 'vite';
import { visualizer } from 'rollup-plugin-visualizer';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  root: __dirname,
  base: '/',
  publicDir: 'public',
  logLevel: 'info',
  clearScreen: false,
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1000,
    sourcemap: process.env.NODE_ENV === 'production' ? 'hidden' : true,
    target: 'es2022',
    rollupOptions: {
      plugins: [
        visualizer({
          filename: 'dist/stats.html',
          open: false,
          gzipSize: true,
          brotliSize: true,
          template: 'treemap'
        })
      ],
      output: {
        manualChunks: {
          'vendor-core': ['bootstrap', '@popperjs/core'],
          'vendor-d3': ['d3']
        },
        assetFileNames: assetInfo => {
          const originalName = assetInfo.names?.[0] ?? '';
          if (/\.(png|jpe?g|svg|gif|tiff|bmp|ico)$/i.test(originalName)) {
            return `images/[name]-[hash][extname]`;
          }
          if (/\.(woff2?|eot|ttf|otf)$/i.test(originalName)) {
            return `fonts/[name]-[hash][extname]`;
          }
          return `assets/[name]-[hash][extname]`;
        },
        chunkFileNames: 'js/[name]-[hash].js',
        entryFileNames: 'js/[name]-[hash].js'
      },
      input: {
        // 홈 (지식그래프 랜딩)
        home: 'production/index.html',
        // My Life 랜딩
        mylife: 'production/mylife.html',
        // 시간 타임라인
        mytime: 'production/mytime.html',
        // 나의 사람들
        mypeople: 'production/mypeople.html',
        // 그래프 시각화
        graph_viz: 'production/graph-viz.html',
        // 메일 통계 요약
        recap: 'production/recap.html',
        // 서치 페이지
        search: 'production/search.html',
        // IMAP 메일 수집
        imap_collect: 'production/imap-collect.html',
        // 로그인 (디자인만, OAuth 연동은 후속 작업)
        login: 'production/login.html'
      }
    },
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
        unsafe_comps: true,
        passes: 3,
        pure_getters: true,
        reduce_vars: true,
        collapse_vars: true,
        dead_code: true,
        unused: true
      },
      mangle: {
        safari10: true
      },
      format: {
        comments: false
      }
    }
  },
  esbuild: {
    target: 'es2022'
  },
  server: {
    open: '/production/index.html',
    port: 3000,
    host: true,
    proxy: {
      '/graph-data': 'http://127.0.0.1:80',
      '/graph-render.js': 'http://127.0.0.1:80',
      '/run-query-async': 'http://127.0.0.1:80',
      '/job-status': 'http://127.0.0.1:80',
      '/high_affinity_person_stats': 'http://127.0.0.1:80',
      '/mail-date-range': 'http://127.0.0.1:80',
      '/mail-exchange-stats': 'http://127.0.0.1:80',
      '/keyword-stats': 'http://127.0.0.1:80',
      '/keyword-by-person-date': 'http://127.0.0.1:80',
      '/mail-stats': 'http://127.0.0.1:80',
      '/mail_sync_stats': 'http://127.0.0.1:80',
      '/mail-summaries': 'http://127.0.0.1:80',
      '/mail-person-emails': 'http://127.0.0.1:80',
      '/mail-person-sent-stats': 'http://127.0.0.1:80',
      '/mail-person-received-stats': 'http://127.0.0.1:80',
      '/user_rating_stats': 'http://127.0.0.1:80',
      '/person-descriptions': 'http://127.0.0.1:80',
      '/contact-photos': 'http://127.0.0.1:80',
      '/person-avatars': 'http://127.0.0.1:80',
      '/generate-person-avatars': 'http://127.0.0.1:80',
      '/self-avatar': 'http://127.0.0.1:80',
      '/generate-self-avatar': 'http://127.0.0.1:80',
      '/indexing-history': 'http://127.0.0.1:80',
      '/indexing-stream': 'http://127.0.0.1:80'
    },
    watch: {
      usePolling: false,
      interval: 100,
      ignored: ['**/node_modules/**', '**/dist/**']
    },
    hmr: {
      overlay: false
    }
  },
  optimizeDeps: {
    include: ['bootstrap', '@popperjs/core', 'd3'],
    force: false
  },
  css: {
    devSourcemap: process.env.NODE_ENV !== 'production',
    preprocessorOptions: {
      scss: {
        silenceDeprecations: ['legacy-js-api', 'import', 'global-builtin', 'color-functions'],
        includePaths: ['node_modules'],
        sourceMap: process.env.NODE_ENV !== 'production',
        sourceMapContents: process.env.NODE_ENV !== 'production'
      }
    }
  },
  define: {
    global: 'globalThis',
    process: JSON.stringify({
      env: {
        NODE_ENV: 'production'
      }
    }),
    'process.env': JSON.stringify({
      NODE_ENV: 'production'
    }),
    'process.env.NODE_ENV': '"production"'
  }
});
