/**
 * SAXAZ Protected Video Vault & Custom Player Engine
 * - Eliminates raw YouTube URLs from DOM / Inspect Element (uses server-signed vtok_ tokens + closed Shadow DOM)
 * - Blocks all clicks on YouTube logo, title, Share, Watch Later, and "Watch on YouTube" via pointer-events shield + overscan crop
 * - Blocks all YouTube pause/end-screen "More videos" suggestions via instant blackout curtain
 * - Supports YouTube Subtitle (CC) Toggle & Video Quality Changing (Auto / 1080p / 720p / 480p / 360p / 240p)
 * - Supports Fullscreen on Mobile in both Tilted (90° landscape on portrait phone) and Physical Landscape orientations
 */
(function () {
  if (window.SaxazVideoVault) return;

  let ytApiReady = false;
  let ytApiCallbacks = [];
  let ytScriptLoaded = false;

  function ensureGlobalFullscreenStyles() {
    if (document.getElementById('saxaz-fs-global-style')) return;
    const st = document.createElement('style');
    st.id = 'saxaz-fs-global-style';
    st.textContent = `
      html.sx-video-fs-lock,
      body.sx-video-fs-lock {
        overflow: hidden !important;
        overscroll-behavior: none !important;
        touch-action: none !important;
        background: #000000 !important;
      }
      html.sx-video-fs-lock header.sx-nav,
      html.sx-video-fs-lock .global-topbar,
      html.sx-video-fs-lock .global-sidebar,
      html.sx-video-fs-lock .saxaz-mobile-dock,
      html.sx-video-fs-lock .mobile-bottom-bar,
      html.sx-video-fs-lock #math-tools-dock-wrap,
      html.sx-video-fs-lock #scratchpad-dock-wrap,
      html.sx-video-fs-lock .question-palette-drawer,
      html.sx-video-fs-lock .mini-tutor-drawer {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
      }
      html.sx-video-fs-lock body *:not(.sx-fs-ancestor):not(.sx-ios-fs) {
        visibility: hidden !important;
        pointer-events: none !important;
      }
      html.sx-video-fs-lock .sx-fs-ancestor,
      html.sx-video-fs-lock .sx-fs-ancestor:hover,
      html.sx-video-fs-lock .sx-fs-ancestor:active,
      html.sx-video-fs-lock .sx-fs-ancestor:focus {
        transform: none !important;
        -webkit-transform: none !important;
        perspective: none !important;
        -webkit-perspective: none !important;
        transform-style: flat !important;
        -webkit-transform-style: flat !important;
        filter: none !important;
        -webkit-filter: none !important;
        backdrop-filter: none !important;
        -webkit-backdrop-filter: none !important;
        animation: none !important;
        -webkit-animation: none !important;
        transition: none !important;
        will-change: auto !important;
        contain: none !important;
        clip-path: none !important;
        -webkit-clip-path: none !important;
        mask: none !important;
        -webkit-mask: none !important;
        z-index: 2147483640 !important;
      }
      [data-saxaz-protected="true"].sx-ios-fs {
        visibility: visible !important;
        pointer-events: auto !important;
        position: fixed !important;
        top: 0 !important;
        left: 0 !important;
        right: 0 !important;
        bottom: 0 !important;
        width: 100vw !important;
        height: 100dvh !important;
        max-width: 100vw !important;
        max-height: 100dvh !important;
        margin: 0 !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 0 !important;
        z-index: 2147483647 !important;
        background: #000000 !important;
        overflow: hidden !important;
        touch-action: none !important;
      }
    `;
    (document.head || document.documentElement).appendChild(st);
  }

  function ensureYouTubeApi(cb) {
    if (window.YT && window.YT.Player) {
      ytApiReady = true;
      cb();
      return;
    }
    ytApiCallbacks.push(cb);
    if (!ytScriptLoaded) {
      ytScriptLoaded = true;
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = function () {
        ytApiReady = true;
        if (typeof prev === 'function') prev();
        const queue = ytApiCallbacks.slice();
        ytApiCallbacks = [];
        queue.forEach(fn => {
          try { fn(); } catch (e) { console.error(e); }
        });
      };
      const tag = document.createElement('script');
      tag.src = 'https://www.youtube.com/iframe_api';
      document.head.appendChild(tag);
    }
  }

  function decodeVaultResponse(payload) {
    if (!payload || !payload.k || !Array.isArray(payload.d)) return null;
    const key = payload.k;
    let out = '';
    for (let i = 0; i < payload.d.length; i++) {
      out += String.fromCharCode(payload.d[i] ^ key.charCodeAt(i % key.length));
    }
    return out;
  }

  async function resolveToken(token) {
    if (!token) return null;
    try {
      const res = await fetch('/student/api/video-vault/resolve', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'SAXAZ-Vault'
        },
        body: JSON.stringify({ token: token })
      });
      if (!res.ok) return null;
      const data = await res.json();
      return decodeVaultResponse(data);
    } catch (e) {
      console.error('Vault resolution failed:', e);
      return null;
    }
  }

  function formatTime(sec) {
    if (!sec || isNaN(sec) || sec < 0) return '0:00';
    const total = Math.floor(sec);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ':' + (s < 10 ? '0' + s : s);
  }

  const QUALITY_LABELS = {
    highres: '4K / Max',
    hd2160: '2160p 4K',
    hd1440: '1440p HD',
    hd1080: '1080p HD',
    hd720: '720p HD',
    large: '480p',
    medium: '360p',
    small: '240p',
    tiny: '144p',
    auto: 'Auto'
  };

  const DEFAULT_QUALITIES = ['auto', 'hd1080', 'hd720', 'large', 'medium', 'small'];

  const PLAYER_CSS = `
    :host {
      display: block;
      width: 100%;
      height: 100%;
    }
    * {
      box-sizing: border-box;
      user-select: none;
      -webkit-user-select: none;
      -webkit-tap-highlight-color: transparent;
    }
    .sx-root {
      position: relative;
      width: 100%;
      height: 100%;
      background: #000000;
      overflow: hidden;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #ffffff;
    }
    /* Fullscreen Landscape (when device is physically in landscape or desktop) */
    .sx-root.sx-fs-landscape {
      position: absolute !important;
      top: 0 !important;
      left: 0 !important;
      width: 100% !important;
      height: 100% !important;
      max-width: 100% !important;
      max-height: 100% !important;
      transform: none !important;
      -webkit-transform: none !important;
      z-index: 2147483647 !important;
      touch-action: none !important;
    }
    /* Fullscreen Tilted 90deg (when mobile device is held in portrait orientation) */
    .sx-root.sx-fs-tilted {
      position: absolute !important;
      top: 50% !important;
      left: 50% !important;
      width: 100dvh !important;
      height: 100vw !important;
      max-width: 100dvh !important;
      max-height: 100vw !important;
      transform: translate(-50%, -50%) rotate(90deg) !important;
      -webkit-transform: translate(-50%, -50%) rotate(90deg) !important;
      transform-origin: center center !important;
      -webkit-transform-origin: center center !important;
      z-index: 2147483647 !important;
      touch-action: none !important;
    }
    /* Top Fullscreen Action Bar (Exit & Rotate buttons for instant one-tap access on mobile Safari) */
    .sx-fs-topbar {
      display: none;
      position: absolute;
      top: 14px;
      left: 24px;
      right: 24px;
      z-index: 27;
      align-items: center;
      justify-content: space-between;
      pointer-events: none;
      transition: opacity 0.22s ease, transform 0.22s ease;
    }
    .sx-root.sx-fs-tilted .sx-fs-topbar,
    .sx-root.sx-fs-landscape .sx-fs-topbar {
      display: flex;
    }
    .sx-root.sx-playing:not(.sx-controls-awake) .sx-fs-topbar {
      opacity: 0;
      transform: translateY(-6px);
      pointer-events: none;
    }
    .sx-fs-pill {
      pointer-events: auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 7px 14px;
      border-radius: 999px;
      background: rgba(20, 20, 24, 0.88);
      border: 1.5px solid rgba(244, 170, 0, 0.75);
      color: #ffffff;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
    }
    .sx-fs-pill:active {
      transform: scale(0.95);
    }
    .sx-root.sx-fs-tilted .sx-controls,
    .sx-root.sx-fs-landscape .sx-controls {
      left: 24px;
      right: 24px;
      bottom: 14px;
    }
    .sx-viewport {
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none !important;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000000;
    }
    /* Overscan crop pushes YouTube top title/share bar and bottom watermark outside visible bounds */
    .sx-frame-crop {
      position: absolute;
      top: -64px;
      left: -2px;
      width: calc(100% + 4px);
      height: calc(100% + 128px);
      pointer-events: none !important;
      transition: top 0.2s ease, height 0.2s ease;
    }
    /* When Subtitles (CC) are enabled, lift bottom crop slightly so captions sit cleanly above control bar */
    .sx-root.sx-cc-on .sx-frame-crop {
      top: -78px;
      height: calc(100% + 96px);
    }
    .sx-frame-crop iframe {
      width: 100% !important;
      height: 100% !important;
      border: 0 !important;
      pointer-events: none !important;
    }
    /* Impermeable interaction shield */
    .sx-shield {
      position: absolute;
      inset: 0;
      z-index: 10;
      cursor: pointer;
      background: transparent;
    }
    .sx-root.sx-playing:not(.sx-controls-awake) .sx-shield {
      cursor: none;
    }
    /* Toast feedback badge for Quality / Subtitles changes */
    .sx-toast {
      position: absolute;
      top: 14px;
      right: 14px;
      z-index: 28;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(15, 15, 20, 0.88);
      border: 1.5px solid #F4AA00;
      color: #F4AA00;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.05em;
      pointer-events: none;
      opacity: 0;
      transform: translateY(-6px);
      transition: opacity 0.2s ease, transform 0.2s ease;
    }
    .sx-toast.sx-show {
      opacity: 1;
      transform: translateY(0);
    }
    /* Curtain hides YouTube pause/end suggestions and initial title/share overlays */
    .sx-curtain {
      position: absolute;
      inset: 0;
      z-index: 15;
      background: rgba(18, 18, 22, 0.96);
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
      padding-bottom: 52px;
      transition: opacity 0.18s ease;
      cursor: pointer;
    }
    .sx-curtain.sx-hidden {
      opacity: 0;
      pointer-events: none;
    }
    .sx-big-play {
      width: 62px;
      height: 62px;
      border-radius: 9999px;
      background: #F4AA00;
      color: #141414;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 30px rgba(244, 170, 0, 0.45);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
      flex-shrink: 0;
    }
    .sx-curtain:hover .sx-big-play {
      transform: scale(1.08);
      box-shadow: 0 14px 36px rgba(244, 170, 0, 0.65);
    }
    .sx-curtain-label {
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.78);
      text-align: center;
      padding: 0 14px;
    }
    .sx-curtain-label:empty {
      display: none;
    }
    .sx-root.sx-unstarted .sx-controls,
    .sx-root.sx-ended .sx-controls {
      display: none !important;
    }
    .sx-root.sx-started:not(.sx-ended) .sx-big-play {
      display: none !important;
    }
    /* Minimal Single-Line Control Bar */
    .sx-controls {
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      z-index: 25;
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 8px 14px 9px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.96);
      color: #18181b;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
      border: 1px solid rgba(0, 0, 0, 0.08);
      transition: opacity 0.22s ease, transform 0.22s ease;
    }
    .sx-root.sx-playing:not(.sx-controls-awake) .sx-controls {
      opacity: 0;
      transform: translateY(6px);
      pointer-events: none;
    }
    .sx-controls-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      width: 100%;
      flex-wrap: wrap;
      row-gap: 4px;
    }
    .sx-controls-left,
    .sx-controls-right {
      display: flex;
      align-items: center;
      gap: 5px;
      flex-shrink: 0;
    }
    .sx-controls-right {
      margin-left: auto;
    }
    .sx-btn {
      background: transparent;
      border: none;
      color: #18181b;
      width: 30px;
      height: 30px;
      border-radius: 9999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: background 0.15s ease, color 0.15s ease;
      padding: 0;
      flex-shrink: 0;
    }
    .sx-btn:hover {
      background: rgba(244, 170, 0, 0.18);
      color: #b47d00;
    }
    .sx-btn-primary {
      background: #F4AA00;
      color: #141414;
    }
    .sx-btn-primary:hover {
      background: #e09b00;
      color: #000;
    }
    .sx-fs-btn {
      background: rgba(244, 170, 0, 0.14);
      border: 1.5px solid rgba(244, 170, 0, 0.45);
    }
    /* Subtitle (CC) Toggle Button */
    .sx-cc-btn {
      background: #f4f4f5;
      border: 1.5px solid #d4d4d8;
      color: #27272a;
      font-size: 11px;
      font-weight: 900;
      letter-spacing: 0.03em;
      border-radius: 8px;
      height: 26px;
      padding: 0 7px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      flex-shrink: 0;
      transition: all 0.15s ease;
    }
    .sx-cc-btn:hover {
      border-color: #F4AA00;
    }
    .sx-cc-btn.sx-active {
      background: #F4AA00;
      color: #141414;
      border-color: #141414;
      box-shadow: 0 2px 0 #141414;
    }
    .sx-progress-wrap {
      width: 100%;
      display: flex;
      align-items: center;
      height: 16px;
      cursor: pointer;
      position: relative;
      touch-action: none;
    }
    .sx-range {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 6px;
      border-radius: 999px;
      background: #e4e4e7; accent-color: #f7b317;
      outline: none;
      cursor: pointer;
      margin: 0;
    }
    .sx-range::-webkit-slider-runnable-track {
      height: 6px;
      border-radius: 999px;
      background: transparent;
    }
    .sx-range::-moz-range-progress {
      background-color: #F4AA00;
      height: 6px;
      border-radius: 999px;
    }
    .sx-range::-moz-range-track {
      background-color: #e4e4e7;
      height: 6px;
      border-radius: 999px;
    }
    .sx-range::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 14px;
      height: 14px;
      margin-top: -4px;
      border-radius: 50%;
      background: #F4AA00;
      border: 2px solid #ffffff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.35);
      cursor: pointer;
    }
    .sx-range::-moz-range-thumb {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background: #F4AA00;
      border: 2px solid #ffffff;
      box-shadow: 0 1px 4px rgba(0,0,0,0.35);
      cursor: pointer;
    }
    .sx-time {
      font-size: 11px;
      font-weight: 800;
      font-variant-numeric: tabular-nums;
      color: #3f3f46;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .sx-select {
      -webkit-appearance: none;
      appearance: none;
      background-color: #f4f4f5;
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='%2318181b' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");
      background-repeat: no-repeat;
      background-position: right 5px center;
      background-size: 9px 9px;
      border: 1.5px solid #d4d4d8;
      color: #18181b;
      font-size: 11px;
      font-weight: 800;
      border-radius: 8px;
      height: 26px;
      padding: 0 17px 0 6px;
      cursor: pointer;
      outline: none;
      flex-shrink: 0;
    }
    .sx-select:hover,
    .sx-select:focus {
      border-color: #F4AA00;
    }
    .sx-tilt-btn {
      display: none;
    }
    .sx-root.sx-fs-tilted .sx-tilt-btn,
    .sx-root.sx-fs-landscape .sx-tilt-btn {
      display: inline-flex;
    }
    @media (max-width: 640px) {
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-curtain {
        padding-bottom: 46px;
        gap: 5px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-big-play {
        width: 40px;
        height: 40px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-big-play svg {
        width: 20px;
        height: 20px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-curtain-label {
        font-size: 9.5px;
        letter-spacing: 0.08em;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-controls {
        left: 5px;
        right: 5px;
        bottom: 5px;
        padding: 4px 6px 5px;
        border-radius: 11px;
        gap: 2px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-progress-wrap {
        height: 13px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-controls-row {
        gap: 2px;
        row-gap: 3px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-controls-left,
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-controls-right {
        gap: 2px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-btn {
        width: 22px;
        height: 22px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-btn svg {
        width: 12px;
        height: 12px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-time {
        font-size: 9px;
        letter-spacing: -0.03em;
        margin: 0 1px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-cc-btn {
        font-size: 9px;
        height: 20px;
        padding: 0 4px;
        border-radius: 6px;
      }
      .sx-root:not(.sx-fs-tilted):not(.sx-fs-landscape) .sx-select {
        font-size: 9px;
        height: 20px;
        padding: 0 12px 0 4px;
        border-radius: 6px;
        background-position: right 3px center;
        background-size: 7px 7px;
      }
    }
  `;

  const instances = new WeakMap();
  const activePlayers = new Set();

  // Block F12 / Ctrl+Shift+I / Ctrl+Shift+C / Ctrl+Shift+J / Ctrl+U when protected videos exist on page
  window.addEventListener('keydown', (e) => {
    if (activePlayers.size === 0) return;
    if (e.key === 'Escape') {
      activePlayers.forEach(p => {
        if (p.isFullscreen) p.exitFullscreen();
      });
      return;
    }
    const key = (e.key || '').toUpperCase();
    const isDevShortcut =
      e.key === 'F12' ||
      (e.ctrlKey && e.shiftKey && (key === 'I' || key === 'C' || key === 'J')) ||
      (e.metaKey && e.altKey && (key === 'I' || key === 'C' || key === 'J')) ||
      (e.ctrlKey && key === 'U');
    if (isDevShortcut) {
      e.preventDefault();
      e.stopPropagation();
      activePlayers.forEach(p => p.purgeFrame('Video Paused — Click to Resume'));
      return false;
    }
  }, true);

  document.addEventListener('contextmenu', (e) => {
    if (e.target && e.target.closest && e.target.closest('[data-saxaz-protected="true"]')) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
  }, true);

  class ProtectedPlayer {
    constructor(hostEl) {
      ensureGlobalFullscreenStyles();
      this.hostEl = hostEl;
      this.contentId = hostEl.getAttribute('data-content-id') || '';
      this.nextUrl = hostEl.getAttribute('data-next-url') || '';
      this.nextLabel = hostEl.getAttribute('data-next-label') || 'Proceed to Next Summary →';
      const initialToken = hostEl.getAttribute('data-saxaz-video') || '';
      // Strip attribute from DOM so Inspect Element doesn't show even the token
      hostEl.removeAttribute('data-saxaz-video');
      hostEl.setAttribute('data-saxaz-protected', 'true');

      // Attach CLOSED Shadow DOM so element.shadowRoot is null in DevTools console
      this.shadow = hostEl.attachShadow({ mode: 'closed' });
      this.ytPlayer = null;
      this.pollTimer = null;
      this.wakeTimer = null;
      this.toastTimer = null;
      this.isPlaying = false;
      this.isEnded = false;
      this.isMuted = false;
      this.isMounting = false;
      this.isFullscreen = false;
      this.manualTiltMode = null; // null = auto (tilted when portrait, landscape when rotated), 'tilted', or 'upright'
      this.fsAncestors = [];
      this.duration = 0;
      this.resumeTime = 0;
      this.currentToken = null;
      this.resolvedVideoId = null;

      // YouTube Subtitle (CC) & Quality state
      this.ccEnabled = false;
      this.mountedWithCc = false;
      this.selectedQuality = 'auto';
      this.availableQualities = DEFAULT_QUALITIES.slice();

      activePlayers.add(this);
      this.buildUI();

      this._onWindowResize = () => {
        if (this.isFullscreen) {
          this.syncFullscreenOrientation();
        }
      };
      this._onFsTouchMoveLock = (e) => {
        if (!this.isFullscreen) return;
        if (e.cancelable) {
          e.preventDefault();
        }
      };
      window.addEventListener('resize', this._onWindowResize);
      window.addEventListener('orientationchange', this._onWindowResize);
      if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', this._onWindowResize);
        window.visualViewport.addEventListener('scroll', this._onWindowResize);
      }
      this._onNativeFs = () => this.onNativeFullscreenChange();
      document.addEventListener('fullscreenchange', this._onNativeFs);
      document.addEventListener('webkitfullscreenchange', this._onNativeFs);

      if (initialToken) {
        this.loadToken(initialToken);
      }
    }

    buildUI() {
      const style = document.createElement('style');
      style.textContent = PLAYER_CSS;

      this.root = document.createElement('div');
      this.root.className = 'sx-root sx-unstarted sx-controls-awake';
      this.root.addEventListener('contextmenu', e => {
        e.preventDefault();
        e.stopPropagation();
        return false;
      });

      this.root.innerHTML = `
        <div class="sx-viewport">
          <div class="sx-frame-crop">
            <div class="sx-yt-mount"></div>
          </div>
        </div>
        <div class="sx-shield"></div>
        <div class="sx-fs-topbar">
          <button type="button" class="sx-fs-pill sx-fs-top-rotate" title="Rotate Fullscreen Orientation">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F4AA00" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><rect x="7" y="11" width="10" height="7" rx="1.5"/></svg>
            <span>Rotate</span>
          </button>
          <button type="button" class="sx-fs-pill sx-fs-top-exit" title="Exit Fullscreen">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#F4AA00" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            <span>Exit Fullscreen</span>
          </button>
        </div>
        <div class="sx-toast"></div>
        <div class="sx-curtain" style="padding-bottom:0;">
          <div class="sx-big-play">
            <svg class="sx-curtain-icon" width="30" height="30" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z"/>
            </svg>
          </div>
          <button type="button" class="sx-next-summary-btn" style="display:none;padding:13px 28px;border-radius:999px;background:#f7b317;color:#16151a;font-weight:800;font-size:15px;border:0;box-shadow:0 12px 28px rgba(0,0,0,0.45);cursor:pointer;pointer-events:auto;align-items:center;gap:8px;">
            <span class="sx-next-summary-text">Next Video</span>
          </button>
          <div class="sx-curtain-label"></div>
        </div>
        <div class="sx-controls">
          <div class="sx-progress-wrap" title="Seek Video">
            <input type="range" class="sx-range" min="0" max="1000" value="0" step="1">
          </div>
          <div class="sx-controls-row">
            <div class="sx-controls-left">
              <button type="button" class="sx-btn sx-btn-primary sx-play-btn" title="Play / Pause">
                <svg class="sx-icon-play" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
                <svg class="sx-icon-pause" width="15" height="15" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
              </button>
              <button type="button" class="sx-btn sx-mute-btn" title="Mute / Unmute">
                <svg class="sx-icon-vol" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                <svg class="sx-icon-muted" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:none;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
              </button>
              <span class="sx-time">0:00 / 0:00</span>
            </div>
            <div class="sx-controls-right">
              <button type="button" class="sx-btn sx-tilt-btn" title="Rotate / Tilt Fullscreen Orientation">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><rect x="7" y="11" width="10" height="7" rx="1.5"/></svg>
              </button>
              <button type="button" class="sx-btn sx-fs-btn" title="Fullscreen">
                <svg class="sx-icon-fs-enter" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
                <svg class="sx-icon-fs-exit" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:none;"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>
              </button>
            </div>
          </div>
        </div>
      `;

      this.shadow.appendChild(style);
      this.shadow.appendChild(this.root);

      this.frameCropEl = this.root.querySelector('.sx-frame-crop');
      this.mountEl = this.root.querySelector('.sx-yt-mount');
      this.shieldEl = this.root.querySelector('.sx-shield');
      this.toastEl = this.root.querySelector('.sx-toast');
      this.curtainEl = this.root.querySelector('.sx-curtain');
      this.bigPlayEl = this.root.querySelector('.sx-big-play');
      this.curtainLabelEl = this.root.querySelector('.sx-curtain-label');
      this.nextSummaryBtn = this.root.querySelector('.sx-next-summary-btn');
      this.nextSummaryTextEl = this.root.querySelector('.sx-next-summary-text');
      this.controlsEl = this.root.querySelector('.sx-controls');
      this.progressWrapEl = this.root.querySelector('.sx-progress-wrap');
      this.playBtn = this.root.querySelector('.sx-play-btn');
      this.iconPlay = this.root.querySelector('.sx-icon-play');
      this.iconPause = this.root.querySelector('.sx-icon-pause');
      this.rangeEl = this.root.querySelector('.sx-range');
      this.timeEl = this.root.querySelector('.sx-time');
      this.muteBtn = this.root.querySelector('.sx-mute-btn');
      this.iconVol = this.root.querySelector('.sx-icon-vol');
      this.iconMuted = this.root.querySelector('.sx-icon-muted');
      this.tiltBtn = this.root.querySelector('.sx-tilt-btn');
      this.fsBtn = this.root.querySelector('.sx-fs-btn');
      this.fsTopExitBtn = this.root.querySelector('.sx-fs-top-exit');
      this.fsTopRotateBtn = this.root.querySelector('.sx-fs-top-rotate');
      this.iconFsEnter = this.root.querySelector('.sx-icon-fs-enter');
      this.iconFsExit = this.root.querySelector('.sx-icon-fs-exit');

      // Wake controls only when the cursor actually moves; hide after idle timeout or mouseleave
      this._lastMouseX = -1;
      this._lastMouseY = -1;
      this.root.addEventListener('mousemove', (e) => {
        if (Math.abs(e.clientX - this._lastMouseX) > 2 || Math.abs(e.clientY - this._lastMouseY) > 2) {
          this._lastMouseX = e.clientX;
          this._lastMouseY = e.clientY;
          this.wakeControls();
        }
      }, { passive: true });
      this.root.addEventListener('mouseleave', () => {
        if (this.isPlaying) {
          if (this.wakeTimer) clearTimeout(this.wakeTimer);
          this.root.classList.remove('sx-controls-awake');
        }
      });

      // Keep controls awake when interacting with control bar
      this.controlsEl.addEventListener('pointerdown', (e) => {
        e.stopPropagation();
        this.wakeControls();
      });
      this.controlsEl.addEventListener('click', (e) => {
        e.stopPropagation();
        this.wakeControls();
      });

      // Shield click: on touch devices when controls are hidden, wake controls first; otherwise toggle play
      this.shieldEl.addEventListener('click', (e) => {
        e.stopPropagation();
        const isTouch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
        if (isTouch && this.isPlaying && !this.root.classList.contains('sx-controls-awake')) {
          this.wakeControls();
          return;
        }
        this.wakeControls();
        this.togglePlay();
      });

      this.shieldEl.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        this.toggleFullscreen();
      });

      this.curtainEl.addEventListener('click', (e) => {
        e.stopPropagation();
        this.wakeControls();
        this.togglePlay();
      });

      this.playBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.wakeControls();
        this.togglePlay();
      });

      // Custom pointer/touch scrubbing that works in BOTH upright and 90°-tilted fullscreen
      const seekFromPointer = (clientX, clientY) => {
        const rect = this.progressWrapEl.getBoundingClientRect();
        if (!rect.width && !rect.height) return;
        let ratio = 0;
        if (this.root.classList.contains('sx-fs-tilted')) {
          ratio = (clientY - rect.top) / Math.max(1, rect.height);
        } else {
          ratio = (clientX - rect.left) / Math.max(1, rect.width);
        }
        ratio = Math.min(1, Math.max(0, ratio));
        const rawVal = Math.round(ratio * 1000);
        this.updateSeekVisual(rawVal);
        if (this.ytPlayer && this.duration > 0) {
          const target = ratio * Math.max(0, this.duration - 0.5);
          this.resumeTime = target;
          this.ytPlayer.seekTo(target, true);
          this.updateTimeUI(target, this.duration);
        }
      };

      this.rangeEl.addEventListener('input', (e) => {
        e.stopPropagation();
        this.wakeControls();
        const rawVal = parseFloat(this.rangeEl.value) || 0;
        this.updateSeekVisual(rawVal);
        if (!this.ytPlayer || !this.duration) return;
        const target = (rawVal / 1000) * Math.max(0, this.duration - 0.5);
        this.resumeTime = target;
        this.ytPlayer.seekTo(target, true);
        this.updateTimeUI(target, this.duration);
      });

      this.progressWrapEl.addEventListener('touchstart', (e) => {
        if (!e.touches || !e.touches.length) return;
        e.stopPropagation();
        this.wakeControls();
        seekFromPointer(e.touches[0].clientX, e.touches[0].clientY);
      }, { passive: true });

      this.progressWrapEl.addEventListener('touchmove', (e) => {
        if (!e.touches || !e.touches.length) return;
        if (e.cancelable) e.preventDefault();
        e.stopPropagation();
        this.wakeControls();
        seekFromPointer(e.touches[0].clientX, e.touches[0].clientY);
      }, { passive: false });

      this.muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.wakeControls();
        if (!this.ytPlayer) return;
        if (this.ytPlayer.isMuted()) {
          this.ytPlayer.unMute();
          this.isMuted = false;
        } else {
          this.ytPlayer.mute();
          this.isMuted = true;
        }
        this.iconVol.style.display = this.isMuted ? 'none' : '';
        this.iconMuted.style.display = this.isMuted ? '' : 'none';
      });

      // Manual Tilt / Rotate toggle button in Fullscreen
      const handleRotateToggle = (e) => {
        e.stopPropagation();
        this.wakeControls();
        const isCurrentlyTilted = this.root.classList.contains('sx-fs-tilted');
        this.manualTiltMode = isCurrentlyTilted ? 'upright' : 'tilted';
        this.syncFullscreenOrientation();
        this.showToast(this.manualTiltMode === 'tilted' ? 'Landscape Tilt: ON' : 'Upright View');
      };
      this.tiltBtn.addEventListener('click', handleRotateToggle);
      if (this.fsTopRotateBtn) {
        this.fsTopRotateBtn.addEventListener('click', handleRotateToggle);
      }

      // Fullscreen Toggle
      let lastFsToggleTs = 0;
      const triggerFsToggle = (e) => {
        e.stopPropagation();
        const now = Date.now();
        if (now - lastFsToggleTs < 280) return;
        lastFsToggleTs = now;
        this.wakeControls();
        this.toggleFullscreen();
      };
      this.fsBtn.addEventListener('click', triggerFsToggle);
      this.fsBtn.addEventListener('touchend', (e) => {
        if (e.cancelable) e.preventDefault();
        triggerFsToggle(e);
      }, { passive: false });
      if (this.fsTopExitBtn) {
        this.fsTopExitBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.exitFullscreen();
        });
        this.fsTopExitBtn.addEventListener('touchend', (e) => {
          if (e.cancelable) e.preventDefault();
          e.stopPropagation();
          this.exitFullscreen();
        }, { passive: false });
      }

      const triggerProceedNext = (e) => {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        if (this.isFullscreen) this.exitFullscreen();
        if (this.contentId) {
          try {
            fetch(`/student/content/${this.contentId}/complete`, { method: 'POST' }).catch(() => {});
          } catch (_err) {}
        }
        const ev = new CustomEvent('saxaz:proceed-next', {
          bubbles: true,
          cancelable: true,
          detail: {
            nextUrl: this.nextUrl,
            nextLabel: this.nextLabel,
            contentId: this.contentId
          }
        });
        const notCancelled = this.hostEl.dispatchEvent(ev);
        if (notCancelled && this.nextUrl) {
          window.location.href = this.nextUrl;
        }
      };

      this.hasNextAction = Boolean(this.nextUrl || this.hostEl.hasAttribute('data-has-next'));
      if (this.hasNextAction) {
        if (this.nextSummaryTextEl) {
          this.nextSummaryTextEl.textContent = this.nextLabel || 'Next Video';
        }
        if (this.nextSummaryBtn) {
          this.nextSummaryBtn.style.display = 'none';
          this.nextSummaryBtn.addEventListener('click', triggerProceedNext);
        }
      }
    }

    wakeControls() {
      this.root.classList.add('sx-controls-awake');
      if (this.wakeTimer) clearTimeout(this.wakeTimer);
      this.wakeTimer = setTimeout(() => {
        if (this.isPlaying) {
          this.root.classList.remove('sx-controls-awake');
        }
      }, 2500);
    }

    showToast(msg) {
      if (!this.toastEl) return;
      this.toastEl.textContent = msg;
      this.toastEl.classList.add('sx-show');
      if (this.toastTimer) clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => {
        this.toastEl.classList.remove('sx-show');
      }, 1800);
    }

    /* =====================================================================
       YOUTUBE SUBTITLE (CC) TOGGLE & QUALITY CHANGING IMPLEMENTATION
       ===================================================================== */
    toggleSubtitles() {
      this.ccEnabled = !this.ccEnabled;
      this.ccBtn.classList.toggle('sx-active', this.ccEnabled);
      this.ccBtn.setAttribute('aria-pressed', this.ccEnabled ? 'true' : 'false');
      this.root.classList.toggle('sx-cc-on', this.ccEnabled);
      this.showToast(this.ccEnabled ? 'Subtitles (CC): ON' : 'Subtitles (CC): OFF');

      if (!this.ytPlayer || typeof this.ytPlayer.getPlayerState !== 'function') {
        return;
      }

      if (this.ccEnabled) {
        this.applySubtitlesToPlayer();
        // If iframe was originally mounted without cc_load_policy=1 and YouTube has not loaded caption tracks yet, remount seamlessly at current timestamp
        let tracks = [];
        try {
          if (typeof this.ytPlayer.getOption === 'function') {
            tracks = this.ytPlayer.getOption('captions', 'tracklist') || this.ytPlayer.getOption('cc', 'tracklist') || [];
          }
        } catch (e) {}
        if ((!Array.isArray(tracks) || tracks.length === 0) && !this.mountedWithCc) {
          this.remountAtCurrentTime();
        }
      } else {
        try {
          if (typeof this.ytPlayer.setOption === 'function') {
            this.ytPlayer.setOption('captions', 'track', {});
            this.ytPlayer.setOption('cc', 'track', {});
          }
          if (typeof this.ytPlayer.unloadModule === 'function') {
            this.ytPlayer.unloadModule('captions');
            this.ytPlayer.unloadModule('cc');
          }
        } catch (e) {}
        if (this.mountedWithCc) {
          this.remountAtCurrentTime();
        }
      }
    }

    applySubtitlesToPlayer() {
      if (!this.ytPlayer) return;
      try {
        if (this.ccEnabled) {
          if (typeof this.ytPlayer.loadModule === 'function') {
            try { this.ytPlayer.loadModule('captions'); } catch (e) {}
            try { this.ytPlayer.loadModule('cc'); } catch (e) {}
          }
          if (typeof this.ytPlayer.setOption === 'function') {
            const tracks = this.ytPlayer.getOption('captions', 'tracklist') || this.ytPlayer.getOption('cc', 'tracklist') || [];
            const preferred = (Array.isArray(tracks) && tracks.length > 0)
              ? (tracks.find(t => t.languageCode === 'en' || String(t.languageCode || '').startsWith('en')) || tracks[0])
              : { languageCode: 'en' };
            try { this.ytPlayer.setOption('captions', 'track', preferred); } catch (e) {}
            try { this.ytPlayer.setOption('cc', 'track', preferred); } catch (e) {}
          }
        } else {
          if (typeof this.ytPlayer.setOption === 'function') {
            try { this.ytPlayer.setOption('captions', 'track', {}); } catch (e) {}
            try { this.ytPlayer.setOption('cc', 'track', {}); } catch (e) {}
          }
        }
      } catch (e) {}
    }

    refreshAvailableQualities() {
      if (!this.ytPlayer || typeof this.ytPlayer.getAvailableQualityLevels !== 'function') return;
      try {
        const levels = this.ytPlayer.getAvailableQualityLevels();
        if (Array.isArray(levels) && levels.length > 0) {
          const merged = ['auto'];
          levels.forEach(lvl => {
            if (lvl && lvl !== 'auto' && !merged.includes(lvl) && QUALITY_LABELS[lvl]) {
              merged.push(lvl);
            }
          });
          if (merged.length > 1) {
            this.availableQualities = merged;
            const prevSelected = this.selectedQuality;
            this.qualityEl.innerHTML = merged.map(q => {
              const label = QUALITY_LABELS[q] || q;
              const sel = q === prevSelected ? ' selected' : '';
              return `<option value="${q}"${sel}>${label}</option>`;
            }).join('');
          }
        }
      } catch (e) {}
    }

    setVideoQuality(q) {
      this.selectedQuality = q || 'auto';
      const label = QUALITY_LABELS[this.selectedQuality] || this.selectedQuality;
      this.showToast(`Quality: ${label}`);

      if (!this.ytPlayer || typeof this.ytPlayer.getPlayerState !== 'function') return;

      this.applyQualityToPlayer(this.selectedQuality, true);
    }

    applyQualityToPlayer(q, userInitiated) {
      if (!this.ytPlayer) return;
      try {
        if (q === 'auto') {
          if (typeof this.ytPlayer.setPlaybackQualityRange === 'function') {
            this.ytPlayer.setPlaybackQualityRange('small', 'highres');
          }
          if (typeof this.ytPlayer.setPlaybackQuality === 'function') {
            this.ytPlayer.setPlaybackQuality('default');
          }
          return;
        }
        if (typeof this.ytPlayer.setPlaybackQualityRange === 'function') {
          this.ytPlayer.setPlaybackQualityRange(q, q);
        }
        if (typeof this.ytPlayer.setPlaybackQuality === 'function') {
          this.ytPlayer.setPlaybackQuality(q);
        }
        if (userInitiated && this.resolvedVideoId) {
          const curQuality = (typeof this.ytPlayer.getPlaybackQuality === 'function') ? this.ytPlayer.getPlaybackQuality() : '';
          if (curQuality && curQuality !== q && typeof this.ytPlayer.loadVideoById === 'function') {
            const curTime = (typeof this.ytPlayer.getCurrentTime === 'function') ? (this.ytPlayer.getCurrentTime() || this.resumeTime || 0) : (this.resumeTime || 0);
            const wasPlaying = this.isPlaying;
            this.resumeTime = curTime;
            this.ytPlayer.loadVideoById({
              videoId: this.resolvedVideoId,
              startSeconds: curTime,
              suggestedQuality: q
            });
            setTimeout(() => {
              if (!this.ytPlayer) return;
              try {
                if (typeof this.ytPlayer.setPlaybackQualityRange === 'function') {
                  this.ytPlayer.setPlaybackQualityRange(q, q);
                }
                if (typeof this.ytPlayer.setPlaybackQuality === 'function') {
                  this.ytPlayer.setPlaybackQuality(q);
                }
                const rate = parseFloat(this.speedEl.value) || 0.75;
                if (typeof this.ytPlayer.setPlaybackRate === 'function') {
                  this.ytPlayer.setPlaybackRate(rate);
                }
                if (!wasPlaying && typeof this.ytPlayer.pauseVideo === 'function') {
                  this.ytPlayer.pauseVideo();
                }
              } catch (e) {}
            }, 220);
          }
        }
      } catch (e) {}
    }

    remountAtCurrentTime() {
      if (!this.currentToken) return;
      if (this.ytPlayer && typeof this.ytPlayer.getCurrentTime === 'function') {
        try {
          this.resumeTime = this.ytPlayer.getCurrentTime() || this.resumeTime || 0;
        } catch (e) {}
      }
      this.purgeFrame('Updating Player...');
      this.mountAndPlay();
    }

    updateSeekVisual(pctPermille) {
      const clamped = Math.min(1000, Math.max(0, Math.round(pctPermille || 0)));
      const pct = (clamped / 1000) * 100;
      this.rangeEl.value = String(clamped);
      this.rangeEl.style.accentColor = '#f7b317';
    }

    purgeFrame(message) {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
      if (this.ytPlayer) {
        try {
          if (typeof this.ytPlayer.getCurrentTime === 'function') {
            this.resumeTime = this.ytPlayer.getCurrentTime() || this.resumeTime || 0;
          }
          if (typeof this.ytPlayer.destroy === 'function') {
            this.ytPlayer.destroy();
          }
        } catch (e) {}
        this.ytPlayer = null;
      }
      this.isPlaying = false;
      this.isMounting = false;
      this.root.classList.remove('sx-playing', 'sx-started', 'sx-ended');
      this.root.classList.add('sx-unstarted');
      if (this.nextSummaryBtn) this.nextSummaryBtn.style.display = 'none';
      if (this.bigPlayEl) this.bigPlayEl.style.display = '';
      this.iconPlay.style.display = '';
      this.iconPause.style.display = 'none';
      this.frameCropEl.innerHTML = '<div class="sx-yt-mount"></div>';
      this.mountEl = this.frameCropEl.querySelector('.sx-yt-mount');
      this.showCurtain(message || '');
    }

    loadToken(token) {
      if (!token || token === this.currentToken) return;
      this.currentToken = token;
      this.resolvedVideoId = null;
      this.resumeTime = 0;
      this.duration = 0;
      this.isEnded = false;
      this.updateSeekVisual(0);
      this.updateTimeUI(0, 0);
      this.purgeFrame('');
      if (this.hostEl.hasAttribute('data-autoplay')) {
        this.mountAndPlay();
      }
    }

    forceDisableSubtitles() {
      if (!this.ytPlayer) return;
      try {
        if (typeof this.ytPlayer.setOption === 'function') {
          try { this.ytPlayer.setOption('captions', 'track', {}); } catch (e) {}
          try { this.ytPlayer.setOption('cc', 'track', {}); } catch (e) {}
        }
        if (typeof this.ytPlayer.unloadModule === 'function') {
          try { this.ytPlayer.unloadModule('captions'); } catch (e) {}
          try { this.ytPlayer.unloadModule('cc'); } catch (e) {}
        }
      } catch (e) {}
    }

    forceMaxResolution() {
      if (!this.ytPlayer) return;
      try {
        const levels = (typeof this.ytPlayer.getAvailableQualityLevels === 'function')
          ? this.ytPlayer.getAvailableQualityLevels()
          : [];
        const best = (Array.isArray(levels) && levels.find(q => q && q !== 'auto')) || 'hd1080';
        const curQ = (typeof this.ytPlayer.getPlaybackQuality === 'function')
          ? this.ytPlayer.getPlaybackQuality()
          : '';
        if (!curQ || curQ !== best) {
          if (typeof this.ytPlayer.setPlaybackQualityRange === 'function') {
            try { this.ytPlayer.setPlaybackQualityRange(best, best); } catch (e) {}
          }
          if (typeof this.ytPlayer.setPlaybackQuality === 'function') {
            try { this.ytPlayer.setPlaybackQuality(best); } catch (e) {}
          }
        }
      } catch (e) {}
    }

    async mountAndPlay() {
      if (this.isMounting || !this.currentToken) return;
      this.isMounting = true;
      if (this.nextSummaryBtn) this.nextSummaryBtn.style.display = 'none';
      this.showCurtain('Loading...');
      const videoId = this.resolvedVideoId || await resolveToken(this.currentToken);
      if (!videoId) {
        this.isMounting = false;
        this.showCurtain('Video Unavailable');
        return;
      }
      this.resolvedVideoId = videoId;

      ensureYouTubeApi(() => {
        const startSec = this.isEnded ? 0 : Math.floor(this.resumeTime || 0);
        this.isEnded = false;
        this.ccEnabled = false;
        this.mountedWithCc = false;
        const playerVars = {
          autoplay: 1,
          start: startSec,
          controls: 0,
          rel: 0,
          modestbranding: 1,
          iv_load_policy: 3,
          cc_load_policy: 0,
          hl: 'en',
          vq: 'highres',
          disablekb: 1,
          fs: 0,
          playsinline: 1,
          origin: window.location.origin
        };

        this.ytPlayer = new window.YT.Player(this.mountEl, {
          width: '100%',
          height: '100%',
          host: 'https://www.youtube-nocookie.com',
          videoId: videoId,
          playerVars: playerVars,
          events: {
            onReady: () => {
              this.isMounting = false;
              this.duration = this.ytPlayer.getDuration() || 0;
              this.forceDisableSubtitles();
              this.forceMaxResolution();
              if (this.resumeTime > 0 && typeof this.ytPlayer.seekTo === 'function') {
                this.ytPlayer.seekTo(this.resumeTime, true);
              }
              if (typeof this.ytPlayer.setPlaybackRate === 'function') {
                this.ytPlayer.setPlaybackRate(1);
              }
              if (this.isMuted && typeof this.ytPlayer.mute === 'function') {
                this.ytPlayer.mute();
              }
              this.ytPlayer.playVideo();
              this.forceMaxResolution();
              this.startMonitor();
            },
            onApiChange: () => {
              this.forceDisableSubtitles();
              this.forceMaxResolution();
            },
            onStateChange: (ev) => this.onStateChange(ev)
          }
        });
      });
    }

    onStateChange(ev) {
      const YTS = window.YT.PlayerState;
      if (ev.data === YTS.BUFFERING) {
        this.forceDisableSubtitles();
        this.forceMaxResolution();
      } else if (ev.data === YTS.PLAYING) {
        this.isPlaying = true;
        this.isEnded = false;
        this.duration = this.ytPlayer.getDuration() || this.duration;
        if (this.nextSummaryBtn) this.nextSummaryBtn.style.display = 'none';
        this.forceDisableSubtitles();
        this.forceMaxResolution();
        this.hideCurtain();
        this.root.classList.remove('sx-unstarted', 'sx-ended');
        this.root.classList.add('sx-started', 'sx-playing');
        this.iconPlay.style.display = 'none';
        this.iconPause.style.display = '';
        this.wakeControls();
      } else if (ev.data === YTS.PAUSED) {
        this.isPlaying = false;
        this.root.classList.remove('sx-playing');
        this.root.classList.add('sx-controls-awake');
        this.iconPlay.style.display = '';
        this.iconPause.style.display = 'none';
        if (this.ytPlayer && typeof this.ytPlayer.getCurrentTime === 'function') {
          this.resumeTime = this.ytPlayer.getCurrentTime() || this.resumeTime;
        }
        if (this.nextSummaryBtn && !this.isEnded) this.nextSummaryBtn.style.display = 'none';
        this.showCurtain(this.isEnded ? 'Watch Again' : 'Paused');
      } else if (ev.data === YTS.ENDED) {
        this.handleVideoEnded();
      }
    }

    handleVideoEnded() {
      if (this.isEnded) return;
      this.isEnded = true;
      this.isPlaying = false;
      this.resumeTime = 0;
      this.updateSeekVisual(1000);
      this.root.classList.remove('sx-playing');
      this.root.classList.add('sx-ended', 'sx-controls-awake');
      this.iconPlay.style.display = '';
      this.iconPause.style.display = 'none';
      if (this.hasNextAction && this.nextSummaryBtn) {
        if (this.bigPlayEl) this.bigPlayEl.style.display = 'none';
        this.nextSummaryBtn.style.display = 'inline-flex';
        this.showCurtain('Tap background to watch again');
      } else {
        if (this.bigPlayEl) this.bigPlayEl.style.display = '';
        this.showCurtain('Watch Again');
      }

      if (this.contentId && window.htmx) {
        const container = document.getElementById(`progress-container-${this.contentId}`);
        if (container && container.querySelector('button')) {
          window.htmx.ajax('POST', `/student/content/${this.contentId}/complete`, {
            target: `#progress-container-${this.contentId}`,
            swap: 'innerHTML'
          });
        }
      }
      this.hostEl.dispatchEvent(new CustomEvent('saxaz:video-ended', { bubbles: true }));
    }

    startMonitor() {
      if (this.pollTimer) clearInterval(this.pollTimer);
      this._monTick = 0;
      this.pollTimer = setInterval(() => {
        if (!this.ytPlayer || typeof this.ytPlayer.getCurrentTime !== 'function') return;
        this._monTick = (this._monTick || 0) + 1;
        if (this.isPlaying && this._monTick % 6 === 0) {
          this.forceDisableSubtitles();
          this.forceMaxResolution();
        }
        const cur = this.ytPlayer.getCurrentTime() || 0;
        const dur = this.ytPlayer.getDuration() || this.duration || 0;
        if (dur > 0) {
          this.duration = dur;
          this.resumeTime = cur;
          if (this.isPlaying && dur - cur <= 0.45 && dur > 2) {
            this.ytPlayer.pauseVideo();
            this.ytPlayer.seekTo(0, true);
            this.handleVideoEnded();
            return;
          }
          const pct = Math.min(1000, Math.max(0, Math.round((cur / dur) * 1000)));
          this.updateSeekVisual(pct);
          this.updateTimeUI(cur, dur);
        }
      }, 120);
    }

    updateTimeUI(cur, dur) {
      this.timeEl.textContent = `${formatTime(cur)} / ${formatTime(dur)}`;
    }

    showCurtain(label) {
      this.curtainLabelEl.textContent = label || '';
      this.curtainEl.classList.remove('sx-hidden');
    }

    hideCurtain() {
      this.curtainEl.classList.add('sx-hidden');
    }

    togglePlay() {
      if (!this.ytPlayer || typeof this.ytPlayer.getPlayerState !== 'function') {
        this.mountAndPlay();
        return;
      }
      const state = this.ytPlayer.getPlayerState();
      if (state === window.YT.PlayerState.PLAYING) {
        this.ytPlayer.pauseVideo();
      } else {
        if (this.isEnded) {
          this.isEnded = false;
          this.resumeTime = 0;
          if (this.nextSummaryBtn) this.nextSummaryBtn.style.display = 'none';
          this.root.classList.remove('sx-ended');
          this.updateSeekVisual(0);
          this.ytPlayer.seekTo(0, true);
        }
        this.ytPlayer.playVideo();
      }
    }

    pause() {
      if (this.ytPlayer && typeof this.ytPlayer.pauseVideo === 'function') {
        try { this.ytPlayer.pauseVideo(); } catch (e) {}
      }
    }

    /* =====================================================================
       MOBILE & DESKTOP FULLSCREEN (TILTED 90° PORTRAIT + PHYSICAL LANDSCAPE)
       ===================================================================== */
    unlockAncestorsForFullscreen() {
      this.restoreAncestorsFromFullscreen();
      this._savedWindowScroll = {
        x: window.scrollX || window.pageXOffset || 0,
        y: window.scrollY || window.pageYOffset || 0
      };
      this._savedHtmlCssText = document.documentElement.style.cssText || '';
      this._savedBodyCssText = document.body.style.cssText || '';
      this._savedHostCssText = this.hostEl.style.cssText || '';

      let p = this.hostEl.parentElement;
      while (p && p !== document.body && p !== document.documentElement) {
        this.fsAncestors.push({
          el: p,
          cssText: p.style.cssText || '',
          scrollTop: p.scrollTop || 0,
          scrollLeft: p.scrollLeft || 0
        });
        p.classList.add('sx-fs-ancestor');
        p.style.setProperty('transform', 'none', 'important');
        p.style.setProperty('-webkit-transform', 'none', 'important');
        p.style.setProperty('perspective', 'none', 'important');
        p.style.setProperty('-webkit-perspective', 'none', 'important');
        p.style.setProperty('transform-style', 'flat', 'important');
        p.style.setProperty('-webkit-transform-style', 'flat', 'important');
        p.style.setProperty('filter', 'none', 'important');
        p.style.setProperty('-webkit-filter', 'none', 'important');
        p.style.setProperty('backdrop-filter', 'none', 'important');
        p.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
        p.style.setProperty('animation', 'none', 'important');
        p.style.setProperty('-webkit-animation', 'none', 'important');
        p.style.setProperty('transition', 'none', 'important');
        p.style.setProperty('will-change', 'auto', 'important');
        p.style.setProperty('contain', 'none', 'important');
        p.style.setProperty('clip-path', 'none', 'important');
        p.style.setProperty('-webkit-clip-path', 'none', 'important');
        p.style.setProperty('mask', 'none', 'important');
        p.style.setProperty('-webkit-mask', 'none', 'important');
        p.style.setProperty('border-radius', '0px', 'important');
        p.style.setProperty('position', 'static', 'important');
        p.style.setProperty('z-index', '2147483640', 'important');

        const isMainScroller = (p.tagName === 'MAIN' || p.classList.contains('sx-main') || p.classList.contains('main-content-wrapper'));
        if (isMainScroller) {
          p.style.setProperty('overflow', 'hidden', 'important');
          p.style.setProperty('height', '100%', 'important');
          p.style.setProperty('max-height', '100%', 'important');
          p.style.setProperty('touch-action', 'none', 'important');
        } else {
          p.style.setProperty('overflow', 'visible', 'important');
        }
        p = p.parentElement;
      }

      document.documentElement.classList.add('sx-video-fs-lock');
      document.body.classList.add('sx-video-fs-lock');

      [document.documentElement, document.body].forEach(rootNode => {
        rootNode.style.setProperty('position', 'fixed', 'important');
        rootNode.style.setProperty('top', '0px', 'important');
        rootNode.style.setProperty('left', '0px', 'important');
        rootNode.style.setProperty('right', '0px', 'important');
        rootNode.style.setProperty('bottom', '0px', 'important');
        rootNode.style.setProperty('width', '100%', 'important');
        rootNode.style.setProperty('height', '100%', 'important');
        rootNode.style.setProperty('max-height', '100%', 'important');
        rootNode.style.setProperty('overflow', 'hidden', 'important');
        rootNode.style.setProperty('overscroll-behavior', 'none', 'important');
        rootNode.style.setProperty('touch-action', 'none', 'important');
        rootNode.style.setProperty('background', '#000000', 'important');
      });

      document.addEventListener('touchmove', this._onFsTouchMoveLock, { passive: false, capture: true });
      document.addEventListener('wheel', this._onFsTouchMoveLock, { passive: false, capture: true });
    }

    restoreAncestorsFromFullscreen() {
      document.removeEventListener('touchmove', this._onFsTouchMoveLock, { capture: true });
      document.removeEventListener('wheel', this._onFsTouchMoveLock, { capture: true });

      if (typeof this._savedHtmlCssText === 'string') {
        document.documentElement.style.cssText = this._savedHtmlCssText;
      }
      if (typeof this._savedBodyCssText === 'string') {
        document.body.style.cssText = this._savedBodyCssText;
      }
      if (typeof this._savedHostCssText === 'string') {
        this.hostEl.style.cssText = this._savedHostCssText;
      }

      if (this.fsAncestors && this.fsAncestors.length) {
        this.fsAncestors.forEach(item => {
          try {
            item.el.classList.remove('sx-fs-ancestor');
            item.el.style.cssText = item.cssText;
          } catch (e) {}
        });
        this.fsAncestors.forEach(item => {
          try {
            if (item.scrollTop) item.el.scrollTop = item.scrollTop;
            if (item.scrollLeft) item.el.scrollLeft = item.scrollLeft;
          } catch (e) {}
        });
      }
      this.fsAncestors = [];
      document.documentElement.classList.remove('sx-video-fs-lock');
      document.body.classList.remove('sx-video-fs-lock');

      if (this._savedWindowScroll && (this._savedWindowScroll.x || this._savedWindowScroll.y)) {
        try {
          window.scrollTo(this._savedWindowScroll.x, this._savedWindowScroll.y);
        } catch (e) {}
      }
    }

    syncFullscreenOrientation() {
      if (!this.isFullscreen) {
        this.root.classList.remove('sx-fs-tilted', 'sx-fs-landscape');
        this.root.style.removeProperty('position');
        this.root.style.removeProperty('top');
        this.root.style.removeProperty('left');
        this.root.style.removeProperty('width');
        this.root.style.removeProperty('height');
        this.root.style.removeProperty('max-width');
        this.root.style.removeProperty('max-height');
        this.root.style.removeProperty('transform');
        this.root.style.removeProperty('-webkit-transform');
        this.iconFsEnter.style.display = '';
        this.iconFsExit.style.display = 'none';
        return;
      }
      this.iconFsEnter.style.display = 'none';
      this.iconFsExit.style.display = '';

      const vv = window.visualViewport;
      const vw = Math.round((vv && vv.width) ? vv.width : (window.innerWidth || document.documentElement.clientWidth || 360));
      const vh = Math.round((vv && vv.height) ? vv.height : (window.innerHeight || document.documentElement.clientHeight || 640));
      const vTop = Math.round((vv && vv.offsetTop) ? vv.offsetTop : 0);
      const vLeft = Math.round((vv && vv.offsetLeft) ? vv.offsetLeft : 0);
      const isPortraitViewport = vh > vw;

      this.hostEl.style.setProperty('position', 'fixed', 'important');
      this.hostEl.style.setProperty('top', vTop + 'px', 'important');
      this.hostEl.style.setProperty('left', vLeft + 'px', 'important');
      this.hostEl.style.setProperty('width', vw + 'px', 'important');
      this.hostEl.style.setProperty('height', vh + 'px', 'important');
      this.hostEl.style.setProperty('max-width', vw + 'px', 'important');
      this.hostEl.style.setProperty('max-height', vh + 'px', 'important');
      this.hostEl.style.setProperty('margin', '0px', 'important');
      this.hostEl.style.setProperty('padding', '0px', 'important');
      this.hostEl.style.setProperty('border', '0px', 'important');
      this.hostEl.style.setProperty('border-radius', '0px', 'important');
      this.hostEl.style.setProperty('z-index', '2147483647', 'important');
      this.hostEl.style.setProperty('background', '#000000', 'important');
      this.hostEl.style.setProperty('overflow', 'hidden', 'important');
      this.hostEl.style.setProperty('touch-action', 'none', 'important');

      let shouldTilt = false;
      if (this.manualTiltMode === 'tilted') {
        shouldTilt = true;
      } else if (this.manualTiltMode === 'upright') {
        shouldTilt = false;
      } else {
        // Automatic: when on a portrait screen (mobile held upright), tilt 90deg into landscape;
        // when the phone is physically rotated into landscape (vw >= vh), use direct horizontal landscape!
        shouldTilt = isPortraitViewport;
      }

      if (shouldTilt) {
        this.root.classList.add('sx-fs-tilted');
        this.root.classList.remove('sx-fs-landscape');
        this.root.style.setProperty('position', 'absolute', 'important');
        this.root.style.setProperty('top', '50%', 'important');
        this.root.style.setProperty('left', '50%', 'important');
        this.root.style.setProperty('width', vh + 'px', 'important');
        this.root.style.setProperty('height', vw + 'px', 'important');
        this.root.style.setProperty('max-width', vh + 'px', 'important');
        this.root.style.setProperty('max-height', vw + 'px', 'important');
        this.root.style.setProperty('transform', 'translate(-50%, -50%) rotate(90deg)', 'important');
        this.root.style.setProperty('-webkit-transform', 'translate(-50%, -50%) rotate(90deg)', 'important');
      } else {
        this.root.classList.add('sx-fs-landscape');
        this.root.classList.remove('sx-fs-tilted');
        this.root.style.setProperty('position', 'absolute', 'important');
        this.root.style.setProperty('top', '0px', 'important');
        this.root.style.setProperty('left', '0px', 'important');
        this.root.style.setProperty('width', vw + 'px', 'important');
        this.root.style.setProperty('height', vh + 'px', 'important');
        this.root.style.setProperty('max-width', vw + 'px', 'important');
        this.root.style.setProperty('max-height', vh + 'px', 'important');
        this.root.style.setProperty('transform', 'none', 'important');
        this.root.style.setProperty('-webkit-transform', 'none', 'important');
      }
    }

    onNativeFullscreenChange() {
      const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
      if (!fsEl && this.isFullscreen && !this._usingCssFullscreenOnly) {
        this.exitFullscreen();
      } else if (fsEl === this.hostEl) {
        this.syncFullscreenOrientation();
      }
    }

    enterFullscreen() {
      this.isFullscreen = true;
      this.manualTiltMode = null;
      this._usingCssFullscreenOnly = true;
      this.unlockAncestorsForFullscreen();
      this.hostEl.classList.add('sx-ios-fs');
      this.syncFullscreenOrientation();
      this.wakeControls();

      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent || '') || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
      const target = this.hostEl;
      if (!isIOS && !document.fullscreenElement && !document.webkitFullscreenElement) {
        if (target.requestFullscreen) {
          target.requestFullscreen().then(() => {
            this._usingCssFullscreenOnly = false;
            if (screen.orientation && typeof screen.orientation.lock === 'function') {
              screen.orientation.lock('landscape').catch(() => {});
            }
            this.syncFullscreenOrientation();
          }).catch(() => {
            this._usingCssFullscreenOnly = true;
            this.syncFullscreenOrientation();
          });
        } else if (target.webkitRequestFullscreen) {
          try {
            target.webkitRequestFullscreen();
            this._usingCssFullscreenOnly = false;
          } catch (e) {
            this._usingCssFullscreenOnly = true;
          }
          this.syncFullscreenOrientation();
        }
      }
    }

    exitFullscreen() {
      this.isFullscreen = false;
      this.manualTiltMode = null;
      this._usingCssFullscreenOnly = false;
      this.hostEl.classList.remove('sx-ios-fs');
      this.root.classList.remove('sx-fs-tilted', 'sx-fs-landscape');
      this.syncFullscreenOrientation();
      this.restoreAncestorsFromFullscreen();

      if (screen.orientation && typeof screen.orientation.unlock === 'function') {
        try { screen.orientation.unlock(); } catch (e) {}
      }
      const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
      if (fsEl) {
        if (document.exitFullscreen) {
          document.exitFullscreen().catch(() => {});
        } else if (document.webkitExitFullscreen) {
          try { document.webkitExitFullscreen(); } catch (e) {}
        }
      }
    }

    toggleFullscreen() {
      if (this.isFullscreen) {
        this.exitFullscreen();
      } else {
        this.enterFullscreen();
      }
    }

    destroy() {
      if (this._destroyed) return;
      this._destroyed = true;
      try { if (this.isFullscreen) this.exitFullscreen(); } catch (e) {}
      if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; }
      [this.wakeTimer, this.toastTimer].forEach((tm) => { if (tm) clearTimeout(tm); });
      if (this.ytPlayer) {
        try { if (typeof this.ytPlayer.destroy === 'function') this.ytPlayer.destroy(); } catch (e) {}
        this.ytPlayer = null;
      }
      window.removeEventListener('resize', this._onWindowResize);
      window.removeEventListener('orientationchange', this._onWindowResize);
      if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', this._onWindowResize);
        window.visualViewport.removeEventListener('scroll', this._onWindowResize);
      }
      document.removeEventListener('fullscreenchange', this._onNativeFs);
      document.removeEventListener('webkitfullscreenchange', this._onNativeFs);
      document.documentElement.classList.remove('sx-video-fs-lock');
      document.body.classList.remove('sx-video-fs-lock');
      activePlayers.delete(this);
      instances.delete(this.hostEl);
    }
  }

  function upgradeElement(el) {
    if (!el || el.nodeType !== 1) return;
    const token = el.getAttribute('data-saxaz-video');
    if (instances.has(el)) {
      if (token) {
        el.removeAttribute('data-saxaz-video');
        instances.get(el).loadToken(token);
      }
      return;
    }
    if (token !== null) {
      instances.set(el, new ProtectedPlayer(el));
    }
  }

  function scanAll(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('[data-saxaz-video]').forEach(upgradeElement);
  }

  let sweepQueued = false;
  const sweepDetachedPlayers = () => {
    sweepQueued = false;
    activePlayers.forEach((pl) => {
      if (pl.hostEl && !pl.hostEl.isConnected) pl.destroy();
    });
  };
  const observer = new MutationObserver((mutations) => {
    if (!sweepQueued && activePlayers.size) {
      for (const m of mutations) {
        if (m.type === 'childList' && m.removedNodes.length) {
          sweepQueued = true;
          requestAnimationFrame(sweepDetachedPlayers);
          break;
        }
      }
    }
    for (const m of mutations) {
      if (m.type === 'attributes' && m.attributeName === 'data-saxaz-video') {
        upgradeElement(m.target);
      } else if (m.type === 'childList') {
        m.addedNodes.forEach(node => {
          if (node.nodeType === 1) {
            if (node.hasAttribute && node.hasAttribute('data-saxaz-video')) {
              upgradeElement(node);
            }
            scanAll(node);
          }
        });
      }
    }
  });

  function initObserver() {
    scanAll(document);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-saxaz-video']
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initObserver);
  } else {
    initObserver();
  }

  // Default any native HTML5 <video> elements to 0.75x playback speed
  document.addEventListener('loadedmetadata', (e) => {
    if (e.target && e.target.tagName === 'VIDEO' && !e.target._sxDefaultRateApplied) {
      e.target._sxDefaultRateApplied = true;
      try {
        e.target.defaultPlaybackRate = 0.75;
        e.target.playbackRate = 0.75;
      } catch (_err) {}
    }
  }, true);

  window.SaxazVideoVault = {
    scan: scanAll,
    pauseAll: function () {
      document.querySelectorAll('[data-saxaz-protected="true"]').forEach(el => {
        const inst = instances.get(el);
        if (inst) inst.pause();
      });
    }
  };
  window.saxazMountVaultPlayers = scanAll;
  window.SAXAZPlayer = {
    initAll: function () {
      scanAll(document);
    }
  };
})();
