/* global localStorage, URLSearchParams, CustomEvent */

(() => {
  const LANG_KEY = "im_lang";
  const SUPPORTED = ["zh", "en"];
  let urlLanguageOverride = false;

  const MSG = {
    /* ---- Common ---- */
    "common.close":       { zh: "关闭", en: "Close" },
    "common.cancel":      { zh: "取消", en: "Cancel" },
    "common.clear":       { zh: "清空", en: "Clear" },
    "common.save":        { zh: "保存", en: "Save" },
    "common.refresh":     { zh: "刷新", en: "Refresh" },
    "common.search":      { zh: "搜索", en: "Search" },
    "common.confirm":     { zh: "确定", en: "Confirm" },
    "common.loading":     { zh: "加载中...", en: "Loading..." },
    "common.retry":       { zh: "重试", en: "Retry" },
    "common.noData":      { zh: "暂无数据", en: "No data" },
    "common.unavailable": { zh: "暂不可用", en: "Unavailable" },
    "common.page":        { zh: "第 {0} / {1} 页 · 共 {2} 条", en: "Page {0}/{1} · {2} total" },
    "common.perPage":     { zh: "每页", en: "Per page" },
    "common.perPage20":   { zh: "20 条/页", en: "20 per page" },
    "common.perPage50":   { zh: "50 条/页", en: "50 per page" },
    "common.perPage100":  { zh: "100 条/页", en: "100 per page" },
    "common.enabled":     { zh: "已启用", en: "Enabled" },
    "common.disabled":    { zh: "未启用", en: "Disabled" },

    /* ---- Title / Header ---- */
    "page.title":         { zh: "IsolatedMemory 管理后台", en: "IsolatedMemory Console" },
    "header.title":       { zh: "IsolatedMemory 记忆控制台", en: "IsolatedMemory Dashboard" },
    "header.subtitle":    { zh: "长期记忆管理 · 基于时间衰减与官方会话隔离的智能记忆系统", en: "Long-term memory management · Time-decay & Session Isolation" },
    "header.lang":        { zh: "语言", en: "Language" },
    "header.theme":       { zh: "外观与主题", en: "Appearance" },

    /* ---- Navigation ---- */
    "nav.memory":         { zh: "记忆管理", en: "Memories" },
    "nav.recall":         { zh: "检索测试", en: "Recall Test" },
    "nav.system":         { zh: "系统概览", en: "System Overview" },
    "nav.affinity":       { zh: "好感与羁绊", en: "Affinity & Bonds" },

    /* ---- Status & Types ---- */
    "status.active":      { zh: "活跃", en: "Active" },
    "status.archived":    { zh: "已归档", en: "Archived" },
    "status.deleted":     { zh: "已删除", en: "Deleted" },
    "type.factual":       { zh: "事实 (Factual)", en: "Factual" },
    "type.preference":    { zh: "偏好 (Preference)", en: "Preference" },
    "type.episodic":      { zh: "事件 (Episodic)", en: "Episodic" },
    "type.planned":       { zh: "计划 (Planned)", en: "Planned" },
    "type.opinion":       { zh: "观点 (Opinion)", en: "Opinion" },
    "type.relational":    { zh: "关系 (Relational)", en: "Relational" },
    "type.general":       { zh: "通用 (General)", en: "General" },

    /* ---- Table & Filters ---- */
    "filter.keyword":     { zh: "按关键词或文档 ID 搜索…", en: "Search by keyword or doc ID…" },
    "filter.sessionId":   { zh: "用户 / 会话 UMO (如 12345)", en: "User / Session ID" },
    "filter.statusAll":   { zh: "全部状态", en: "All Status" },
    "filter.statusActive":{ zh: "活跃", en: "Active" },
    "filter.statusArchived":{ zh: "已归档", en: "Archived" },
    "filter.statusDeleted":{ zh: "已删除", en: "Deleted" },
    "filter.typeAll":     { zh: "全部类型", en: "All Types" },
    "filter.apply":       { zh: "筛选", en: "Filter" },
    "flow.resetFilters":  { zh: "重置筛选", en: "Reset" },
    "flow.transfer":      { zh: "导入与导出", en: "Import & Export" },
    "flow.exportAll":     { zh: "导出全部记忆，或勾选指定记忆进行导出。", en: "Export all or selected memories." },
    "flow.importSteps":   { zh: "选择 JSON 或 CSV 文件后确认导入。", en: "Choose a JSON/CSV file then confirm import." },
    "flow.clearSelection":{ zh: "取消选择", en: "Clear selection" },
    "flow.unsavedTitle":  { zh: "有未保存的修改", en: "Unsaved changes" },
    "flow.unsavedMessage":{ zh: "离开会丢失当前修改，确定放弃吗？", en: "Discard changes?" },
    "flow.keepEditing":   { zh: "继续编辑", en: "Keep editing" },
    "flow.discard":       { zh: "放弃修改", en: "Discard" },
    "flow.waitForSave":   { zh: "操作进行中，请稍候…", en: "Please wait…" },
    "sort.createdDesc":   { zh: "最新创建", en: "Newest first" },
    "sort.createdAsc":    { zh: "最早创建", en: "Oldest first" },
    "sort.updatedDesc":   { zh: "最近更新", en: "Recently updated" },
    "sort.importanceDesc":{ zh: "重要度从高到低", en: "Importance high-to-low" },
    "sort.importanceAsc": { zh: "重要度从低到高", en: "Importance low-to-high" },

    /* ---- Detail & Peek ---- */
    "detail.memoryTitle": { zh: "记忆 #{0}", en: "Memory #{0}" },
    "detail.content":     { zh: "记忆内容", en: "Content" },
    "detail.editBtn":     { zh: "编辑", en: "Edit" },
    "detail.deleteBtn":   { zh: "删除", en: "Delete" },

    /* ---- Recall Test ---- */
    "recall.queryPh":     { zh: "输入查询语句以测试检索效果…", en: "Enter a test query…" },
    "recall.sessionPh":   { zh: "指定用户 / 会话 UMO (可选)", en: "User / Session ID (optional)" },
    "recall.kLabel":      { zh: "召回数量 (k)", en: "Results (k)" },
    "recall.searchBtn":   { zh: "执行检索", en: "Run Recall" },
    "recall.searching":   { zh: "正在执行混合检索与打分…", en: "Running recall test…" },

    /* ---- Stats & System ---- */
    "stats.total":        { zh: "记忆总数", en: "Total Memories" },
    "stats.active":       { zh: "活跃记忆", en: "Active" },
    "stats.archived":     { zh: "已归档", en: "Archived" },
    "stats.deleted":      { zh: "已删除", en: "Deleted" },
    "stats.sessions":     { zh: "用户/会话数", en: "Users / Sessions" },
    "system.importanceDistribution": { zh: "重要度分布 (0-10)", en: "Importance Distribution" },
    "system.factTypes":   { zh: "事实类型分布", en: "Fact Type Breakdown" },
    "system.activeSessions": { zh: "活跃用户 / 会话列表", en: "Active Users / Sessions" },
    "system.consolidationTitle": { zh: "记忆衰减与一键升级", en: "Memory Decay & Upgrade" },
    "system.consolidationRun": { zh: "一键升级全部记忆", en: "Upgrade All Memories" },
    "system.versionBackups": { zh: "版本备份管理", en: "Memory Backups" },
  };

  function getSavedLanguage() {
    try {
      const p = new URLSearchParams(window.location.search);
      const urlLang = p.get("lang");
      if (urlLang && SUPPORTED.includes(urlLang)) {
        urlLanguageOverride = true;
        return urlLang;
      }
    } catch (_) {}

    try {
      const saved = localStorage.getItem(LANG_KEY);
      if (saved && SUPPORTED.includes(saved)) return saved;
    } catch (_) {}

    const nav = (navigator.language || "").toLowerCase();
    if (nav.startsWith("zh")) return "zh";
    return "en";
  }

  let currentLang = getSavedLanguage();

  function t(key, ...args) {
    const entry = MSG[key];
    let str = (entry && (entry[currentLang] || entry["zh"])) || key;
    if (args.length) {
      args.forEach((val, idx) => {
        str = str.replace(new RegExp(`\\{${idx}\\}`, "g"), val);
      });
    }
    return str;
  }

  function setLanguage(lang) {
    if (!SUPPORTED.includes(lang)) return;
    currentLang = lang;
    try {
      if (!urlLanguageOverride) localStorage.setItem(LANG_KEY, lang);
    } catch (_) {}
    document.documentElement.lang = lang;
    applyTranslations();
    window.dispatchEvent(new CustomEvent("languagechange", { detail: { lang } }));
  }

  function applyTranslations() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.dataset.i18n;
      if (key) el.textContent = t(key);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.dataset.i18nPlaceholder;
      if (key) el.placeholder = t(key);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.dataset.i18nTitle;
      if (key) el.title = t(key);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      const key = el.dataset.i18nAria;
      if (key) el.setAttribute("aria-label", t(key));
    });

    const langLabel = document.getElementById("lang-label");
    if (langLabel) {
      langLabel.textContent = currentLang === "zh" ? "中文" : "English";
    }
  }

  window.t = t;
  window.setLanguage = setLanguage;
  window.getLanguage = () => currentLang;

  document.addEventListener("DOMContentLoaded", () => {
    applyTranslations();
    document.querySelectorAll(".lang-option[data-lang]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setLanguage(btn.dataset.lang);
        const menu = document.getElementById("lang-menu");
        if (menu) menu.open = false;
      });
    });
  });
})();
