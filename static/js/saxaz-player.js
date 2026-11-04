/**
 * SAXAZ Protected Video Vault & Custom Player Engine
 * - Eliminates raw YouTube URLs from DOM / Inspect Element (uses server-signed vtok_ tokens + closed Shadow DOM)
 * - Blocks all clicks on YouTube logo, title, Share, Watch Later, and "Watch on YouTube" via pointer-events shield + overscan crop
 * - Blocks all YouTube pause/end-screen "More videos" suggestions via instant blackout curtain
 * - Works universally across Jinja2, HTMX, and Alpine.js templates
 */
(function () {
  if (window.SaxazVideoVault) return;

  let ytApiReady = false;
  let ytApiCallbacks = [];
  let ytScriptLoaded = false;

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
    }
    .sx-root {
      position: relative;
      width: 100%;
      height: 100%;
      background: #0a0a0c;
      overflow: hidden;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #ffffff;
    }
    .sx-viewport {
      position: absolute;
      inset: 0;
      overflow: hidden;
      pointer-events: none !important;
    }
    /* Overscan crop pushes YouTube top title/share bar and bottom watermark outside visible bounds */
    .sx-frame-crop {
      position: absolute;
      top: -68px;
      left: -2px;
      width: calc(100% + 4px);
      height: calc(100% + 136px);
      pointer-events: none !important;
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
    /* Curtain hides YouTube pause/end suggestions and initial title/share overlays */
    .sx-curtain {
      position: absolute;
      inset: 0;
      z-index: 15;
      background: radial-gradient(circle at center, rgba(18, 18, 22, 0.92) 0%, rgba(10, 10, 14, 0.98) 100%);
      backdrop-filter: blur(12px);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 14px;
      transition: opacity 0.18s ease;
      cursor: pointer;
    }
    .sx-curtain.sx-hidden {
      opacity: 0;
      pointer-events: none;
    }
    .sx-big-play {
      width: 72px;
      height: 72px;
      border-radius: 9999px;
      background: #F4AA00;
      color: #141414;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 10px 30px rgba(244, 170, 0, 0.45);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .sx-curtain:hover .sx-big-play {
      transform: scale(1.08);
      box-shadow: 0 14px 36px rgba(244, 170, 0, 0.65);
    }
    .sx-curtain-label {
      font-size: 13px;
      font-weight: 800;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: rgba(255, 255, 255, 0.85);
    }
    .sx-badge {
      position: absolute;
      top: 14px;
      left: 16px;
      z-index: 20;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 9999px;
      background: rgba(15, 15, 20, 0.72);
      backdrop-filter: blur(6px);
      border: 1px solid rgba(244, 170, 0, 0.3);
      font-size: 10px;
      font-weight: 800;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #F4AA00;
      pointer-events: none;
    }
    /* Custom Control Bar */
    .sx-controls {
      position: absolute;
      left: 12px;
      right: 12px;
      bottom: 12px;
      z-index: 25;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.95);
      color: #18181b;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(0, 0, 0, 0.08);
      transition: opacity 0.25s ease, transform 0.25s ease;
    }
    .sx-root.sx-playing:not(:hover) .sx-controls {
      opacity: 0;
      transform: translateY(6px);
    }
    .sx-btn {
      background: transparent;
      border: none;
      color: #18181b;
      width: 32px;
      height: 32px;
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
    .sx-progress-wrap {
      flex: 1;
      display: flex;
      align-items: center;
      height: 24px;
      cursor: pointer;
      position: relative;
    }
    .sx-range {
      -webkit-appearance: none;
      appearance: none;
      width: 100%;
      height: 7px;
      border-radius: 999px;
      background: linear-gradient(to right, #F4AA00 0%, #F4AA00 0%, #e4e4e7 0%, #e4e4e7 100%);
      outline: none;
      cursor: pointer;
    }
    .sx-range::-webkit-slider-runnable-track {
      height: 7px;
      border-radius: 999px;
      background: transparent;
    }
    .sx-range::-moz-range-progress {
      background-color: #F4AA00;
      height: 7px;
      border-radius: 999px;
    }
    .sx-range::-moz-range-track {
      background-color: #e4e4e7;
      height: 7px;
      border-radius: 999px;
    }
    .sx-range::-webkit-slider-thumb {
      -webkit-appearance: none;
      appearance: none;
      width: 16px;
      height: 16px;
      margin-top: -4.5px;
      border-radius: 50%;
      background: #F4AA00;
      border: 2.5px solid #ffffff;
      box-shadow: 0 1px 5px rgba(0,0,0,0.35);
      cursor: pointer;
      transition: transform 0.12s ease;
    }
    .sx-range:hover::-webkit-slider-thumb {
      transform: scale(1.15);
    }
    .sx-range::-moz-range-thumb {
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: #F4AA00;
      border: 2.5px solid #ffffff;
      box-shadow: 0 1px 5px rgba(0,0,0,0.35);
      cursor: pointer;
    }
    .sx-time {
      font-size: 12px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      color: #3f3f46;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .sx-speed {
      background: #f4f4f5;
      border: 1px solid #e4e4e7;
      color: #18181b;
      font-size: 11px;
      font-weight: 800;
      border-radius: 999px;
      padding: 4px 8px;
      cursor: pointer;
      outline: none;
    }
    @media (max-width: 640px) {
      .sx-badge {
        top: 8px;
        left: 8px;
        padding: 3px 8px;
        font-size: 8.5px;
        gap: 4px;
      }
      .sx-big-play {
        width: 54px;
        height: 54px;
      }
      .sx-curtain-label {
        font-size: 11px;
      }
      .sx-controls {
        left: 6px;
        right: 6px;
        bottom: 6px;
        gap: 5px;
        padding: 5px 8px;
        border-radius: 12px;
      }
      .sx-btn {
        width: 26px;
        height: 26px;
      }
      .sx-time {
        font-size: 10px;
      }
      .sx-speed {
        font-size: 10px;
        padding: 2px 5px;
      }
      .sx-progress-wrap {
        min-width: 56px;
      }
    }
  `;

  const instances = new WeakMap();
  const activePlayers = new Set();

  // Block F12 / Ctrl+Shift+I / Ctrl+Shift+C / Ctrl+Shift+J / Ctrl+U when protected videos exist on page
  window.addEventListener('keydown', (e) => {
    if (activePlayers.size === 0) return;
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
      this.hostEl = hostEl;
      this.contentId = hostEl.getAttribute('data-content-id') || '';
      const initialToken = hostEl.getAttribute('data-saxaz-video') || '';
      // Strip attribute from DOM so Inspect Element doesn't show even the token
      hostEl.removeAttribute('data-saxaz-video');
      hostEl.setAttribute('data-saxaz-protected', 'true');

      // Attach CLOSED Shadow DOM so element.shadowRoot is null in DevTools console
      this.shadow = hostEl.attachShadow({ mode: 'closed' });
      this.ytPlayer = null;
      this.pollTimer = null;
      this.isPlaying = false;
      this.isEnded = false;
      this.isMuted = false;
      this.isMounting = false;
      this.duration = 0;
      this.resumeTime = 0;
      this.currentToken = null;

      activePlayers.add(this);
      this.buildUI();
      if (initialToken) {
        this.loadToken(initialToken);
      }
    }

    buildUI() {
      const style = document.createElement('style');
      style.textContent = PLAYER_CSS;

      this.root = document.createElement('div');
      this.root.className = 'sx-root';
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
        <div class="sx-shield" title="Click to Play/Pause"></div>
        <div class="sx-curtain">
          <div class="sx-big-play">
            <svg class="sx-curtain-icon" width="32" height="32" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z"/>
            </svg>
          </div>
          <div class="sx-curtain-label">Click to Play Video</div>
        </div>
        <div class="sx-controls">
          <button type="button" class="sx-btn sx-btn-primary sx-play-btn" title="Play / Pause">
            <svg class="sx-icon-play" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
            <svg class="sx-icon-pause" width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
          </button>
          <button type="button" class="sx-btn sx-rew-btn" title="Rewind 10s">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
          </button>
          <div class="sx-progress-wrap">
            <input type="range" class="sx-range" min="0" max="1000" value="0" step="1">
          </div>
          <span class="sx-time">0:00 / 0:00</span>
          <button type="button" class="sx-btn sx-mute-btn" title="Mute / Unmute">
            <svg class="sx-icon-vol" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
            <svg class="sx-icon-muted" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="display:none;"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>
          </button>
          <select class="sx-speed" title="Playback Speed">
            <option value="0.75">0.75x</option>
            <option value="1" selected>1x</option>
            <option value="1.25">1.25x</option>
            <option value="1.5">1.5x</option>
            <option value="2">2x</option>
          </select>
          <button type="button" class="sx-btn sx-fs-btn" title="Fullscreen">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
          </button>
        </div>
      `;

      this.shadow.appendChild(style);
      this.shadow.appendChild(this.root);

      this.frameCropEl = this.root.querySelector('.sx-frame-crop');
      this.mountEl = this.root.querySelector('.sx-yt-mount');
      this.shieldEl = this.root.querySelector('.sx-shield');
      this.curtainEl = this.root.querySelector('.sx-curtain');
      this.curtainLabelEl = this.root.querySelector('.sx-curtain-label');
      this.playBtn = this.root.querySelector('.sx-play-btn');
      this.iconPlay = this.root.querySelector('.sx-icon-play');
      this.iconPause = this.root.querySelector('.sx-icon-pause');
      this.rewBtn = this.root.querySelector('.sx-rew-btn');
      this.rangeEl = this.root.querySelector('.sx-range');
      this.timeEl = this.root.querySelector('.sx-time');
      this.muteBtn = this.root.querySelector('.sx-mute-btn');
      this.iconVol = this.root.querySelector('.sx-icon-vol');
      this.iconMuted = this.root.querySelector('.sx-icon-muted');
      this.speedEl = this.root.querySelector('.sx-speed');
      this.fsBtn = this.root.querySelector('.sx-fs-btn');

      const togglePlay = (e) => {
        if (e) e.stopPropagation();
        this.togglePlay();
      };

      this.shieldEl.addEventListener('click', togglePlay);
      this.shieldEl.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        this.toggleFullscreen();
      });
      this.curtainEl.addEventListener('click', togglePlay);
      this.playBtn.addEventListener('click', togglePlay);

      this.rewBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!this.ytPlayer || typeof this.ytPlayer.getCurrentTime !== 'function') return;
        const t = Math.max(0, (this.ytPlayer.getCurrentTime() || 0) - 10);
        this.resumeTime = t;
        this.ytPlayer.seekTo(t, true);
        if (this.duration > 0) {
          this.updateSeekVisual((t / this.duration) * 1000);
          this.updateTimeUI(t, this.duration);
        }
      });

      this.rangeEl.addEventListener('input', (e) => {
        e.stopPropagation();
        const rawVal = parseFloat(this.rangeEl.value) || 0;
        this.updateSeekVisual(rawVal);
        if (!this.ytPlayer || !this.duration) return;
        const target = (rawVal / 1000) * Math.max(0, this.duration - 0.5);
        this.resumeTime = target;
        this.ytPlayer.seekTo(target, true);
        this.updateTimeUI(target, this.duration);
      });

      this.muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
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

      this.speedEl.addEventListener('change', (e) => {
        e.stopPropagation();
        if (this.ytPlayer && typeof this.ytPlayer.setPlaybackRate === 'function') {
          this.ytPlayer.setPlaybackRate(parseFloat(this.speedEl.value) || 1);
        }
      });

      this.fsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleFullscreen();
      });
    }

    updateSeekVisual(pctPermille) {
      const clamped = Math.min(1000, Math.max(0, Math.round(pctPermille || 0)));
      const pct = (clamped / 1000) * 100;
      this.rangeEl.value = String(clamped);
      this.rangeEl.style.background = `linear-gradient(to right, #F4AA00 0%, #F4AA00 ${pct}%, #e4e4e7 ${pct}%, #e4e4e7 100%)`;
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
      this.root.classList.remove('sx-playing');
      this.iconPlay.style.display = '';
      this.iconPause.style.display = 'none';
      this.frameCropEl.innerHTML = '<div class="sx-yt-mount"></div>';
      this.mountEl = this.frameCropEl.querySelector('.sx-yt-mount');
      this.showCurtain(message || 'Click to Play Video');
    }

    loadToken(token) {
      if (!token || token === this.currentToken) return;
      this.currentToken = token;
      this.resumeTime = 0;
      this.duration = 0;
      this.isEnded = false;
      this.updateSeekVisual(0);
      this.updateTimeUI(0, 0);
      // Do not mount the iframe until the user clicks Play (zero iframe in DOM while idle)
      this.purgeFrame('Click to Play Video');
    }

    async mountAndPlay() {
      if (this.isMounting || !this.currentToken) return;
      this.isMounting = true;
      this.showCurtain('Loading Video...');
      const videoId = await resolveToken(this.currentToken);
      if (!videoId) {
        this.isMounting = false;
        this.showCurtain('Video Unavailable');
        return;
      }

      ensureYouTubeApi(() => {
        const startSec = this.isEnded ? 0 : Math.floor(this.resumeTime || 0);
        this.isEnded = false;
        this.ytPlayer = new window.YT.Player(this.mountEl, {
          width: '100%',
          height: '100%',
          host: 'https://www.youtube-nocookie.com',
          videoId: videoId,
          playerVars: {
            autoplay: 1,
            start: startSec,
            controls: 0,
            rel: 0,
            modestbranding: 1,
            iv_load_policy: 3,
            disablekb: 1,
            fs: 0,
            playsinline: 1,
            origin: window.location.origin
          },
          events: {
            onReady: () => {
              this.isMounting = false;
              this.duration = this.ytPlayer.getDuration() || 0;
              if (this.resumeTime > 0 && typeof this.ytPlayer.seekTo === 'function') {
                this.ytPlayer.seekTo(this.resumeTime, true);
              }
              const rate = parseFloat(this.speedEl.value) || 1;
              if (rate !== 1 && typeof this.ytPlayer.setPlaybackRate === 'function') {
                this.ytPlayer.setPlaybackRate(rate);
              }
              this.ytPlayer.playVideo();
              this.startMonitor();
            },
            onStateChange: (ev) => this.onStateChange(ev)
          }
        });
      });
    }

    onStateChange(ev) {
      const YTS = window.YT.PlayerState;
      if (ev.data === YTS.PLAYING) {
        this.isPlaying = true;
        this.isEnded = false;
        this.duration = this.ytPlayer.getDuration() || this.duration;
        this.hideCurtain();
        this.root.classList.add('sx-playing');
        this.iconPlay.style.display = 'none';
        this.iconPause.style.display = '';
      } else if (ev.data === YTS.PAUSED) {
        this.isPlaying = false;
        this.root.classList.remove('sx-playing');
        this.iconPlay.style.display = '';
        this.iconPause.style.display = 'none';
        if (this.ytPlayer && typeof this.ytPlayer.getCurrentTime === 'function') {
          this.resumeTime = this.ytPlayer.getCurrentTime() || this.resumeTime;
        }
        // Immediately cover YouTube's pause recommendations ("More videos")
        this.showCurtain(this.isEnded ? 'Replay Video' : 'Paused — Click to Continue');
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
      this.iconPlay.style.display = '';
      this.iconPause.style.display = 'none';
      this.showCurtain('Replay Video');

      // Trigger auto-complete if inside content_view.html
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
      this.pollTimer = setInterval(() => {
        if (!this.ytPlayer || typeof this.ytPlayer.getCurrentTime !== 'function') return;
        const cur = this.ytPlayer.getCurrentTime() || 0;
        const dur = this.ytPlayer.getDuration() || this.duration || 0;
        if (dur > 0) {
          this.duration = dur;
          this.resumeTime = cur;
          // Intercept 0.45s before the end so YouTube's end-screen suggestions never render
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
      this.curtainLabelEl.textContent = label || 'Click to Play Video';
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

    toggleFullscreen() {
      const target = this.hostEl;
      if (target.classList.contains('sx-ios-fs')) {
        target.classList.remove('sx-ios-fs');
        return;
      }
      if (!document.fullscreenElement && !document.webkitFullscreenElement) {
        if (target.requestFullscreen) {
          target.requestFullscreen().catch(() => target.classList.add('sx-ios-fs'));
        } else if (target.webkitRequestFullscreen) {
          target.webkitRequestFullscreen();
        } else {
          target.classList.add('sx-ios-fs');
        }
      } else {
        if (document.exitFullscreen) document.exitFullscreen();
        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      }
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

  const observer = new MutationObserver((mutations) => {
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

  window.SaxazVideoVault = {
    scan: scanAll,
    pauseAll: function () {
      document.querySelectorAll('[data-saxaz-protected="true"]').forEach(el => {
        const inst = instances.get(el);
        if (inst) inst.pause();
      });
    }
  };
})();
