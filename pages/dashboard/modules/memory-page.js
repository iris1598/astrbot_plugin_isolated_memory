/**
 * Memory Page - 记忆管理页面
 * 负责记忆列表展示、筛选过滤、排序分页、批量操作以及导入导出
 */

import { normalizeImportance, esc, statusPill, typeLabel, showConfirm } from "./utils.js";

export class MemoryPage {
  constructor(state, apiClient, peekPanel) {
    this.state = state;
    this.api = apiClient;
    this.peek = peekPanel;
    window._memoryPageInstance = this;

    if (!(this.state.memory.selectedIds instanceof Set)) {
      this.state.memory.selectedIds = new Set();
    }
    this._fetchGeneration = 0;

    this.initEventListeners();
  }

  showToast(msg, isError = false) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("visible", "error");
    if (isError) el.classList.add("error");
    void el.offsetWidth;
    el.classList.add("visible");
    clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      el.classList.remove("visible");
    }, 2500);
  }

  initEventListeners() {
    // 刷新按钮
    document.getElementById("mem-refresh")?.addEventListener("click", () => this.fetch());

    // 筛选表单
    const filterForm = document.getElementById("memory-filters");
    if (filterForm) {
      filterForm.addEventListener("submit", (e) => {
        e.preventDefault();
        this.applyFilters();
      });
    }

    // 重置筛选
    document.getElementById("mem-reset-filters")?.addEventListener("click", () => {
      document.getElementById("mem-keyword").value = "";
      document.getElementById("mem-session").value = "";
      document.getElementById("mem-type").value = "all";
      document.getElementById("mem-sort").value = "created_desc";
      this.applyFilters();
    });

    // 分页控制
    document.getElementById("mem-prev")?.addEventListener("click", () => {
      if (this.state.memory.page > 1) {
        this.state.memory.page--;
        this.fetch();
      }
    });

    document.getElementById("mem-next")?.addEventListener("click", () => {
      const maxPage = Math.ceil(this.state.memory.total / this.state.memory.pageSize);
      if (this.state.memory.page < maxPage) {
        this.state.memory.page++;
        this.fetch();
      }
    });

    document.getElementById("mem-page-size")?.addEventListener("change", (e) => {
      this.state.memory.pageSize = parseInt(e.target.value) || 20;
      this.state.memory.page = 1;
      this.fetch();
    });

    // 全选
    document.getElementById("mem-select-all")?.addEventListener("change", (e) => {
      const checked = e.target.checked;
      document.querySelectorAll(".cell-select-cb").forEach((cb) => {
        cb.checked = checked;
        const id = cb.dataset.id;
        if (checked) this.state.memory.selectedIds.add(id);
        else this.state.memory.selectedIds.delete(id);
      });
      this.updateSelectionBar();
    });

    // 清除选择
    document.getElementById("mem-clear-selection")?.addEventListener("click", () => {
      this.state.memory.selectedIds.clear();
      const selectAll = document.getElementById("mem-select-all");
      if (selectAll) selectAll.checked = false;
      document.querySelectorAll(".cell-select-cb").forEach((cb) => (cb.checked = false));
      this.updateSelectionBar();
    });

    // 批量删除
    document.getElementById("mem-delete-selected")?.addEventListener("click", () => {
      this.handleBatchDelete();
    });

    // 导出
    document.getElementById("mem-export")?.addEventListener("click", () => {
      this.handleExport();
    });

    // 导入触发
    document.getElementById("mem-import")?.addEventListener("click", () => {
      document.getElementById("mem-import-file")?.click();
    });

    document.getElementById("mem-import-file")?.addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (file) {
        this.handleImportFile(file);
        e.target.value = "";
      }
    });
  }

  applyFilters() {
    this.state.memory.keyword = document.getElementById("mem-keyword")?.value.trim() || "";
    this.state.memory.session = document.getElementById("mem-session")?.value.trim() || "";
    this.state.memory.type = document.getElementById("mem-type")?.value || "all";
    this.state.memory.sort = document.getElementById("mem-sort")?.value || "created_desc";
    this.state.memory.page = 1;
    this.fetch();
  }

  setSessionFilter(sessionId) {
    const input = document.getElementById("mem-session");
    if (input) input.value = sessionId;
    this.applyFilters();
  }

  async fetch() {
    const fetchGeneration = ++this._fetchGeneration;
    this.state.memory.loading = true;
    this.updateFeedback();

    const params = {
      page: String(this.state.memory.page),
      page_size: String(this.state.memory.pageSize),
    };
    if (this.state.memory.session) params.session_id = this.state.memory.session;
    if (this.state.memory.keyword) params.keyword = this.state.memory.keyword;
    if (this.state.memory.type && this.state.memory.type !== "all") {
      params.type = this.state.memory.type;
    }
    if (this.state.memory.sort) params.sort = this.state.memory.sort;

    try {
      const data = await this.api.get("memories", params);
      if (fetchGeneration !== this._fetchGeneration) return;

      const total = data.total || 0;
      const totalPages = Math.max(1, Math.ceil(total / this.state.memory.pageSize));
      if (this.state.memory.page > totalPages && total > 0) {
        this.state.memory.page = totalPages;
        return this.fetch();
      }

      this.state.memory.total = total;
      this.state.memory.items = Array.isArray(data.items) ? data.items : [];
      this.state.memory.selectedIds.clear();

      this.renderTable();
      this.updatePagination();
      this.updateSelectionBar();
    } catch (e) {
      if (fetchGeneration !== this._fetchGeneration) return;
      this.showToast(e.message || "获取记忆失败", true);
    } finally {
      if (fetchGeneration === this._fetchGeneration) {
        this.state.memory.loading = false;
        this.updateFeedback();
      }
    }
  }

  updateFeedback() {
    const feedback = document.getElementById("memory-feedback");
    const msg = document.getElementById("memory-feedback-message");
    if (!feedback) return;
    if (this.state.memory.loading) {
      feedback.hidden = false;
      if (msg) msg.textContent = window.t ? window.t("common.loading") : "加载中…";
    } else {
      feedback.hidden = true;
    }
  }

  renderTable() {
    const tbody = document.getElementById("memories-body");
    if (!tbody) return;

    const items = this.state.memory.items;
    if (!items || items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="table-empty">' + (window.t ? window.t("common.noData") : "暂无数据") + '</td></tr>';
      return;
    }

    let html = "";
    items.forEach((item) => {
      const id = item.doc_id || item.id || "--";
      const md = item.metadata || {};
      const owner = md.memory_owner || md.user_id || "--";
      const summary = item.summary || item.text || "--";
      const type = String(md.type || "factual").toLowerCase();
      const imp = Number(md.importance || 0.6).toFixed(2);
      const created = item.created_at || "--";

      html += '<tr class="memory-row" data-id="' + esc(id) + '">';
      html += '<td class="cell-select"><input type="checkbox" class="cell-select-cb" data-id="' + esc(id) + '" /></td>';
      html += '<td class="cell-id" style="font-family:monospace;font-size:11px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(id) + '">' + esc(id) + '</td>';
      html += '<td class="cell-owner" style="font-weight:600;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + esc(owner) + '"><span class="owner-filter-link" data-owner="' + esc(owner) + '" style="cursor:pointer;color:var(--color-primary, #6366f1)">' + esc(owner) + '</span></td>';
      html += '<td class="cell-summary" style="cursor:pointer" title="' + esc(item.text || summary) + '">' + esc(summary) + '</td>';
      html += '<td class="cell-type"><span class="type-tag">' + esc(typeLabel(type)) + '</span></td>';
      html += '<td class="cell-importance" style="font-family:monospace">' + imp + '</td>';
      html += '<td class="cell-created" style="font-size:12px;color:var(--text-tertiary, #888);white-space:nowrap">' + esc(created) + '</td>';
      html += '</tr>';
    });

    tbody.innerHTML = html;

    // 行点击打开详情
    tbody.querySelectorAll(".cell-summary").forEach((cell) => {
      cell.addEventListener("click", (e) => {
        const row = e.target.closest(".memory-row");
        const id = row?.dataset.id;
        const item = items.find((it) => (it.doc_id || it.id) === id);
        if (item) this.peek.renderMemory(item);
      });
    });

    // 点击归属用户快速筛选
    tbody.querySelectorAll(".owner-filter-link").forEach((link) => {
      link.addEventListener("click", (e) => {
        e.stopPropagation();
        const owner = e.target.dataset.owner;
        if (owner && owner !== "--") {
          this.setSessionFilter(owner);
        }
      });
    });

    // 行勾选事件
    tbody.querySelectorAll(".cell-select-cb").forEach((cb) => {
      cb.addEventListener("change", (e) => {
        const id = e.target.dataset.id;
        if (e.target.checked) this.state.memory.selectedIds.add(id);
        else this.state.memory.selectedIds.delete(id);
        this.updateSelectionBar();
      });
    });
  }

  updateSelectionBar() {
    const bar = document.getElementById("memory-selection");
    const countEl = document.getElementById("mem-selection-count");
    const delBtn = document.getElementById("mem-delete-selected");
    const count = this.state.memory.selectedIds.size;

    if (!bar) return;
    if (count > 0) {
      bar.hidden = false;
      if (countEl) countEl.textContent = `已选择 ${count} 条记忆`;
      if (delBtn) delBtn.disabled = false;
    } else {
      bar.hidden = true;
      if (delBtn) delBtn.disabled = true;
    }
  }

  updatePagination() {
    const { page, pageSize, total } = this.state.memory;
    const maxPage = Math.max(1, Math.ceil(total / pageSize));

    const prevBtn = document.getElementById("mem-prev");
    const nextBtn = document.getElementById("mem-next");
    const infoEl = document.getElementById("mem-pagination-info");

    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = page >= maxPage;
    if (infoEl) infoEl.textContent = `第 ${page} / ${maxPage} 页 · 共 ${total} 条`;
  }

  async handleBatchDelete() {
    const count = this.state.memory.selectedIds.size;
    if (!count) return;

    const ok = await showConfirm(
      "批量删除确认",
      `确定要批量删除选中的 ${count} 条记忆吗？该操作不可恢复！`,
      { isDanger: true, confirmText: "删除" }
    );
    if (!ok) return;

    try {
      const ids = Array.from(this.state.memory.selectedIds);
      const res = await this.api.post("memories/batch-delete", { memory_ids: ids });
      this.showToast(`成功删除 ${res.deleted_count || count} 条记忆`);
      this.state.memory.selectedIds.clear();
      this.fetch();
    } catch (e) {
      this.showToast(e.message || "批量删除失败", true);
    }
  }

  async handleExport() {
    try {
      const ids = Array.from(this.state.memory.selectedIds);
      const res = await this.api.post("memories/export", { memory_ids: ids });
      const memories = res.memories || [];
      const format = document.getElementById("mem-transfer-format")?.value || "json";

      let blob;
      let filename;
      const dateStr = new Date().toISOString().slice(0, 10);

      if (format === "csv") {
        const header = ["id", "owner", "content", "type", "importance", "created_at"];
        const rows = memories.map((m) => [
          m.id,
          m.owner,
          `"${String(m.content || "").replace(/"/g, '""')}"`,
          m.type,
          m.importance,
          m.created_at,
        ]);
        const csvContent = [header.join(","), ...rows.map((r) => r.join(","))].join("\n");
        blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
        filename = `isolated_memories_${dateStr}.csv`;
      } else {
        const jsonStr = JSON.stringify(memories, null, 2);
        blob = new Blob([jsonStr], { type: "application/json;charset=utf-8;" });
        filename = `isolated_memories_${dateStr}.json`;
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      this.showToast(`已成功导出 ${memories.length} 条记忆`);
    } catch (e) {
      this.showToast(e.message || "导出失败", true);
    }
  }

  async handleImportFile(file) {
    try {
      const text = await file.text();
      let items = [];

      if (file.name.endsWith(".json")) {
        const parsed = JSON.parse(text);
        items = Array.isArray(parsed) ? parsed : (parsed.memories || []);
      } else if (file.name.endsWith(".csv")) {
        const lines = text.split(/\r?\n/).filter(Boolean);
        if (lines.length > 1) {
          const header = lines[0].split(",").map((h) => h.trim().toLowerCase());
          const ownerIdx = header.indexOf("owner");
          const contentIdx = header.indexOf("content");
          const typeIdx = header.indexOf("type");
          const impIdx = header.indexOf("importance");

          for (let i = 1; i < lines.length; i++) {
            const parts = lines[i].split(",");
            if (parts.length >= 2) {
              items.push({
                owner: parts[ownerIdx >= 0 ? ownerIdx : 1] || "default_user",
                content: parts[contentIdx >= 0 ? contentIdx : 2] || parts[0],
                type: parts[typeIdx >= 0 ? typeIdx : 3] || "factual",
                importance: parts[impIdx >= 0 ? impIdx : 4] || 0.6,
              });
            }
          }
        }
      }

      if (!items.length) {
        this.showToast("文件未包含可解析的记忆数据", true);
        return;
      }

      const ok = await showConfirm(
        "导入记忆确认",
        `解析到 ${items.length} 条记忆，确定要导入吗？`,
        { isDanger: false, confirmText: "导入" }
      );
      if (!ok) return;

      const res = await this.api.post("memories/import", { items });
      this.showToast(`导入完成：成功 ${res.imported_count || 0} 条，跳过 ${res.skipped_count || 0} 条`);
      this.fetch();
    } catch (e) {
      this.showToast(e.message || "文件解析或导入失败", true);
    }
  }
}
