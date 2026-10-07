/**
 * IsolatedMemory Dashboard - 主入口应用脚本
 */

import {
  ApiClient,
  PeekPanel,
  MemoryPage,
  RecallPage,
  SystemPage,
} from "./modules/index.js";

(() => {
  "use strict";

  const state = {
    page: "memory",
    memory: {
      items: [],
      total: 0,
      page: 1,
      pageSize: 20,
      hasMore: false,
      keyword: "",
      session: "",
      type: "all",
      sort: "created_desc",
      selectedIds: new Set(),
      loading: false,
    },
    selectedMemory: null,
    isEditing: false,
    _detailCache: null,
  };

  const api = new ApiClient();
  const peekPanel = new PeekPanel(state, api);
  const memoryPage = new MemoryPage(state, api, peekPanel);
  const recallPage = new RecallPage(state, api, peekPanel);
  const systemPage = new SystemPage(state, api);

  function hydrateIcons() {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons({
        attrs: {
          "stroke-width": 1.7,
          "aria-hidden": "true",
        },
      });
    }
  }

  function showToast(msg, isError = false) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("visible", "error");
    if (isError) el.classList.add("error");
    void el.offsetWidth;
    el.classList.add("visible");
    setTimeout(() => {
      el.classList.remove("visible");
    }, 2500);
  }

  async function switchPage(name) {
    if (name === state.page) return;
    if (!(await peekPanel.requestClose())) return;

    state.page = name;

    document.querySelectorAll(".nav-item[data-page]").forEach((item) => {
      const active = item.dataset.page === name;
      item.classList.toggle("active", active);
      if (active) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    });

    document.querySelectorAll(".page").forEach((p) => {
      p.classList.toggle("active", p.id === "page-" + name);
    });

    if (name === "memory") memoryPage.fetch();
    else if (name === "system") systemPage.fetch();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    hydrateIcons();

    // 导航栏点击切换
    document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchPage(btn.dataset.page);
      });
    });

    // 主题切换对话框
    document.getElementById("theme-toggle")?.addEventListener("click", () => {
      const dlg = document.getElementById("appearance-dialog");
      if (dlg && typeof dlg.showModal === "function") {
        dlg.showModal();
      }
    });

    // 等待 Bridge 初始化并加载第一页数据
    try {
      await api.ready();
    } catch (_) {}

    memoryPage.fetch();
  });
})();
