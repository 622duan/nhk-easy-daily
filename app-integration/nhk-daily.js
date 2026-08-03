// ============================================
// nhk-daily.js — NHK 每日新闻自动合并模块
// 部署: 在 app 主 JS 加载后, 异步执行
// 数据源: GitHub raw JSON (由 GitHub Actions 每天生成)
// 失败行为: 静默降级, 不影响 app 使用
// ============================================

(function() {
  'use strict';

  // 配置: 改成你的 GitHub repo 路径
  // 格式: 'https://raw.githubusercontent.com/<user>/<repo>/main/data/nhk-app-format.json'
  const NHK_DAILY_URL = (function() {
    // 支持自定义: window.NHK_DAILY_URL = '...' (在 index.html 里设置)
    if (typeof window.NHK_DAILY_URL === 'string') return window.NHK_DAILY_URL;
    // 默认值 — 用占位符, 用户部署时改
    return 'https://raw.githubusercontent.com/<YOUR_GITHUB_USER>/<YOUR_REPO>/main/data/nhk-app-format.json';
  })();

  const CACHE_KEY = 'nhk_daily_cache';
  const CACHE_TTL = 24 * 60 * 60 * 1000;  // 24 小时

  /**
   * 从 localStorage 读缓存
   */
  function getCache() {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (Date.now() - obj.cached_at > CACHE_TTL) return null;
      return obj;
    } catch (e) {
      return null;
    }
  }

  /**
   * 写缓存
   */
  function setCache(data) {
    try {
      localStorage.setItem(CACHE_KEY, JSON.stringify({
        cached_at: Date.now(),
        data: data
      }));
    } catch (e) {}
  }

  /**
   * 把 NHK daily items 合并到 JP_DATA
   * 默认放到 N3.newsList 前面 (最新在前)
   */
  function mergeIntoJPData(items, level) {
    if (!window.JP_DATA) {
      console.warn('[NHK daily] JP_DATA not loaded yet, skip');
      return false;
    }
    if (!window.JP_DATA[level]) {
      console.warn('[NHK daily] level not found:', level);
      return false;
    }
    if (!Array.isArray(window.JP_DATA[level].newsList)) {
      window.JP_DATA[level].newsList = [];
    }

    // 标记每条
    items.forEach(item => {
      item.is_nhk_daily = true;
      item.fetched_at_marker = 'daily';
    });

    // 合并: 新内容放最前
    window.JP_DATA[level].newsList = items.concat(window.JP_DATA[level].newsList);

    // 触发事件, 通知 UI 重新渲染
    window.dispatchEvent(new CustomEvent('nhk-daily-loaded', {
      detail: { level: level, items: items, count: items.length }
    }));

    return true;
  }

  /**
   * 显示今日 NHK 速递横幅 (UI 集成)
   * 在 N3 等级 news-list 顶部插入一条横幅
   */
  function showDailyBanner(items) {
    const newsListPage = document.querySelector('[data-page="news-list"], .news-list');
    if (!newsListPage) return;

    // 检查是否已存在 (避免重复)
    if (newsListPage.querySelector('.nhk-daily-banner')) return;

    const banner = document.createElement('div');
    banner.className = 'nhk-daily-banner';
    banner.style.cssText = `
      background: linear-gradient(135deg, #DC2626 0%, #EF4444 100%);
      color: white;
      padding: 14px 16px;
      border-radius: 12px;
      margin: 12px 16px;
      box-shadow: 0 4px 12px rgba(220,38,38,0.25);
      display: flex;
      align-items: center;
      gap: 12px;
      cursor: pointer;
    `;
    banner.innerHTML = `
      <div style="font-size:24px;">📰</div>
      <div style="flex:1;">
        <div style="font-weight:600;font-size:14px;">今日 NHK 速递</div>
        <div style="font-size:12px;opacity:0.9;margin-top:2px;">${items.length} 篇最新日语新闻已更新</div>
      </div>
      <div style="font-size:18px;">›</div>
    `;
    banner.onclick = () => {
      // 跳到第一条 NHK 文章
      if (items[0]) {
        location.href = `news-detail.html?id=${items[0].id}`;
      }
    };

    // 插到列表最前
    const firstChild = newsListPage.querySelector('.news-item, .news-card, ul, .list');
    if (firstChild && firstChild.parentNode === newsListPage) {
      newsListPage.insertBefore(banner, firstChild);
    } else {
      newsListPage.appendChild(banner);
    }
  }

  /**
   * 主函数: 异步加载并合并
   */
  async function load() {
    // 1. 先尝试缓存
    const cached = getCache();
    if (cached) {
      const ok = mergeIntoJPData(cached.data.items, cached.data.default_level);
      if (ok) {
        showDailyBanner(cached.data.items);
        console.log('[NHK daily] loaded from cache:', cached.data.items.length, 'items');
        return;
      }
    }

    // 2. 缓存没命中, 异步 fetch
    try {
      const resp = await fetch(NHK_DAILY_URL, { cache: 'no-cache' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);

      const data = await resp.json();
      if (!data.items || !Array.isArray(data.items) || data.items.length === 0) {
        console.log('[NHK daily] no items in response');
        return;
      }

      setCache(data);
      const ok = mergeIntoJPData(data.items, data.default_level || 'N3');
      if (ok) {
        showDailyBanner(data.items);
        console.log('[NHK daily] loaded fresh:', data.items.length, 'items');
      }
    } catch (e) {
      // 静默失败, 不影响 app
      console.log('[NHK daily] fetch failed (silent):', e.message);
    }
  }

  // 暴露到全局, 方便调试
  window.NHKDaily = { load, mergeIntoJPData, getCache };

  // 等 JP_DATA 加载完再跑
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    // 再等一帧, 确保 data.js 已注入
    setTimeout(load, 100);
  }
})();
