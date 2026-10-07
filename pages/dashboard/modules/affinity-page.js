/**
 * AffinityPage - 好感度与自由羁绊管理模块
 * 提供好感度与关系列表查看、多维过滤、分页、编辑与重置功能
 */

import { esc, showConfirm } from "./utils.js";

function strHashHue(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash) % 360;
}

function formatTime(ts) {
  if (!ts) return "--";
  const d = new Date(ts * 1000);
  return (
    d.toLocaleDateString() +
    " " +
    d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
  );
}

export class AffinityPage {
  constructor(state, api) {
    this.state = state;
    this.api = api;
    this.items = [];
    this.total = 0;
    this.page = 1;
    this.pageSize = 20;
    this.keyword = "";
    this.groupKey = "";
    this.personaId = "";
    this.sort = "score_desc";
    this.loading = false;
    this.editingItem = null;

    this.init();
  }

  init() {
    const filterForm = document.getElementById("affinity-filters");
    if (filterForm) {
      filterForm.addEventListener("submit", (e) => {
        e.preventDefault();
        this.page = 1;
        this.keyword = (document.getElementById("aff-keyword")?.value || "").trim();
        this.personaId = (document.getElementById("aff-persona")?.value || "").trim();
        this.groupKey = (document.getElementById("aff-group")?.value || "").trim();
        this.sort = document.getElementById("aff-sort")?.value || "score_desc";
        this.fetch();
      });
    }

    const resetBtn = document.getElementById("aff-reset-filters");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        const kw = document.getElementById("aff-keyword");
        const p = document.getElementById("aff-persona");
        const g = document.getElementById("aff-group");
        const s = document.getElementById("aff-sort");
        if (kw) kw.value = "";
        if (p) p.value = "";
        if (g) g.value = "";
        if (s) s.value = "score_desc";
        this.page = 1;
        this.keyword = "";
        this.personaId = "";
        this.groupKey = "";
        this.sort = "score_desc";
        this.fetch();
      });
    }

    const refreshBtn = document.getElementById("aff-refresh");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => {
        this.fetch();
      });
    }

    const prevBtn = document.getElementById("aff-prev-page");
    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (this.page > 1) {
          this.page--;
          this.fetch();
        }
      });
    }

    const nextBtn = document.getElementById("aff-next-page");
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        const maxPage = Math.ceil(this.total / this.pageSize) || 1;
        if (this.page < maxPage) {
          this.page++;
          this.fetch();
        }
      });
    }

    // 编辑弹窗绑定
    const editForm = document.getElementById("aff-edit-form");
    if (editForm) {
      editForm.addEventListener("submit", (e) => {
        e.preventDefault();
        this.saveEdit();
      });
    }

    const editDialog = document.getElementById("aff-edit-dialog");
    if (editDialog) {
      editDialog.addEventListener("click", (e) => {
        const rect = editDialog.getBoundingClientRect();
        const isInDialog =
          rect.top <= e.clientY &&
          e.clientY <= rect.top + rect.height &&
          rect.left <= e.clientX &&
          e.clientX <= rect.left + rect.width;
        if (!isInDialog) {
          this.closeEditDialog();
        }
      });
    }

    const editCancel = document.getElementById("aff-edit-cancel");
    if (editCancel) {
      editCancel.addEventListener("click", () => {
        this.closeEditDialog();
      });
    }
  }

  showToast(msg, isError = false) {
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

  async fetch() {
    if (this.loading) return;
    this.loading = true;

    try {
      const data = await this.api.get("affinity/list", {
        keyword: this.keyword,
        group_key: this.groupKey,
        persona_id: this.personaId,
        sort: this.sort,
        page: this.page,
        page_size: this.pageSize,
      });

      this.items = data.items || [];
      this.total = data.total || 0;

      // 更新下拉筛选选项（如未初始化）
      this.updateFilterOptions(data.personas || [], data.groups || []);

      this.render();
    } catch (err) {
      console.error("加载好感度列表失败:", err);
      this.showToast("加载好感度数据失败: " + err.message, true);
    } finally {
      this.loading = false;
    }
  }

  updateFilterOptions(personas, groups) {
    const pSelect = document.getElementById("aff-persona");
    if (pSelect && pSelect.children.length <= 1) {
      personas.forEach((pid) => {
        const opt = document.createElement("option");
        opt.value = pid;
        opt.textContent = pid === "default" ? "默认预设 (default)" : `人格：${pid}`;
        pSelect.appendChild(opt);
      });
      if (this.personaId) pSelect.value = this.personaId;
    }

    const gSelect = document.getElementById("aff-group");
    if (gSelect && gSelect.children.length <= 1) {
      groups.forEach((gid) => {
        const opt = document.createElement("option");
        opt.value = gid;
        opt.textContent = gid;
        gSelect.appendChild(opt);
      });
      if (this.groupKey) gSelect.value = this.groupKey;
    }
  }

  render() {
    // 渲染统计卡片
    const totalEl = document.getElementById("aff-stat-total");
    const avgEl = document.getElementById("aff-stat-avg");
    const maxEl = document.getElementById("aff-stat-max");
    const personasEl = document.getElementById("aff-stat-personas");

    if (totalEl) totalEl.textContent = this.total;
    if (this.items.length > 0) {
      const scores = this.items.map((i) => i.score);
      const sum = scores.reduce((a, b) => a + b, 0);
      if (avgEl) avgEl.textContent = Math.round(sum / this.items.length);
      if (maxEl) maxEl.textContent = Math.max(...scores);
    }

    const personas = new Set(this.items.map((i) => i.persona_id));
    if (personasEl) personasEl.textContent = personas.size;

    // 渲染表格
    const tbody = document.getElementById("affinity-list-body");
    const emptyEl = document.getElementById("aff-empty");
    if (!tbody) return;

    tbody.innerHTML = "";

    if (this.items.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
    } else {
      if (emptyEl) emptyEl.style.display = "none";

      this.items.forEach((item) => {
        const tr = document.createElement("tr");

        // 计算关系色彩 Hue
        const relHue = strHashHue(item.relation || "普通朋友");
        const relBadgeStyle = `background: hsl(${relHue}, 70%, 94%); color: hsl(${relHue}, 80%, 25%); border: 1px solid hsl(${relHue}, 60%, 82%); padding: 2px 8px; border-radius: 999px; font-weight: 500; font-size: 12px;`;

        // 好感数值色彩
        let scoreColor = "var(--text-primary)";
        if (item.score >= 1000) scoreColor = "#6366f1"; // 极高高亮紫色
        else if (item.score >= 100) scoreColor = "#10b981"; // 绿色
        else if (item.score < 0) scoreColor = "#ef4444"; // 红色

        // 心境胶囊
        const moodText = item.mood_state || "平常心";
        const moodReason = item.mood_reason ? ` (${esc(item.mood_reason)})` : "";
        const moodHtml =
          moodText !== "平常心"
            ? `<span style="background: rgba(245, 158, 11, 0.12); color: #d97706; padding: 2px 8px; border-radius: 999px; font-size: 12px;" title="${esc(item.mood_reason)}">${esc(moodText)}${moodReason}</span>`
            : `<span style="color: var(--text-muted); font-size: 12px;">平常心</span>`;

        tr.innerHTML = `
          <td>
            <div style="font-weight: 600;">${esc(item.user_name || item.user_id)}</div>
            <div style="font-size: 11px; color: var(--text-muted);">${esc(item.user_id)}</div>
          </td>
          <td>
            <span class="badge" style="background: var(--bg-hover); padding: 2px 6px; border-radius: 4px; font-size: 12px;">
              ${esc(item.persona_id === "default" ? "默认预设" : item.persona_id)}
            </span>
          </td>
          <td style="font-size: 12px; color: var(--text-muted); max-width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${esc(item.group_key)}">
            ${esc(item.group_key)}
          </td>
          <td style="font-weight: 700; font-size: 16px; color: ${scoreColor}; font-family: monospace;">
            ${item.score > 0 ? "+" : ""}${item.score}
          </td>
          <td>
            <span style="${relBadgeStyle}">${esc(item.relation)}</span>
          </td>
          <td>${moodHtml}</td>
          <td style="font-size: 12px; color: var(--text-secondary); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${esc(item.eval)}">
            ${esc(item.eval)}
          </td>
          <td style="font-size: 11px; color: var(--text-muted);">
            ${formatTime(item.updated_at)}
          </td>
          <td>
            <div style="display: flex; gap: 6px;">
              <button class="btn btn-secondary btn-xs btn-aff-edit" style="padding: 2px 6px; font-size: 11px;">编辑</button>
              <button class="btn btn-ghost btn-xs btn-aff-reset" style="padding: 2px 6px; font-size: 11px; color: var(--danger-text, #ef4444);">重置</button>
            </div>
          </td>
        `;

        tr.querySelector(".btn-aff-edit")?.addEventListener("click", () => {
          this.openEditDialog(item);
        });

        tr.querySelector(".btn-aff-reset")?.addEventListener("click", () => {
          this.handleReset(item);
        });

        tbody.appendChild(tr);
      });
    }

    // 分页更新
    const maxPage = Math.ceil(this.total / this.pageSize) || 1;
    const pageInfo = document.getElementById("aff-page-info");
    if (pageInfo) {
      pageInfo.textContent = `第 ${this.page} / ${maxPage} 页 · 共 ${this.total} 条`;
    }

    const prevBtn = document.getElementById("aff-prev-page");
    const nextBtn = document.getElementById("aff-next-page");
    if (prevBtn) prevBtn.disabled = this.page <= 1;
    if (nextBtn) nextBtn.disabled = this.page >= maxPage;
  }

  openEditDialog(item) {
    this.editingItem = item;
    const dialog = document.getElementById("aff-edit-dialog");
    const userEl = document.getElementById("aff-edit-user");
    const scoreEl = document.getElementById("aff-edit-score");
    const relEl = document.getElementById("aff-edit-relation");
    const evalEl = document.getElementById("aff-edit-eval");

    if (userEl) userEl.value = `${item.user_name || item.user_id} (${item.persona_id})`;
    if (scoreEl) scoreEl.value = item.score != null ? item.score : 0;
    if (relEl) relEl.value = item.relation || "普通朋友";
    if (evalEl) evalEl.value = item.eval || "";

    if (dialog) {
      if (typeof dialog.showModal === "function") {
        try {
          dialog.showModal();
        } catch (err) {
          console.warn("showModal failed, fallback to open attribute:", err);
          dialog.setAttribute("open", "");
        }
      } else {
        dialog.setAttribute("open", "");
      }
    }
  }

  closeEditDialog() {
    const dialog = document.getElementById("aff-edit-dialog");
    if (dialog) {
      if (typeof dialog.close === "function") {
        try {
          dialog.close();
        } catch (_) {
          dialog.removeAttribute("open");
        }
      } else {
        dialog.removeAttribute("open");
      }
    }
  }

  async saveEdit() {
    if (!this.editingItem) return;

    const saveBtn = document.getElementById("aff-edit-save");
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "保存中...";
    }

    const score = parseInt(document.getElementById("aff-edit-score")?.value || "0", 10);
    const relation = (document.getElementById("aff-edit-relation")?.value || "").trim();
    const evalText = (document.getElementById("aff-edit-eval")?.value || "").trim();

    try {
      await this.api.post("affinity/update", {
        group_key: this.editingItem.group_key,
        user_id: this.editingItem.user_id,
        persona_id: this.editingItem.persona_id,
        score: score,
        relation: relation,
        eval: evalText,
      });

      this.showToast("好感档案已成功更新");
      this.closeEditDialog();
      this.fetch();
    } catch (err) {
      console.error("更新好感档案失败:", err);
      this.showToast("更新失败: " + err.message, true);
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = "保存";
      }
    }
  }

  async handleReset(item) {
    const ok = await showConfirm(
      "重置好感档案",
      `确定要重置成员「${item.user_name || item.user_id}」在预设「${item.persona_id}」下的好感数据吗？\n该操作将清空累计好感分并恢复初始关系。`,
      { isDanger: true }
    );

    if (!ok) return;

    try {
      await this.api.post("affinity/reset", {
        group_key: item.group_key,
        user_id: item.user_id,
        persona_id: item.persona_id,
      });

      this.showToast("好感档案已成功重置");
      this.fetch();
    } catch (err) {
      console.error("重置好感档案失败:", err);
      this.showToast("重置失败: " + err.message, true);
    }
  }
}
