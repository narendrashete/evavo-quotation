/* Tiny fetch wrapper: attaches the JWT, handles 401 by bouncing to login. */
const API = (() => {
  const TOKEN_KEY = "evavo_token";

  const getToken = () => localStorage.getItem(TOKEN_KEY);
  const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
  const clearToken = () => localStorage.removeItem(TOKEN_KEY);

  async function request(method, path, body, isForm) {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    let payload;
    if (isForm) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      payload = new URLSearchParams(body).toString();
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(path, { method, headers, body: payload });
    if (res.status === 401) {
      clearToken();
      if (window.onUnauthorized) window.onUnauthorized();
      throw new Error("Unauthorized");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  return {
    getToken, setToken, clearToken,
    login: (email, password) =>
      request("POST", "/api/auth/login", { username: email, password }, true),
    me: () => request("GET", "/api/auth/me"),
    products: (q, cat) => request("GET",
      "/api/products" + qs({ q, category: cat })),
    fx: () => request("GET", "/api/fx"),
    refreshFx: () => request("POST", "/api/fx/refresh"),
    leads: () => request("GET", "/api/masters/leads"),
    terms: () => request("GET", "/api/masters/terms"),
    quotes: () => request("GET", "/api/quotes"),
    createQuote: (data) => request("POST", "/api/quotes", data),
    getQuote: (id) => request("GET", "/api/quotes/" + id),
    previewQuote: (id) => request("GET", "/api/quotes/" + id + "/preview"),
    setQuoteStatus: (id, status) =>
      request("PATCH", "/api/quotes/" + id + "/status", { status }),
    emailQuote: (id) => request("POST", "/api/quotes/" + id + "/email"),
    reviseQuote: (id) => request("POST", "/api/quotes/" + id + "/revise"),
    async pdfBlob(id) {
      const res = await fetch("/api/quotes/" + id + "/pdf",
        { headers: { Authorization: "Bearer " + getToken() } });
      if (!res.ok) throw new Error("PDF failed");
      return res.blob();
    },
    // masters
    clients: () => request("GET", "/api/masters/clients"),
    createClient: (d) => request("POST", "/api/masters/clients", d),
    updateClient: (id, d) => request("PUT", "/api/masters/clients/" + id, d),
    deleteClient: (id) => request("DELETE", "/api/masters/clients/" + id),
    projects: (clientId) => request("GET", "/api/masters/projects" + qs({ client_id: clientId })),
    createProject: (d) => request("POST", "/api/masters/projects", d),
    updateProject: (id, d) => request("PUT", "/api/masters/projects/" + id, d),
    deleteProject: (id) => request("DELETE", "/api/masters/projects/" + id),
    createLead: (d) => request("POST", "/api/masters/leads", d),
    updateLead: (id, d) => request("PUT", "/api/masters/leads/" + id, d),
    deleteLead: (id) => request("DELETE", "/api/masters/leads/" + id),
    createTerms: (d) => request("POST", "/api/masters/terms", d),
    updateTerms: (id, d) => request("PUT", "/api/masters/terms/" + id, d),
    getEmailSetup: () => request("GET", "/api/masters/email-setup"),
    saveEmailSetup: (d) => request("PUT", "/api/masters/email-setup", d),
    updateProduct: (id, d) => request("PUT", "/api/masters/products/" + id, d),
    // users (admin-only)
    users: () => request("GET", "/api/users"),
    createUser: (d) => request("POST", "/api/users", d),
    updateUser: (id, d) => request("PUT", "/api/users/" + id, d),
    deleteUser: (id) => request("DELETE", "/api/users/" + id),
  };

  function qs(obj) {
    const parts = Object.entries(obj)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v));
    return parts.length ? "?" + parts.join("&") : "";
  }
})();
