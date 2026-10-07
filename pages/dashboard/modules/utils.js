/**
 * Utils - 纯工具函数集
 * 提供数据处理、UI 渲染相关的工具方法
 */

/**
 * 标准化重要性值（支持 0-1 和 0-10 两种输入）
 * @param {number} value - 输入值
 * @returns {number} 0-10 范围的重要性值
 */
export function normalizeImportance(value) {
  let n = Number(value);
  if (!Number.isFinite(n)) n = 0.6;
  if (n <= 1) n *= 10;
  return Math.min(10, Math.max(0, n));
}

/**
 * 从记忆详情对象中提取文本内容
 * @param {Object} detail - 记忆详情对象
 * @returns {string} 文本内容
 */
export function getDetailText(detail) {
  return detail.summary || detail.text || detail.content || "";
}

/**
 * HTML 转义，防止 XSS
 */
const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(text) {
  return String(text != null ? text : "").replace(/[&<>"']/g, (ch) => ESC_MAP[ch]);
}

/**
 * 渲染状态标签 pill
 * @param {string} status - 状态值（active/archived/deleted）
 * @returns {string} HTML 字符串
 */
export function statusPill(status) {
  const label = statusLabel(status);
  const cls = ["active", "archived", "deleted"].includes(status) ? status : "active";
  return '<span class="status-pill ' + cls + '">' + esc(label) + '</span>';
}

/**
 * 获取状态的显示文本
 * @param {string} status - 状态值
 * @returns {string} 显示文本
 */
export function statusLabel(status) {
  if (status === "active") return window.t ? window.t("status.active") : "活跃";
  if (status === "archived") return window.t ? window.t("status.archived") : "已归档";
  if (status === "deleted") return window.t ? window.t("status.deleted") : "已删除";
  return status || "--";
}

/**
 * 获取记忆类型的显示文本
 * @param {string} type - 类型值
 * @returns {string} 显示文本
 */
export function typeLabel(type) {
  const normalized = String(type || "").toLowerCase();
  if (normalized === "factual" || normalized === "fact") return window.t ? window.t("type.factual") : "事实";
  if (normalized === "preference") return window.t ? window.t("type.preference") : "偏好";
  if (normalized === "episodic" || normalized === "event") return window.t ? window.t("type.episodic") : "事件";
  if (normalized === "planned") return window.t ? window.t("type.planned") : "计划";
  if (normalized === "opinion") return window.t ? window.t("type.opinion") : "观点";
  if (normalized === "relational") return window.t ? window.t("type.relational") : "关系";
  return window.t ? window.t("type.general") : "通用";
}

export function atomLabel(type) {
  return typeLabel(type);
}

/**
 * 渲染图节点类型徽章 / 用户标识徽章
 * @param {string} type - 节点或类型
 * @returns {string} HTML 字符串
 */
export function nodeBadge(type) {
  const normalized = String(type || "unknown").toLowerCase();
  return '<span class="peek-node-badge ' + esc(normalized) + '">' + esc(type || "Unknown") + '</span>';
}

/**
 * 渲染元数据项（label: value）
 * @param {string} label - 标签
 * @param {string} value - 值
 * @returns {string} HTML 字符串
 */
export function metaItem(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return (
    '<div class="peek-meta-item">' +
    '<span class="peek-meta-label">' + esc(label) + '</span>' +
    '<span class="peek-meta-value">' + esc(String(value)) + '</span>' +
    '</div>'
  );
}

/**
 * 确认丢弃未保存的修改
 * @returns {Promise<boolean>} 是否确认丢弃
 */
export function confirmDiscardChanges() {
  return new Promise((resolve) => {
    const dialog = document.getElementById("discard-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {
      resolve(true);
      return;
    }
    dialog.returnValue = "";
    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      resolve(dialog.returnValue === "discard");
    };
    dialog.addEventListener("close", onClose);
    dialog.showModal();
  });
}

/**
 * 通用二次确认弹窗（替代原生 window.confirm，完全适配 iframe 沙盒环境）
 * @param {string} title - 弹窗标题
 * @param {string} message - 确认内容文本
 * @param {Object} [options] - 配置选项
 * @param {boolean} [options.isDanger=true] - 是否为危险操作（危险操作按钮为红色）
 * @param {string} [options.confirmText] - 确认按钮文字
 * @param {string} [options.cancelText] - 取消按钮文字
 * @returns {Promise<boolean>} 用户是否确认
 */
export function showConfirm(title, message, options = {}) {
  return new Promise((resolve) => {
    const dialog = document.getElementById("confirm-dialog");
    if (!dialog || typeof dialog.showModal !== "function") {
      // 降级兜底：无原生 dialog 支持时放行
      resolve(true);
      return;
    }

    const titleEl = document.getElementById("confirm-dialog-title");
    const msgEl = document.getElementById("confirm-dialog-message");
    const okBtn = document.getElementById("confirm-dialog-ok");
    const cancelBtn = document.getElementById("confirm-dialog-cancel");

    if (titleEl) titleEl.textContent = title || "确认操作";
    if (msgEl) msgEl.textContent = message || "";

    const isDanger = options.isDanger !== false;
    const confirmText = options.confirmText || (window.t ? window.t("common.confirm") : "确定");
    const cancelText = options.cancelText || (window.t ? window.t("common.cancel") : "取消");

    if (okBtn) {
      okBtn.textContent = confirmText;
      okBtn.className = isDanger ? "btn btn-danger" : "btn btn-primary";
    }
    if (cancelBtn) {
      cancelBtn.textContent = cancelText;
    }

    dialog.returnValue = "";

    const onClose = () => {
      dialog.removeEventListener("close", onClose);
      resolve(dialog.returnValue === "confirm");
    };

    dialog.addEventListener("close", onClose);
    dialog.showModal();
  });
}

