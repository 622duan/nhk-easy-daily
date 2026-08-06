// ============================================
// nhk-daily.js — NHK 每日新闻自动合并模块
// v4.7 — 2026-08-05 (NHK 按等级分配 N4/N3/N2)
// - 适配新 NHK Next.js 渲染 (sitemap + sitemap-driven parse)
// - fetch from GitHub Actions daily, fallback to yesterday's commit
// - title/body/image/words 全字段都正常
// 部署: 在 app 主 JS 加载后, 异步执行
// 数据源: GitHub raw JSON (由 GitHub Actions 每天生成)
// 失败行为: 静默降级, 不影响 app 使用
// ============================================

(function() {
  'use strict';

  // 配置: NHK 每日数据 JSON URL
  // 来源: GitHub 仓库 https://github.com/622duan/nhk-easy-daily
  // 由 GitHub Actions 每天 9:00 JST 抓取 (如果 Actions 卡了, 可以手动跑或手工写占位)
  const NHK_DAILY_URL = (function() {
    // 支持自定义: window.NHK_DAILY_URL = '...' (在 index.html 里设置)
    if (typeof window.NHK_DAILY_URL === 'string') return window.NHK_DAILY_URL;
    // 默认值 — 用 jsdelivr CDN
    // @main 是延迟缓存, 这里加 ?t=Date.now() 强制 bust
    return 'https://cdn.jsdelivr.net/gh/622duan/nhk-easy-daily@main/data/nhk-app-format.json?t=' + Date.now();
  })();

  // GitHub API 用来拿最新 commit sha (避免 jsdelivr 缓存 @main 的旧版)
  // 因为 jsdelivr 对 @main 的缓存最长 12h, 我们每天都需要新鲜数据
  // 注: API rate limit 5000/hr 是 unauthenticated, 足够用
  const GH_API_URL = 'https://api.github.com/repos/622duan/nhk-easy-daily/commits?per_page=1';
  const GH_SHA_CACHE_KEY = 'nhk_daily_sha_cache';
  const GH_SHA_TTL = 30 * 60 * 1000; // 30 分钟

  async function getLatestSha() {
    // 1. 先用 localStorage cache
    try {
      const cached = localStorage.getItem(GH_SHA_CACHE_KEY);
      if (cached) {
        const obj = JSON.parse(cached);
        if (Date.now() - obj.cached_at < GH_SHA_TTL) {
          return obj.sha;
        }
      }
    } catch (e) {}

    // 2. fetch GitHub API
    try {
      const r = await fetch(GH_API_URL);
      if (r.ok) {
        const commits = await r.json();
        if (Array.isArray(commits) && commits[0] && commits[0].sha) {
          const sha = commits[0].sha.substring(0, 12);
          try {
            localStorage.setItem(GH_SHA_CACHE_KEY, JSON.stringify({
              cached_at: Date.now(),
              sha: sha
            }));
          } catch (e) {}
          return sha;
        }
      }
    } catch (e) {}

    return null;
  }

  /**
   * 拿最终 fetch URL (优先用 SHA, 失败用 @main)
   */
  async function resolveFetchUrl() {
    const sha = await getLatestSha();
    if (sha) {
      // 用 SHA 而不是 @main, 避免 jsdelivr 缓存
      return `https://cdn.jsdelivr.net/gh/622duan/nhk-easy-daily@${sha}/data/nhk-app-format.json?t=${Date.now()}`;
    }
    return NHK_DAILY_URL;
  }

  const CACHE_KEY = 'nhk_daily_cache_v2';  // v2: 修复 cache 失效问题
  const CACHE_TTL = 5 * 60 * 1000;        // 5 分钟 (NHK 每天 8 点更新, 没必要 24h 缓存)

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
   * 按每条 item.badge 分组, 合并到对应 level.newsList 前面
   */
  function mergeIntoJPData(items, defaultLevel) {
    if (!window.JP_DATA) {
      console.warn('[NHK daily] JP_DATA not loaded yet, skip');
      return false;
    }

    // 标记每条
    items.forEach(item => {
      item.is_nhk_daily = true;
      item.fetched_at_marker = 'daily';
    });

    // 按 level 分组
    const byLevel = {};
    items.forEach(item => {
      const lv = item.badge || defaultLevel || 'N3';
      if (!byLevel[lv]) byLevel[lv] = [];
      byLevel[lv].push(item);
    });

    // 合并到各 level
    let totalMerged = 0;
    Object.keys(byLevel).forEach(lv => {
      if (!window.JP_DATA[lv]) {
        console.warn('[NHK daily] level not found:', lv);
        return;
      }
      if (!Array.isArray(window.JP_DATA[lv].newsList)) {
        window.JP_DATA[lv].newsList = [];
      }
      // 新内容放最前
      window.JP_DATA[lv].newsList = byLevel[lv].concat(window.JP_DATA[lv].newsList);
      totalMerged += byLevel[lv].length;
    });

    console.log('[NHK daily] merged to levels:', Object.keys(byLevel).map(lv => `${lv}=${byLevel[lv].length}`).join(', '));

    // 触发事件, 通知 UI 重新渲染
    window.dispatchEvent(new CustomEvent('nhk-daily-loaded', {
      detail: { byLevel: byLevel, totalCount: totalMerged }
    }));

    return true;
  }

  /**
   * 显示今日 NHK 速递横幅 (UI 集成)
   * 在 N3 等级 news-list 顶部插入一条横幅
   */
  function showDailyBanner(items) {
    // 找 news-list 页面的 list 容器
    const listContainer = document.getElementById('newsListContainer');
    if (!listContainer) {
      console.log('[NHK daily] list container not found, skip banner');
      return;
    }
    // 检查是否已存在 (避免重复)
    if (document.querySelector('.nhk-daily-banner')) return;

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
      if (items[0]) {
        location.href = `news-detail.html?id=${items[0].id}`;
      }
    };

    // 插到 list 容器最前
    listContainer.parentNode.insertBefore(banner, listContainer);
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
      // 优先用 SHA URL (避免 jsdelivr @main 缓存)
      const url = await resolveFetchUrl();
      const resp = await fetch(url, { cache: 'no-cache' });
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
        console.log('[NHK daily] loaded fresh:', data.items.length, 'items', url.includes('@main') ? '(main)' : '(sha)');
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
