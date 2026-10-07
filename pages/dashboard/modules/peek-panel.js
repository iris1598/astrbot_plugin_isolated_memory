/**
 * Peek Panel - 侧边详情与编辑抽屉
 * 负责展示选中的记忆详情、修改内容、调整重要度/事实类型、单条删除
 */

import {
  normalizeImportance,
  getDetailText,
  esc,
  statusPill,
  typeLabel,
  metaItem,
  confirmDiscardChanges,
  showConfirm,
} from "./utils.js";

export class PeekPanel {
  constructor(state, apiClient) {
    this.state = state;
    this.api = apiClient;
    this._confirmResolve = null;
    this._detailGeneration = 0;
    this._saving = false;
    this._editSnapshot = "";

    this.initEventListeners();
  }

  initEventListeners() {
    const closeBtn = document.getElementById("peek-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => this.requestClose());
    }

    const overlay = document.getElementById("peek-overlay");
    if (overlay) {
      overlay.addEventListener("click", () => this.requestClose());
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        this.handleEscape();
      }
    });
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

  open(isWide = false) {
    const panel = document.getElementById("peek-panel");
    if (!panel) return;
    panel.removeAttribute("inert");
    panel.setAttribute("aria-hidden", "false");
    panel.classList.add("visible");
    if (isWide) panel.classList.add("wide");
    else panel.classList.remove("wide");

    const overlay = document.getElementById("peek-overlay");
    if (overlay) overlay.classList.add("visible");
  }

  close() {
    const panel = document.getElementById("peek-panel");
    if (!panel) return;
    panel.classList.remove("visible", "wide");
    panel.setAttribute("inert", "");
    panel.setAttribute("aria-hidden", "true");

    const overlay = document.getElementById("peek-overlay");
    if (overlay) overlay.classList.remove("visible");

    this.state.selectedMemory = null;
    this.state.isEditing = false;
    this.state._detailCache = null;
    this._detailGeneration++;
  }

  hasUnsavedChanges() {
    if (!this.state.isEditing) return false;
    const values = Array.from(
      document.querySelectorAll("#peek-body input, #peek-body textarea, #peek-body select"),
      (input) => input.value
    );
    return JSON.stringify(values) !== this._editSnapshot;
  }

  async canDiscard() {
    if (this._saving) {
      this.showToast(window.t ? window.t("flow.waitForSave") : "正在保存，请稍候…");
      return false;
    }
    return !this.hasUnsavedChanges() || (await confirmDiscardChanges());
  }

  async requestClose() {
    const gen = ++this._detailGeneration;
    if (!(await this.canDiscard()) || gen !== this._detailGeneration) return false;
    this.close();
    return true;
  }

  async handleEscape() {
    const panel = document.getElementById("peek-panel");
    if (!panel || !panel.classList.contains("visible")) return false;
    if (this.state.isEditing) {
      if (!(await this.canDiscard())) return true;
      if (this.state._detailCache) {
        this.renderDetailView(this.state._detailCache);
      } else {
        this.close();
      }
      return true;
    }
    this.close();
    return true;
  }

  async renderMemory(memory) {
    const gen = ++this._detailGeneration;
    if ((this.state.isEditing || this._saving) && !(await this.canDiscard())) return;
    if (gen !== this._detailGeneration) return;

    this.state.selectedMemory = memory;
    this.state.isEditing = false;
    const memoryId = memory.doc_id || memory.memory_id || memory.id;

    let detail = null;
    try {
      detail = await this.api.get("memories/detail", { memory_id: memoryId });
      if (gen !== this._detailGeneration) return;
    } catch (_) {
      detail = null;
    }

    if (!detail) {
      const rawMeta = (memory.raw && memory.raw.metadata) || memory.metadata || {};
      detail = {
        memory_id: memoryId,
        doc_id: memory.doc_id || memoryId,
        text: memory.content || memory.text || memory.summary || "",
        content: memory.content || memory.text || memory.summary || "",
        summary: memory.summary || "",
        session_id: rawMeta.memory_owner || rawMeta.user_id || memory.owner || "--",
        memory_owner: rawMeta.memory_owner || rawMeta.user_id || memory.owner || "--",
        memory_type: memory.memory_type || rawMeta.type || "FACTUAL",
        importance: memory.importance != null ? Number(memory.importance) : 0.6,
        status: memory.status || "active",
        created_at: memory.created_at || "--",
        updated_at: memory.updated_at || "--",
        metadata: rawMeta,
      };
    }

    this.state._detailCache = { ...detail };
    this.renderDetailView(this.state._detailCache);
    this.open(true);
  }

  renderDetailView(detail) {
    this.state._detailCache = detail;
    this.state.isEditing = false;

    const id = detail.doc_id || detail.memory_id || "--";
    const type = String(detail.memory_type || "FACTUAL").toUpperCase();
    const status = detail.status || "active";
    const impDisplay = (normalizeImportance(detail.importance) / 10).toFixed(2);
    const content = getDetailText(detail);
    const created = detail.created_at || "--";
    const updated = detail.updated_at || "--";
    const owner = detail.session_id || detail.memory_owner || "--";

    const titleEl = document.getElementById("peek-title");
    if (titleEl) {
      titleEl.textContent = window.t ? window.t("detail.memoryTitle", id) : `记忆 #${id}`;
    }

    let html = "";

    // 头部标签
    html += '<div class="memory-detail-header">';
    html += statusPill(status);
    html += '<span class="type-tag">' + esc(typeLabel(type)) + '</span>';
    html += '<span class="memory-detail-importance">重要度: ' + impDisplay + '</span>';
    html += '</div>';

    // 快捷操作
    html += '<div class="memory-detail-actions">';
    html += '<button class="btn btn-sm btn-secondary" id="peek-edit-btn"><i data-lucide="square-pen" aria-hidden="true"></i><span>' + (window.t ? window.t("detail.editBtn") : "编辑") + '</span></button>';
    html += '<button class="btn btn-sm btn-danger" id="peek-delete-btn"><i data-lucide="trash-2" aria-hidden="true"></i><span>' + (window.t ? window.t("detail.deleteBtn") : "删除") + '</span></button>';
    html += '</div>';

    // 内容区
    html += '<div class="peek-section"><div class="peek-section-title">' + (window.t ? window.t("detail.content") : "记忆内容") + '</div>';
    html += '<div class="memory-detail-content" id="detail-content-display">' + esc(content) + '</div></div>';

    // 元数据区
    html += '<div class="peek-section"><div class="peek-section-title">元数据</div>';
    html += '<div class="peek-meta-grid">';
    html += metaItem("归属用户 (UMO)", owner);
    html += metaItem("记忆类型", typeLabel(type));
    html += metaItem("重要度", impDisplay);
    html += metaItem("创建时间", created);
    html += metaItem("最近更新", updated);
    html += metaItem("文档 ID", id);
    html += '</div></div>';

    const bodyEl = document.getElementById("peek-body");
    if (bodyEl) {
      bodyEl.innerHTML = html;
      if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
      }

      document.getElementById("peek-edit-btn")?.addEventListener("click", () => this.renderEditView(detail));
      document.getElementById("peek-delete-btn")?.addEventListener("click", () => this.handleDelete(id));
    }
  }

  renderEditView(detail) {
    this.state.isEditing = true;
    const content = getDetailText(detail);
    const impVal = (normalizeImportance(detail.importance) / 10).toFixed(2);
    const currentType = String(detail.memory_type || "FACTUAL").toLowerCase();

    let html = "";
    html += '<div class="peek-section"><label class="recall-form-label" for="edit-content">记忆内容</label>';
    html += '<textarea id="edit-content" class="input textarea" rows="6" style="width:100%">' + esc(content) + '</textarea></div>';

    html += '<div class="recall-form-row" style="margin-top:12px">';
    html += '<div class="recall-form-field" style="flex:1">';
    html += '<label class="recall-form-label" for="edit-type">事实类型</label>';
    html += '<select id="edit-type" class="select input" style="width:100%">';
    html += '<option value="factual"' + (currentType === "factual" ? " selected" : "") + '>事实 (Factual)</option>';
    html += '<option value="preference"' + (currentType === "preference" ? " selected" : "") + '>偏好 (Preference)</option>';
    html += '<option value="episodic"' + (currentType === "episodic" ? " selected" : "") + '>事件 (Episodic)</option>';
    html += '<option value="planned"' + (currentType === "planned" ? " selected" : "") + '>计划 (Planned)</option>';
    html += '<option value="general"' + (currentType === "general" ? " selected" : "") + '>通用 (General)</option>';
    html += '</select></div>';

    html += '<div class="recall-form-field" style="width:140px">';
    html += '<label class="recall-form-label" for="edit-importance">重要度 (0.1~1.0)</label>';
    html += '<input id="edit-importance" type="number" step="0.05" min="0.1" max="1.0" class="input" value="' + impVal + '" />';
    html += '</div></div>';

    html += '<div class="prompt-editor-actions" style="margin-top:20px; display:flex; gap:10px">';
    html += '<button class="btn btn-secondary" id="edit-cancel-btn"><i data-lucide="x" aria-hidden="true"></i><span>取消</span></button>';
    html += '<button class="btn btn-primary" id="edit-save-btn"><i data-lucide="save" aria-hidden="true"></i><span>保存修改</span></button>';
    html += '</div>';

    const bodyEl = document.getElementById("peek-body");
    if (bodyEl) {
      bodyEl.innerHTML = html;
      if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
      }

      this._editSnapshot = JSON.stringify(
        Array.from(bodyEl.querySelectorAll("input, textarea, select"), (el) => el.value)
      );

      document.getElementById("edit-cancel-btn")?.addEventListener("click", () => {
        this.renderDetailView(detail);
      });
      document.getElementById("edit-save-btn")?.addEventListener("click", () => {
        this.handleSave(detail);
      });
    }
  }

  async handleSave(detail) {
    const content = document.getElementById("edit-content")?.value.trim();
    const factType = document.getElementById("edit-type")?.value.trim();
    const imp = parseFloat(document.getElementById("edit-importance")?.value) || 0.6;

    if (!content) {
      this.showToast("记忆文本不能为空", true);
      return;
    }

    this._saving = true;
    const saveBtn = document.getElementById("edit-save-btn");
    if (saveBtn) saveBtn.disabled = true;

    try {
      await this.api.post("memories/update", {
        memory_id: detail.doc_id || detail.memory_id,
        content: content,
        memory_type: factType,
        importance: Math.max(0.1, Math.min(1.0, imp)),
      });

      this.showToast("保存成功");
      this.state.isEditing = false;
      detail.text = content;
      detail.content = content;
      detail.summary = content;
      detail.memory_type = factType.toUpperCase();
      detail.importance = imp;

      this.renderDetailView(detail);

      // 通知列表页面刷新
      if (window._memoryPageInstance) {
        window._memoryPageInstance.fetch();
      }
    } catch (e) {
      this.showToast(e.message || "保存失败", true);
    } finally {
      this._saving = false;
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  async handleDelete(memoryId) {
    const ok = await showConfirm(
      "删除记忆确认",
      "确定要删除此条记忆吗？该操作不可恢复！",
      { isDanger: true, confirmText: "删除" }
    );
    if (!ok) return;

    try {
      await this.api.post("memories/batch-delete", {
        memory_ids: [memoryId],
      });
      this.showToast("删除成功");
      this.close();

      if (window._memoryPageInstance) {
        window._memoryPageInstance.fetch();
      }
    } catch (e) {
      this.showToast(e.message || "删除失败", true);
    }
  }
}
