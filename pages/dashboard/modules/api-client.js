/**
 * API Client - 封装 AstrBot Bridge API 通信
 * 提供统一的 API 请求、错误处理、响应解包与重试机制
 */

export class ApiClient {
  constructor() {
    this.bridge = window.AstrBotPluginPage;
    this._context = null;
    this._pendingGets = new Map();
  }

  /**
   * 等待 Bridge 就绪
   * @returns {Promise<Object>} Bridge 上下文
   */
  async ready() {
    if (!this.bridge) {
      return {};
    }
    try {
      this._context = await this.bridge.ready();
      return this._context;
    } catch (e) {
      console.error("Bridge ready failed:", e);
      return {};
    }
  }

  /**
   * 获取当前上下文
   * @returns {Object} 上下文对象
   */
  getContext() {
    return this._context || this.bridge?.getContext() || {};
  }

  /**
   * 构建 endpoint 路径
   * @param {string} path - 原始路径（如 "stats", "memories"）
   * @returns {string} 带 page 前缀的路径（如 "page/stats"）
   */
  buildEndpoint(path) {
    const cleanPath = String(path).replace(/^\/+/, "");
    if (cleanPath.startsWith("page/")) {
      return cleanPath;
    }
    return "page/" + cleanPath.replace(/\/+/g, "/");
  }

  /**
   * 通用 API 请求（带重试与独立回退）
   * @param {string} path - API 路径
   * @param {Object} options - 请求选项
   * @returns {Promise<any>} API 响应
   */
  async request(path, options = {}) {
    const method = options.method || "GET";
    const body = options.body;
    const retries = options.retries ?? (method === "GET" ? 2 : 0);
    const endpoint = this.buildEndpoint(path);

    let lastError;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        if (this.bridge) {
          if (method === "GET") {
            const qi = endpoint.indexOf("?");
            if (qi !== -1) {
              const base = endpoint.substring(0, qi);
              const qs = endpoint.substring(qi + 1);
              const params = {};
              new URLSearchParams(qs).forEach((v, k) => { params[k] = v; });
              return await this.bridge.apiGet(base, params);
            }
            return await this.bridge.apiGet(endpoint, {});
          }
          return await this.bridge.apiPost(endpoint, body || {});
        }

        // 独立打开或开发者模式回退到原生 fetch
        const targetUrl = `/api/plug/astrbot_plugin_isolated_memory/${endpoint}`;
        const fetchOptions = {
          method,
          headers: { "Content-Type": "application/json" },
        };
        if (method === "POST" && body) {
          fetchOptions.body = JSON.stringify(body);
        }
        const res = await fetch(targetUrl, fetchOptions);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: ${res.statusText}`);
        }
        return await res.json();
      } catch (e) {
        lastError = e;
        if (attempt === retries) throw e;
        await new Promise(resolve => setTimeout(resolve, Math.min(800 * Math.pow(2, attempt), 3000)));
      }
    }
    throw lastError || new Error(window.t ? window.t("misc.requestFailed") : "Request failed");
  }

  /**
   * 解包 API 响应
   * @param {Object} response - API 响应
   * @returns {any} 解包后的数据
   */
  unwrapResponse(response) {
    if (response && response.status === "ok" && Object.prototype.hasOwnProperty.call(response, "data")) {
      return response.data;
    }
    if (response && response.status === "error") {
      throw new Error(response.message || (window.t ? window.t("misc.requestFailed") : "Request failed"));
    }
    return response || {};
  }

  /**
   * GET 请求
   * @param {string} path - API 路径
   * @param {Object} params - Query 参数
   * @returns {Promise<any>} 响应数据
   */
  async get(path, params = {}) {
    const query = new URLSearchParams(params);
    query.sort();
    const qs = query.toString();
    const fullPath = qs ? `${path}?${qs}` : path;
    if (!this._pendingGets.has(fullPath)) {
      const pending = this.request(fullPath, { method: "GET" })
        .then(response => this.unwrapResponse(response))
        .finally(() => this._pendingGets.delete(fullPath));
      this._pendingGets.set(fullPath, pending);
    }
    return this._pendingGets.get(fullPath);
  }

  /**
   * POST 请求
   * @param {string} path - API 路径
   * @param {Object} body - 请求体
   * @param {Object} options - 请求选项
   * @returns {Promise<any>} 响应数据
   */
  async post(path, body = {}, options = {}) {
    const response = await this.request(path, {
      method: "POST",
      body,
      ...options,
    });
    return this.unwrapResponse(response);
  }
}
