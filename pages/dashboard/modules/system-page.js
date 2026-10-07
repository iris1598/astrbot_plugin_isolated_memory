/**
 * System Page - 系统概览与管理页面
 * 负责展示数据统计、重要度分布、活跃用户列表、备份管理、以及一键升级所有用户记忆
 */

import { esc, typeLabel, showConfirm } from "./utils.js";

export class SystemPage {
  constructor(state, apiClient) {
    this.state = state;
    this.api = apiClient;

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
    // 立即创建备份
    document.getElementById("btn-create-backup")?.addEventListener("click", () => {
      this.handleCreateBackup();
    });

    // 一键升级所有用户记忆
    document.getElementById("cons-run-btn")?.addEventListener("click", () => {
      this.handleRunUpgrade();
    });
  }

  async fetch() {
    try {
      const data = await this.api.get("stats");
      this.render(data);
    } catch (e) {
      this.showToast(e.message || "获取系统概览失败", true);
    }
  }

  render(data) {
    this.renderStatCards(data);
    this.renderImportanceChart(data.importance_distribution || {});
    this.renderAtomChart(data.atom_breakdown || {});
    this.renderSessionList(data.recent_sessions || []);
    this.fetchAndRenderBackups();
    this.fetchConsolidation();
  }

  renderStatCards(data) {
    const totalEl = document.getElementById("ss-total");
    const activeEl = document.getElementById("ss-active");
    const sessionsEl = document.getElementById("ss-sessions");
    const avgImpEl = document.getElementById("ss-avg-imp");

    if (totalEl) totalEl.textContent = data.total_memories || 0;
    if (activeEl) activeEl.textContent = (data.status_breakdown && data.status_breakdown.active) || data.total_memories || 0;
    if (sessionsEl) sessionsEl.textContent = data.total_sessions || (data.recent_sessions && data.recent_sessions.length) || 0;
    if (avgImpEl) avgImpEl.textContent = data.avg_importance != null ? data.avg_importance : "0.60";
  }

  renderImportanceChart(distribution) {
    const chartEl = document.getElementById("importance-chart");
    if (!chartEl) return;

    const bins = ["0-1", "1-2", "2-3", "3-4", "4-5", "5-6", "6-7", "7-8", "8-9", "9-10"];
    const values = bins.map((bin) => distribution[bin] || 0);
    const maxValue = Math.max(...values, 1);

    let html = "";
    bins.forEach((bin, idx) => {
      const value = values[idx];
      const percentage = ((value / maxValue) * 100).toFixed(0);
      html += '<div class="bar-row">';
      html += '<span class="bar-row-label">' + bin + '</span>';
      html += '<div class="bar-row-track">';
      html += '<div class="bar-row-fill" style="width:' + percentage + '%"></div>';
      html += '</div>';
      html += '<span class="bar-row-value">' + value + '</span>';
      html += '</div>';
    });

    chartEl.innerHTML = html;
  }

  renderAtomChart(types) {
    const chartEl = document.getElementById("atom-chart");
    if (!chartEl) return;

    const entries = Object.entries(types || {});
    if (entries.length === 0) {
      chartEl.innerHTML = '<div class="bar-chart-empty">暂无类型分布数据</div>';
      return;
    }

    const maxValue = Math.max(...entries.map(([_, count]) => count), 1);
    let html = "";
    entries.forEach(([type, count]) => {
      const percentage = ((count / maxValue) * 100).toFixed(0);
      html += '<div class="bar-row">';
      html += '<span class="bar-row-label" style="width:90px">' + esc(typeLabel(type)) + '</span>';
      html += '<div class="bar-row-track">';
      html += '<div class="bar-row-fill" style="width:' + percentage + '%"></div>';
      html += '</div>';
      html += '<span class="bar-row-value">' + count + '</span>';
      html += '</div>';
    });

    chartEl.innerHTML = html;
  }

  renderSessionList(sessions) {
    const listEl = document.getElementById("session-list");
    if (!listEl) return;

    if (!sessions || sessions.length === 0) {
      listEl.innerHTML = '<div class="session-empty">暂无活跃用户数据</div>';
      return;
    }

    let html = "";
    sessions.forEach((s) => {
      const sessionId = s.session_id || "--";
      const count = s.message_count || 0;

      html += '<div class="session-item" style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-bottom:1px solid var(--border-color,#eee)">';
      html += '<div>';
      html += '<span style="font-weight:600;font-size:14px;color:var(--text-primary,#111)">' + esc(sessionId) + '</span>';
      html += '<span style="font-size:12px;color:var(--text-secondary,#666);margin-left:8px">' + count + ' 条记忆</span>';
      html += '</div>';
      html += '<button class="btn btn-sm btn-ghost view-user-memories-btn" data-owner="' + esc(sessionId) + '" style="font-size:12px">查看此用户</button>';
      html += '</div>';
    });

    listEl.innerHTML = html;

    listEl.querySelectorAll(".view-user-memories-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const owner = e.target.dataset.owner;
        if (owner && window._memoryPageInstance) {
          // 切换到记忆管理标签并过滤
          const navBtn = document.querySelector('.nav-item[data-page="memory"]');
          if (navBtn) navBtn.click();
          window._memoryPageInstance.setSessionFilter(owner);
        }
      });
    });
  }

  async fetchAndRenderBackups() {
    try {
      const data = await this.api.get("backups");
      this.renderBackupList(data.backups || []);
    } catch (e) {
      const listEl = document.getElementById("backup-list");
      if (listEl) listEl.innerHTML = '<div class="backup-empty">获取备份列表失败</div>';
    }
  }

  renderBackupList(backups) {
    const listEl = document.getElementById("backup-list");
    if (!listEl) return;

    if (!backups || backups.length === 0) {
      listEl.innerHTML = '<div class="backup-empty">暂无备份文件</div>';
      return;
    }

    let html = "";
    backups.forEach((b) => {
      const filename = b.filename || b.name || "--";
      const timeStr = b.created_at || b.timestamp || "--";
      const totalMem = b.total_memories != null ? b.total_memories : "--";
      const totalUsers = b.total_users != null ? b.total_users : "--";
      const sizeStr = b.size_bytes ? `${(b.size_bytes / 1024).toFixed(1)} KB` : "";

      html += '<div class="backup-item" style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border:1px solid var(--border-color,#eee);border-radius:6px;margin-bottom:8px">';
      html += '<div>';
      html += '<div style="font-weight:600;font-size:13px;font-family:monospace">' + esc(filename) + '</div>';
      html += '<div style="font-size:12px;color:var(--text-tertiary,#888);margin-top:2px">';
      html += '<span>' + esc(timeStr) + '</span>';
      html += '<span style="margin-left:12px">记忆: ' + totalMem + ' 条</span>';
      html += '<span style="margin-left:12px">用户: ' + totalUsers + ' 位</span>';
      if (sizeStr) html += '<span style="margin-left:12px">大小: ' + sizeStr + '</span>';
      html += '</div></div>';

      html += '<div style="display:flex;gap:6px">';
      html += '<button class="btn btn-sm btn-secondary restore-backup-btn" data-filename="' + esc(filename) + '"><i data-lucide="rotate-ccw" aria-hidden="true"></i><span>恢复</span></button>';
      html += '<button class="btn btn-sm btn-danger delete-backup-btn" data-filename="' + esc(filename) + '"><i data-lucide="trash-2" aria-hidden="true"></i></button>';
      html += '</div></div>';
    });

    listEl.innerHTML = html;
    if (window.lucide && typeof window.lucide.createIcons === "function") {
      window.lucide.createIcons();
    }

    listEl.querySelectorAll(".restore-backup-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const fn = e.currentTarget.dataset.filename;
        this.handleRestoreBackup(fn);
      });
    });

    listEl.querySelectorAll(".delete-backup-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const fn = e.currentTarget.dataset.filename;
        this.handleDeleteBackup(fn);
      });
    });
  }

  async handleCreateBackup() {
    const btn = document.getElementById("btn-create-backup");
    if (btn) btn.disabled = true;

    try {
      const res = await this.api.post("backups/create", {});
      this.showToast(`备份成功！共备份 ${res.total_memories || 0} 条记忆`);
      this.fetchAndRenderBackups();
    } catch (e) {
      this.showToast(e.message || "创建备份失败", true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async handleRestoreBackup(filename) {
    const ok = await showConfirm(
      "恢复备份确认",
      `确定要从备份「${filename}」恢复记忆吗？\n当前知识库中的记忆将被覆盖！系统会自动先创建安全快照。`,
      { isDanger: true, confirmText: "恢复" }
    );
    if (!ok) return;

    try {
      const res = await this.api.post("backups/restore", { filename });
      this.showToast(`恢复成功！已恢复 ${res.restored_count || 0} 条记忆`);
      this.fetch();
      if (window._memoryPageInstance) {
        window._memoryPageInstance.fetch();
      }
    } catch (e) {
      this.showToast(e.message || "恢复备份失败", true);
    }
  }

  async handleDeleteBackup(filename) {
    const ok = await showConfirm(
      "删除备份确认",
      `确定要删除备份文件「${filename}」吗？该操作不可恢复！`,
      { isDanger: true, confirmText: "删除" }
    );
    if (!ok) return;

    try {
      await this.api.post("backups/delete", { filename });
      this.showToast("删除备份成功");
      this.fetchAndRenderBackups();
    } catch (e) {
      this.showToast(e.message || "删除备份失败", true);
    }
  }

  async fetchConsolidation() {
    try {
      const data = await this.api.get("consolidation/status");
      const metaEl = document.getElementById("consolidation-meta");
      if (metaEl) {
        let html = '<div style="font-size:13px;line-height:1.8;color:var(--text-secondary,#555)">';
        html += `<div>• 记忆半衰期: <strong>${data.half_life_days || 30} 天</strong> | 最大保留 (TTL): <strong>${data.ttl_days || 90} 天</strong></div>`;
        html += `<div>• 单用户记忆上限: <strong>${data.max_docs || 200} 条</strong> | 去重相似度阈值: <strong>${data.dup_threshold || 0.9}</strong></div>`;
        html += `<div>• 保护高重要度记忆: <strong>${data.protect_important ? "已启用" : "未启用"}</strong> | 遗忘前巩固: <strong>${data.consolidate_enabled ? "已启用" : "未启用"}</strong></div>`;
        html += `<div>• Rerank 重排优化: <strong>${data.rerank_enabled ? `已启用 (${data.rerank_provider_id || "未指定模型"})` : "未启用"}</strong></div>`;
        html += '</div>';
        metaEl.innerHTML = html;
      }
    } catch (_) {}
  }

  async handleRunUpgrade() {
    const btn = document.getElementById("cons-run-btn");
    const resultEl = document.getElementById("cons-run-result");
    if (btn) btn.disabled = true;
    if (resultEl) resultEl.textContent = "正在执行升级…";

    try {
      const res = await this.api.post("upgrade/run", {});
      const summary = `升级完成：检查 ${res.owners_checked || 0} 个用户，成功升级 ${res.memories_upgraded || 0} 条记忆`;
      if (resultEl) resultEl.textContent = summary;
      this.showToast(summary);
      this.fetch();
      if (window._memoryPageInstance) {
        window._memoryPageInstance.fetch();
      }
    } catch (e) {
      if (resultEl) resultEl.textContent = e.message || "升级失败";
      this.showToast(e.message || "升级失败", true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }
}
