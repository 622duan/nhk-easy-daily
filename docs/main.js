// ============================================
// 日本語ライフ — 共享 JS
// v4.7.1 — 2026-08-05 (跨 level 找 news + 从 body 提取词 + wordbook news context + spell 完整 game + spell input + keigo SVG 箭头 + NHK 按等级 + grammar/vocab +100)
// ============================================

// PWA standalone 检测: iOS 加到主屏后启动是 standalone 模式
// 此时 html 加 .pwa class, 触发 safe-area CSS 让 status bar 透明融入背景
(function() {
  const isStandalone =
    window.navigator.standalone === true ||  // iOS
    window.matchMedia('(display-mode: standalone)').matches;  // Android Chrome
  if (isStandalone) {
    document.documentElement.classList.add('pwa');
  }
})();

// 等级元信息
const LEVELS = ['N5', 'N4', 'N3', 'N2', 'N1'];
const LEVEL_INFO = {
  N5: { num: 'N5', name: '入门', desc: '入门基础', color: '#10B981' },
  N4: { num: 'N4', name: '基础', desc: '基础会话', color: '#0EA5E9' },
  N3: { num: 'N3', name: '中级', desc: '日常表达', color: '#F59E0B' },
  N2: { num: 'N2', name: '中高级', desc: '商务场景', color: '#8B5CF6' },
  N1: { num: 'N1', name: '高级', desc: '深度阅读', color: '#EF4444' }
};

// 当前等级（共享状态）
const State = {
  level: 'N5',
  setLevel(l) {
    if (!LEVEL_INFO[l]) return;
    this.level = l;
    // 同步所有 stepper
    document.querySelectorAll('.level-num').forEach(el => {
      el.textContent = l;
      el.style.color = LEVEL_INFO[l].color;
    });
    document.querySelectorAll('.level-desc').forEach(el => {
      el.textContent = LEVEL_INFO[l].name;
    });
    document.querySelectorAll('.level-display').forEach(el => {
      el.dataset.level = l;
    });
    // 更新 prev/next 按钮状态
    const idx = LEVELS.indexOf(l);
    document.querySelectorAll('.step-btn-prev').forEach(b => b.disabled = idx === 0);
    document.querySelectorAll('.step-btn-next').forEach(b => b.disabled = idx === LEVELS.length - 1);
    // 同步 Picker 选中状态
    document.querySelectorAll('.level-option').forEach(o => {
      o.classList.toggle('selected', o.dataset.level === l);
    });
    // 更新 body data-level（全局选择器）
    document.body.setAttribute('data-level', l);
    // 触发等级变化事件（页面可订阅）
    window.dispatchEvent(new CustomEvent('levelchange', { detail: { level: l } }));
    // 保存到 localStorage
    try { localStorage.setItem('jp_level', l); } catch(e) {}
  },
  init() {
    try {
      const saved = localStorage.getItem('jp_level');
      if (saved && LEVEL_INFO[saved]) this.level = saved;
    } catch(e) {}
  }
};

function changeLevel(delta) {
  const idx = LEVELS.indexOf(State.level);
  const newIdx = Math.max(0, Math.min(LEVELS.length - 1, idx + delta));
  State.setLevel(LEVELS[newIdx]);
}

function openLevelPicker() {
  const mask = document.getElementById('levelPicker');
  if (!mask) return;
  mask.classList.add('show');
}

function closeLevelPicker() {
  const mask = document.getElementById('levelPicker');
  if (!mask) return;
  mask.classList.remove('show');
}

function pickLevel(l) {
  State.setLevel(l);
  closeLevelPicker();
}

// 等级颜色映射
const LevelColor = {
  N5: '#10B981', N4: '#0EA5E9', N3: '#F59E0B',
  N2: '#8B5CF6', N1: '#EF4444'
};

// 等级 Badge 类名
const LevelBadge = {
  N5: 'badge-n5', N4: 'badge-n4', N3: 'badge-n3',
  N2: 'badge-n2', N1: 'badge-n1'
};

// TTS (优先选高质量日语 native voice)
// 设备 native 语音: iOS Otoya/Kyoko/Sayuri (Neural), Android ja-JP-x-...
// Web Speech API 选最佳日语 voice
function _getBestJapaneseVoice() {
  if (!('speechSynthesis' in window)) return null;
  const voices = speechSynthesis.getVoices();
  if (!voices.length) return null;

  // 优先 iOS 的 native high-quality voices (Otoya, Kyoko, Sayuri, Hattori, Maki)
  const preferredNames = [
    'Kyoko', 'Otoya', 'Sayuri', 'Hattori', 'Maki',     // iOS Japanese Neural
    'Google 日本語', 'Microsoft Nanami', 'Microsoft Ayumi',  // Google/MS Edge
    'Samantha', 'Alex',                                  // macOS fallback
  ];
  for (const name of preferredNames) {
    const v = voices.find(v => v.name.includes(name));
    if (v) return v;
  }

  // 退而求其次: 任何 ja-JP voice
  return voices.find(v => v.lang === 'ja-JP')
      || voices.find(v => v.lang.startsWith('ja'))
      || null;
}

// 共享 kana audio player (避免每个 cell 单独 <audio>)
let _kanaAudio = null;
function _getKanaAudio() {
  if (!_kanaAudio) {
    _kanaAudio = new Audio();
    _kanaAudio.preload = 'none';
  }
  return _kanaAudio;
}

// 单 kana 字符 (平假/片假/拗音) 走真人 TTS mp3
// 例: 'あ' 'きゃ' 'ガ' 'キョ'
const _KANA_RE = /^[\u3040-\u309f\u30a0-\u30ff]$/;

function speak(text, opts = {}) {
  // 1. 优先用真人 TTS mp3 (kana 单字)
  if (_KANA_RE.test(text) && !opts.useWeb) {
    const audio = _getKanaAudio();
    audio.pause();
    audio.currentTime = 0;
    audio.src = `https://cdn.jsdelivr.net/gh/622duan/nhk-easy-daily@main/data/audio/kana-${text}.mp3`;
    audio.playbackRate = opts.rate || 1.0;  // mp3 已 0.8 speed 录好
    const p = audio.play();
    if (p && p.catch) p.catch(() => {
      // mp3 失败 (offline / 404) → fallback 到 Web Speech API
      _speakWeb(text, opts);
    });
    return;
  }

  _speakWeb(text, opts);
}

function _speakWeb(text, opts = {}) {
  if (!('speechSynthesis' in window)) {
    console.warn('[speak] speechSynthesis not supported');
    return;
  }
  // 取消之前的 (避免叠加)
  speechSynthesis.cancel();

  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ja-JP';
  // 自然语速: 0.9 偏慢但更清晰, 适合学习
  u.rate = opts.rate || 0.9;
  u.pitch = opts.pitch || 1.0;
  u.volume = opts.volume || 1.0;

  const voice = _getBestJapaneseVoice();
  if (voice) {
    u.voice = voice;
    // iOS voice 设 lang 无效, 必须用 voice.lang 同步
    u.lang = voice.lang || 'ja-JP';
  }
  speechSynthesis.speak(u);
}

// 异步等待 voices 加载 (Chrome 需要)
if ('speechSynthesis' in window) {
  speechSynthesis.onvoiceschanged = () => {
    // 触发一次空查询让 voices 列表填充
    speechSynthesis.getVoices();
  };
}

// 单词本数据（demo）
const WordBook = {
  get(key) {
    try {
      const data = JSON.parse(localStorage.getItem('jp_wordbook') || '[]');
      return data;
    } catch(e) { return []; }
  },
  add(word) {
    const list = this.get();
    if (list.find(w => w.id === word.id)) return false;
    list.unshift({ ...word, added_at: Date.now() });
    try { localStorage.setItem('jp_wordbook', JSON.stringify(list)); } catch(e) {}
    return true;
  },
  remove(id) {
    const list = this.get().filter(w => w.id !== id);
    try { localStorage.setItem('jp_wordbook', JSON.stringify(list)); } catch(e) {}
  },
  has(id) {
    return this.get().some(w => w.id === id);
  }
};

// 翻卡
function flipCard(el) {
  el.classList.toggle('flipped');
}

// 标签切换
function switchTab(barSelector, target) {
  document.querySelectorAll(barSelector + ' .tab').forEach(t => {
    t.classList.toggle('active', t === target);
  });
  const tabs = barSelector + ' .tab';
  document.querySelectorAll(tabs).forEach(t => {
    t.addEventListener('click', () => switchTab(barSelector, t));
  });
}

// 初始化
State.init();

// 生成等级 Stepper HTML
function stepperHTML() {
  const l = State.level;
  const info = LEVEL_INFO[l];
  const idx = LEVELS.indexOf(l);
  return `
    <div class="level-stepper-wrap">
      <div class="level-stepper">
        <button class="step-btn step-btn-prev" onclick="changeLevel(-1)" ${idx === 0 ? 'disabled' : ''}>
          <i class="fas fa-chevron-left"></i>
        </button>
        <div class="level-display" data-level="${l}" onclick="openLevelPicker()">
          <span class="level-num" style="color: ${info.color};">${l}</span>
          <span class="level-desc">${info.name}</span>
        </div>
        <button class="step-btn step-btn-next" onclick="changeLevel(1)" ${idx === LEVELS.length - 1 ? 'disabled' : ''}>
          <i class="fas fa-chevron-right"></i>
        </button>
      </div>
    </div>
  `;
}

// 生成等级 Picker Modal HTML
function pickerHTML() {
  return `
    <div class="level-picker-mask" id="levelPicker" onclick="if(event.target===this) closeLevelPicker()">
      <div class="level-picker">
        <div class="handle"></div>
        <h3>选择等级</h3>
        ${LEVELS.map(l => {
          const info = LEVEL_INFO[l];
          return `
            <div class="level-option ${l === State.level ? 'selected' : ''}" data-level="${l}" onclick="pickLevel('${l}')">
              <span class="pill" style="background: ${info.color};">${l}</span>
              <div>
                <div class="name">${info.name} · ${l}</div>
                <div class="sub">${info.desc}</div>
              </div>
              <i class="fas fa-check check"></i>
            </div>
          `;
        }).join('')}
        <div style="height: 20px;"></div>
      </div>
    </div>
  `;
}

// 自动注入：页面上任何 [data-auto-stepper] 会被替换为 stepper
function autoInjectStepper() {
  document.querySelectorAll('[data-auto-stepper]').forEach(el => {
    el.outerHTML = stepperHTML();
  });
  // Picker 插在 body 末尾（仅一次）
  if (!document.getElementById('levelPicker')) {
    const div = document.createElement('div');
    div.innerHTML = pickerHTML();
    document.body.appendChild(div.firstElementChild);
  }
  // 同步状态
  State.setLevel(State.level);
}

// 暴露全局
window.JP = { State, speak, WordBook, LevelColor, LevelBadge, flipCard, changeLevel, openLevelPicker, closeLevelPicker, pickLevel, LEVELS, LEVEL_INFO, autoInjectStepper };

// v4.8 — TTS 优化: 选最佳日语 native voice (iOS Otoya/Kyoko/Sayuri, Android ja-JP enhanced)
// + news-detail audio: NHK 原声 + TTS 兜底, 进度条动态更新

// DOM Ready 后自动注入
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoInjectStepper);
} else {
  autoInjectStepper();
}
