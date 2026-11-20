class AudioManager {
    constructor() {
        this.context = new (window.AudioContext || window.webkitAudioContext)();
        this.buffers = {};
        
        // Define paths to synthesized SFX
        this.sounds = {
            hover: '/static/sfx/hover.wav',
            click: '/static/sfx/click.wav',
            success: '/static/sfx/success.wav',
            error: '/static/sfx/error.wav',
            select: '/static/sfx/select.wav',
            swoosh: '/static/sfx/swoosh.wav',
            start: '/static/sfx/start.wav',
            finish: '/static/sfx/finish.wav',
            typing: '/static/sfx/typing.wav',
            submit: '/static/sfx/submit.wav'
        };
        
        this.typingSource = null;
        this.scheduleLoad();
    }

    // Sounds are fetched after the page has finished loading (and not at all when sound effects are off),
    // so they never compete with the page's own pictures and scripts.
    scheduleLoad() {
        const start = () => {
            const mode = window.USER_SFX_MODE !== undefined ? window.USER_SFX_MODE : 1;
            if (mode === 0) return;
            if ('requestIdleCallback' in window) window.requestIdleCallback(() => this.init(), { timeout: 3000 });
            else setTimeout(() => this.init(), 800);
        };
        if (document.readyState === 'complete') start();
        else window.addEventListener('load', start, { once: true });
    }

    async init() {
        if (this._loading) return;
        this._loading = true;
        for (const [name, path] of Object.entries(this.sounds)) {
            try {
                const response = await fetch(path);
                const arrayBuffer = await response.arrayBuffer();
                this.buffers[name] = await this.context.decodeAudioData(arrayBuffer);
            } catch (e) {
                console.warn(`Failed to load SFX: ${name}`, e);
            }
        }
        
        this.attachGlobalListeners();
    }

    play(name, volume = 1.0, loop = false) {
        // Mode 0 = Off, 1 = On, 2 = Custom
        const mode = window.USER_SFX_MODE !== undefined ? window.USER_SFX_MODE : 1;
        if (mode === 0) return null;
        
        if (mode === 2) {
            const config = window.USER_SFX_CUSTOM_CONFIG || {};
            // If custom mode is on, but this specific sound is toggled off
            if (config[name] === false) return null;
        }

        if (!this.buffers[name]) return null;
        
        if (this.context.state === 'suspended') {
            this.context.resume();
        }

        const source = this.context.createBufferSource();
        const gainNode = this.context.createGain();
        
        source.buffer = this.buffers[name];
        source.loop = loop;
        gainNode.gain.value = volume;
        
        source.connect(gainNode);
        gainNode.connect(this.context.destination);
        
        source.start(0);
        return source;
    }
    
    // Quick helpers
    playHover() { this.play('hover', 0.2); }
    playClick() { this.play('click', 0.3); }
    playSuccess() { this.play('success', 0.5); }
    playError() { this.play('error', 0.5); }
    playSelect() { this.play('select', 0.3); }
    playSwoosh() { this.play('swoosh', 0.2); }
    playStart() { this.play('start', 0.5); }
    playFinish() { this.play('finish', 0.5); }
    playSubmit() { this.play('submit', 0.4); }
    
    startTyping() {
        if (this.typingSource) return;
        this.typingSource = this.play('typing', 0.15, true);
    }
    
    stopTyping() {
        if (this.typingSource) {
            try { this.typingSource.stop(); } catch (e) {}
            this.typingSource = null;
        }
    }

    attachGlobalListeners() {
        document.addEventListener('mouseenter', (e) => {
            const target = e.target;
            if (target && target.matches && (
                target.matches('button, a, .btn, input[type="submit"], input[type="button"], select, .card')
            )) {
                this.playHover();
            }
        }, true); // Use capture phase for delegated events

        document.addEventListener('mousedown', (e) => {
            // UNLOCK AUDIO CONTEXT GLOBALLY ON FIRST INTERACTION
            if (this.context.state === 'suspended') {
                this.context.resume();
            }

            const target = e.target;
            if (target && target.matches && (
                target.matches('button, a, .btn, input[type="submit"], input[type="button"], select')
            )) {
                // If it's a radio/checkbox label or input, maybe use 'select' instead
                if (target.matches('input[type="radio"], input[type="checkbox"]')) {
                    this.playSelect();
                } else {
                    this.playClick();
                }
            }
            // For labels associated with inputs
            const closestLabel = target.closest('label');
            if (closestLabel && closestLabel.querySelector('input[type="radio"], input[type="checkbox"]')) {
                this.playSelect();
            }
        }, true);
    }
}

// Initialize globally on load
window.SFX = new AudioManager();
