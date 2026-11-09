(function () {
  const nativeFetch = window.fetch.bind(window);
  let tokenPromise = null;

  function isApi(input) {
    try {
      const url = new URL(typeof input === "string" ? input : input.url, location.href);
      return url.origin === location.origin && url.pathname.startsWith("/api/");
    } catch (e) {
      return false;
    }
  }

  async function getToken() {
    if (!tokenPromise) {
      tokenPromise = nativeFetch("/api/session", { cache: "no-store" })
        .then(async (r) => {
          if (!r.ok) throw new Error("无法建立本地会话");
          const data = await r.json();
          if (!data || !data.token) throw new Error("本地会话令牌为空");
          return data.token;
        })
        .catch((err) => {
          tokenPromise = null;
          throw err;
        });
    }
    return tokenPromise;
  }

  async function enspFetch(input, init) {
    const options = Object.assign({}, init || {});
    if (isApi(input)) {
      const headers = new Headers(options.headers || {});
      headers.set("X-Ensp-Token", await getToken());
      options.headers = headers;
    }
    return nativeFetch(input, options);
  }

  async function enspJSON(path, body) {
    const options = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    try {
      const response = await enspFetch(path, options);
      const text = await response.text();
      let data;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (e) {
        return { ok: false, error: `服务返回了非 JSON 内容（HTTP ${response.status}）` };
      }
      if (!response.ok && data.ok !== false) {
        return { ok: false, error: data.error || `请求失败（HTTP ${response.status}）` };
      }
      return data;
    } catch (e) {
      return { ok: false, error: "连不上本地服务，请确认程序仍在运行" };
    }
  }

  window.enspFetch = enspFetch;
  window.enspJSON = enspJSON;
})();
