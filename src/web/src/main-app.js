// Lean shared entry point for MailGrapher's real feature pages.
// Unlike the old main-minimal.js "kitchen sink", this only loads what the
// 6 feature pages + login actually use: bootstrap/popper, dompurify, i18next, styles.

import * as bootstrap from 'bootstrap';
window.bootstrap = bootstrap;
globalThis.bootstrap = bootstrap;

import './main.scss';

import './utils/security.js';
import './js/helpers/smartresize.js';
import './js/init.js';
import './utils/i18n.js';

import { renderHeader, renderFooter } from './layout/appHeader.js';

/**
 * Mounts the shared header/footer for a page.
 * Call once at the top of each page's own entry module (src/pages/<name>.js)
 * with the page's key (matches NAV_ITEMS in appHeader.js), then run the
 * page-specific logic that follows.
 */
export function bootstrapApp(activePage) {
  renderHeader(activePage);
  renderFooter();
}
