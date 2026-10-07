/**
 * Recall Page - 检索与打分测试页面
 * 支持设置检索词、k 值、用户/会话过滤，展示混合召回与时间衰减评分
 */

import { esc, typeLabel } from "./utils.js";

export class RecallPage {
  constructor(state, apiClient, peekPanel) {
    this.state = state;
    this.api = apiClient;
    this.peek = peekPanel;

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
    const queryInput = document.getElementById("recall-query");
    const searchBtn = document.getElementById("recall-search-btn");
    const kSlider = document.getElementById("recall-k");
    const kValue = document.getElementById("recall-k-value");

    if (kSlider && kValue) {
      kSlider.addEventListener("input", () => {
        kValue.textContent = kSlider.value;
      });
    }

    if (searchBtn) {
      searchBtn.addEventListener("click", () => this.runRecall());
    }

    if (queryInput) {
      queryInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing && (e.metaKey || e.ctrlKey)) {
          e.preventDefault();
          this.runRecall();
        }
      });
    }
  }

  async runRecall() {
    const searchBtn = document.getElementById("recall-search-btn");
    if (searchBtn && searchBtn.disabled) return;

    const query = document.getElementById("recall-query")?.value.trim();
    const k = parseInt(document.getElementById("recall-k")?.value) || 5;
    const sessionId = document.getElementById("recall-session")?.value.trim();

    if (!query) {
      this.showToast("请输入检索查询词", true);
      document.getElementById("recall-query")?.focus();
      return;
    }

    if (searchBtn) searchBtn.disabled = true;
    const feedback = document.getElementById("recall-feedback");
    const resultsContainer = document.getElementById("recall-results");

    if (feedback) {
      feedback.hidden = false;
      feedback.textContent = "正在执行检索与衰减打分…";
    }
    if (resultsContainer) {
      resultsContainer.replaceChildren();
      resultsContainer.setAttribute("aria-busy", "true");
    }

    const startTime = Date.now();

    try {
      const data = await this.api.post("recall/test", {
        query,
        k,
        session_id: sessionId || undefined,
      });
      const elapsed = Date.now() - startTime;
      this.renderResults(data, elapsed);
      if (feedback) feedback.hidden = true;
    } catch (e) {
      this.showToast(e.message || "检索失败", true);
      if (feedback) {
        feedback.textContent = e.message || "检索失败";
      }
    } finally {
      if (searchBtn) searchBtn.disabled = false;
      if (resultsContainer) resultsContainer.setAttribute("aria-busy", "false");
    }
  }

  renderResults(data, elapsed) {
    const hits = data.results || [];
    const count = hits.length;

    const statsHeader = document.getElementById("recall-stats");
    const countText = document.getElementById("recall-count-text");
    const timeText = document.getElementById("recall-time-text");
    const resultsContainer = document.getElementById("recall-results");

    if (statsHeader) statsHeader.classList.remove("hidden");
    if (countText) countText.textContent = `找到 ${count} 条匹配记忆`;
    if (timeText) timeText.textContent = `耗时: ${elapsed} ms`;

    if (!resultsContainer) return;

    if (count === 0) {
      resultsContainer.innerHTML = '<div class="table-empty" style="padding:40px 0">未召回到匹配记忆</div>';
      return;
    }

    let html = "";
    hits.forEach((hit) => {
      const rank = hit.rank || 1;
      const score = Number(hit.score || 0).toFixed(4);
      const owner = hit.owner || "--";
      const type = String(hit.type || "factual").toLowerCase();
      const text = hit.text || "";
      const daysAgo = hit.days_ago != null ? `${hit.days_ago} 天前` : "";

      html += '<div class="recall-result-card" style="background:var(--bg-panel, #fff);border:1px solid var(--border-color, #e5e7eb);border-radius:8px;padding:16px;margin-bottom:12px">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">';
      html += '<div style="display:flex;align-items:center;gap:8px">';
      html += '<span style="font-weight:700;color:var(--color-primary, #6366f1)">#' + rank + '</span>';
      html += '<span class="status-pill active" style="font-family:monospace;font-weight:700">得分: ' + score + '</span>';
      html += '<span class="type-tag">' + esc(typeLabel(type)) + '</span>';
      html += '<span style="font-size:12px;color:var(--text-secondary, #666);background:var(--bg-subtle, #f3f4f6);padding:2px 6px;border-radius:4px">归属: ' + esc(owner) + '</span>';
      html += '</div>';
      if (daysAgo) {
        html += '<span style="font-size:12px;color:var(--text-tertiary, #999)">' + esc(daysAgo) + '</span>';
      }
      html += '</div>';
      html += '<div style="font-size:14px;line-height:1.6;color:var(--text-primary, #111)">' + esc(text) + '</div>';
      html += '</div>';
    });

    resultsContainer.innerHTML = html;
  }
}
