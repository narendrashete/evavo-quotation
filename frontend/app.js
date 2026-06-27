/* Evavo Quotation Platform — front-end app logic, wired to the FastAPI backend.
 * Cost/margin fields only exist in API responses for manager/admin, so the UI
 * simply renders whatever the server returns (defense in depth on top of the
 * server-side gating). */

// ---- State ----
let currentUser = null;
let canSeeCost = false;
let PRODUCTS = [];          // from /api/products (cost fields present only for managers)
let LINES = [];             // [{pid, qty, disc}]
let FX = { INR: 1 };        // display rate_to_inr by currency
const SYM = { INR: "₹", USD: "$", EUR: "€" };
let TERMS = [];
let currentQuoteId = null;
let lastPreview = null;     // server client-preview payload after save

const CATCOLOR = {
  "Salon Equipment": ["#1a9fe0", "#0d6efd"], "Massage Beds": ["#13b3a6", "#0f9488"],
  "Loungers": ["#8b5cf6", "#6d28d9"], "Accessories": ["#f0a500", "#d97706"],
};
const CATICON = {
  "Salon Equipment": "💈", "Massage Beds": "🛏️", "Loungers": "🪑", "Accessories": "🧴",
};
const icon = (c) => CATICON[c] || "📦";

// ---- Helpers ----
const $ = (id) => document.getElementById(id);
function toast(msg, isErr) {
  const t = $("toast"); t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => { t.className = "toast"; }, 2600);
}
function cur() { const s = $("curSel"); return s && s.value ? s.value : "INR"; }
function fmt(inr) {
  const c = cur(); const rate = FX[c] || 1; const v = inr / rate;
  return SYM[c] + " " + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
}
function prod(id) { return PRODUCTS.find((p) => p.id === id); }
function prodImg(p, size) {
  const c = CATCOLOR[p.category] || ["#1a9fe0", "#0d6efd"];
  const cls = size === "sm" ? "thumb-sm" : (size === "lg" ? "thumb-lg" : "thumb-md");
  return '<div class="thumb ' + cls + '" style="background:linear-gradient(135deg,' +
    c[0] + ',' + c[1] + ')"><span class="tg">' + icon(p.category) + "</span></div>";
}

// ---- Auth / boot ----
window.onUnauthorized = () => showLogin();

function fillLogin(email, pass) { $("loginEmail").value = email; $("loginPass").value = pass; }

async function doLogin(e) {
  e.preventDefault();
  $("loginErr").classList.add("hide");
  $("loginBtn").disabled = true;
  try {
    const res = await API.login($("loginEmail").value.trim(), $("loginPass").value);
    API.setToken(res.access_token);
    await boot();
  } catch (err) {
    const el = $("loginErr"); el.textContent = "Sign-in failed: " + err.message;
    el.classList.remove("hide");
  } finally {
    $("loginBtn").disabled = false;
  }
  return false;
}

function logout() { API.clearToken(); showLogin(); }
function showLogin() {
  $("appRoot").classList.add("hide"); $("bnav").classList.add("hide");
  $("loginWrap").classList.remove("hide");
}

async function boot() {
  try {
    currentUser = await API.me();
  } catch (e) { showLogin(); return; }
  canSeeCost = currentUser.role === "manager" || currentUser.role === "admin";
  $("loginWrap").classList.add("hide");
  $("appRoot").classList.remove("hide");
  if (window.innerWidth <= 680) $("bnav").classList.remove("hide");

  $("welcome").textContent = "Welcome back, " + currentUser.name.split(" ")[0];
  $("roleLabel").textContent = currentUser.role.charAt(0).toUpperCase() + currentUser.role.slice(1) + " view";
  $("rolePill").className = "role-pill" + (canSeeCost ? " mgr" : "");
  $("userAvatar").textContent = currentUser.name.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  applyRoleVisibility();

  await Promise.all([loadFx(), loadTerms(), loadProducts()]);
  buildCurrencyOptions();
  buildCategoryOptions();
  renderProducts();
  renderItems();
  recalc();
  updateCart();
  await loadDashboard();
}

function applyRoleVisibility() {
  document.querySelectorAll("[data-cost]").forEach((e) => e.classList.toggle("hide", !canSeeCost));
  document.querySelectorAll("[data-nocost]").forEach((e) => e.classList.toggle("hide", canSeeCost));
}

// ---- Data loads ----
async function loadProducts() { PRODUCTS = await API.products(); }
async function loadTerms() {
  TERMS = await API.terms();
  const sel = $("qTerms"); sel.innerHTML = "";
  TERMS.forEach((t) => { const o = document.createElement("option"); o.value = t.id; o.textContent = t.name; sel.appendChild(o); });
}
async function loadFx() {
  const rows = await API.fx();
  FX = { INR: 1 };
  rows.filter((r) => r.kind === "display").forEach((r) => { FX[r.currency] = r.rate_to_inr; });
}
function buildCurrencyOptions() {
  const sel = $("curSel"); sel.innerHTML = "";
  ["INR", "USD", "EUR"].filter((c) => FX[c]).forEach((c) => {
    const o = document.createElement("option"); o.value = c;
    o.textContent = SYM[c] + " " + c; sel.appendChild(o);
  });
}
function buildCategoryOptions() {
  const cats = [...new Set(PRODUCTS.map((p) => p.category))].sort();
  [["prodCat"], ["pkCat"]].forEach(([id]) => {
    const sel = $(id); const keep = sel.querySelector("option[value='']");
    sel.innerHTML = ""; if (keep) sel.appendChild(keep);
    cats.forEach((c) => { const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o); });
  });
}

// ---- Navigation ----
const titles = { dashboard: "Dashboard", pipeline: "Sales Pipeline", products: "Product Catalog", builder: "Quote Builder", preview: "Client Preview", masters: "Masters" };
function goto(v) {
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === v));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".bottomnav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("tbTitle").textContent = titles[v] || "";
  if (v === "preview") renderPreview();
  if (v === "masters") renderMasters();
  window.scrollTo(0, 0);
}
document.querySelectorAll(".nav-item,.bottomnav button").forEach((b) => {
  if (b.dataset.view) b.addEventListener("click", () => goto(b.dataset.view));
});
function newQuote() {
  LINES = []; currentQuoteId = null; lastPreview = null;
  $("builderSub").textContent = "New draft";
  renderItems(); recalc(); updateCart(); goto("builder");
}

// ---- Product catalog ----
function renderProducts() {
  const g = $("prodGrid"); if (!g) return;
  const q = ($("prodSearch").value || "").toLowerCase();
  const cat = $("prodCat").value;
  g.innerHTML = "";
  PRODUCTS.filter((p) => (!cat || p.category === cat) &&
    (p.name.toLowerCase().includes(q) || (p.model_no || "").toLowerCase().includes(q)))
    .forEach((p) => {
      const d = document.createElement("div"); d.className = "prod";
      const costRow = (canSeeCost && p.final_c2e != null)
        ? '<div class="prow"><span>Cost (C2E)</span><span class="cost">₹ ' + p.final_c2e.toLocaleString("en-IN") + "</span></div>" : "";
      d.innerHTML = prodImg(p, "md") + '<div class="pcat">' + p.category + '</div><b>' + p.name +
        '</b><div class="pmodel">' + (p.model_no || "") + '</div><div class="prow"><span>List price</span><span class="price">₹ ' +
        Math.round(p.list_price).toLocaleString("en-IN") + "</span></div>" + costRow;
      g.appendChild(d);
    });
  if (!g.children.length) g.innerHTML = '<div class="empty">No products match.</div>';
}

// ---- Picker ----
function openPicker() { $("picker").classList.add("open"); renderPicker(); }
function closePicker() { $("picker").classList.remove("open"); }
function renderPicker() {
  const g = $("pickerGrid");
  const q = ($("pkSearch").value || "").toLowerCase();
  const cat = $("pkCat").value;
  g.innerHTML = "";
  PRODUCTS.filter((p) => (!cat || p.category === cat) &&
    (p.name.toLowerCase().includes(q) || (p.model_no || "").toLowerCase().includes(q)))
    .forEach((p) => {
      const d = document.createElement("div"); d.className = "pick";
      const costLine = (canSeeCost && p.final_c2e != null)
        ? '<span class="pk-cost">Cost: ₹ ' + p.final_c2e.toLocaleString("en-IN") + "</span>" : "";
      d.innerHTML = prodImg(p, "md") + '<div class="pk-b"><span class="pk-cat">' + p.category +
        '</span><b>' + p.name + '</b><span class="pk-model">' + (p.model_no || "") +
        '</span><span class="pk-price">₹ ' + Math.round(p.client_unit_price).toLocaleString("en-IN") + "</span>" + costLine +
        '</div><div class="pk-add"><div class="qstep"><button onclick="pq(' + p.id + ',-1)">−</button><input id="pq' + p.id +
        '" value="1" readonly><button onclick="pq(' + p.id + ',1)">＋</button></div><button class="btn primary sm" id="pa' + p.id +
        '" onclick="pickAdd(' + p.id + ')">Add to cart</button></div>';
      g.appendChild(d);
    });
}
function pq(id, delta) { const i = $("pq" + id); i.value = Math.max(1, (parseInt(i.value, 10) || 1) + delta); }
function pickAdd(id) {
  const qty = parseInt($("pq" + id).value, 10) || 1;
  const ex = LINES.find((l) => l.pid === id);
  if (ex) ex.qty += qty; else LINES.push({ pid: id, qty, disc: 0 });
  const btn = $("pa" + id);
  if (btn) { btn.textContent = "✓ Added"; btn.classList.add("added-flash"); setTimeout(() => { btn.textContent = "Add to cart"; btn.classList.remove("added-flash"); }, 900); }
  renderItems(); recalc(); updateCart();
}
function updateCart() {
  const n = LINES.length;
  if ($("cartCnt")) $("cartCnt").textContent = n + " item" + (n !== 1 ? "s" : "") + " in quote";
  if ($("addBadge")) $("addBadge").textContent = n;
}

// ---- Line items ----
function removeItem(idx) { LINES.splice(idx, 1); renderItems(); recalc(); updateCart(); }
function renderItems() {
  const b = $("itemsBody"); b.innerHTML = "";
  if (!LINES.length) { b.innerHTML = '<tr><td colspan="9"><div class="empty">No items yet — click <b>🛍️ Add Products</b> to build the quote.</div></td></tr>'; return; }
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const tr = document.createElement("tr");
    const costCells = canSeeCost
      ? '<td class="num cost-col" data-cost>' + fmt((p.final_c2e || 0) * ln.qty) + '</td><td class="num cost-col mcell" data-cost></td>'
      : '<td class="num cost-col hide" data-cost></td><td class="num cost-col mcell hide" data-cost></td>';
    tr.innerHTML = "<td>" + prodImg(p, "sm") + '</td><td class="pname"><b>' + p.name + "</b><br><small>" + (p.model_no || "") +
      '</small></td><td class="num">' + fmt(p.client_unit_price) +
      '</td><td class="num"><input type="number" min="1" value="' + ln.qty + '" onchange="upd(' + idx + ",'qty',this.value)\"></td>" +
      '<td class="num"><input type="number" min="0" max="100" value="' + ln.disc + '" onchange="upd(' + idx + ",'disc',this.value)\"></td>" +
      costCells + '<td class="num amtcell"></td><td><button class="del" onclick="removeItem(' + idx + ')">✕</button></td>';
    b.appendChild(tr);
  });
}
function upd(idx, field, val) { LINES[idx][field] = parseFloat(val) || 0; recalc(); }

// ---- Recalc (instant client-side preview; server is authoritative on save) ----
function recalc() {
  let sub = 0, gross = 0, cost = 0;
  const rows = document.querySelectorAll("#itemsBody tr");
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const lineGross = p.client_unit_price * ln.qty;
    const lineNet = lineGross * (1 - ln.disc / 100);
    const lineCost = (p.final_c2e || 0) * ln.qty;
    sub += lineNet; gross += lineGross; cost += lineCost;
    if (rows[idx]) {
      const ac = rows[idx].querySelector(".amtcell"); if (ac) ac.textContent = fmt(lineNet);
      const mc = rows[idx].querySelector(".mcell");
      if (mc && canSeeCost) { const m = lineNet - lineCost; const mp = lineNet > 0 ? (m / lineNet * 100) : 0; mc.innerHTML = '<span class="' + (m >= 0 ? "mpos" : "mneg") + '">' + fmt(m) + " · " + mp.toFixed(0) + "%</span>"; }
    }
  });
  const discGiven = gross - sub;
  const install = $("aInstall").checked ? sub * 0.105 : 0;
  const pack = parseFloat($("aPack").value) || 0;
  const freight = parseFloat($("aFreight").value) || 0;
  const grand = sub + install + pack + freight;
  $("sSub").textContent = fmt(sub);
  $("sDisc").textContent = "– " + fmt(discGiven);
  $("sInstall").textContent = fmt(install);
  $("sGrand").textContent = fmt(grand);
  if (canSeeCost) {
    const totMargin = sub - cost;
    $("mCost").textContent = fmt(cost);
    $("mMargin").textContent = fmt(totMargin);
    $("mPct").textContent = (sub > 0 ? (totMargin / sub * 100) : 0).toFixed(1) + "%";
  }
  const overallDisc = gross > 0 ? (discGiven / gross * 100) : 0;
  const anyHigh = LINES.some((l) => l.disc > 15);
  $("approvalBox").classList.toggle("hide", !(overallDisc > 12 || anyHigh));
  window._Q = { sub, install, pack, freight, grand };
}

// ---- Save quote (server computes authoritative totals) ----
async function saveQuote() {
  if (!LINES.length) { toast("Add at least one product first.", true); return; }
  $("saveBtn").disabled = true;
  try {
    const payload = {
      customer_name: $("qCustomer").value.trim(),
      customer_email: $("qEmail").value.trim() || null,
      currency: cur(),
      terms_template_id: parseInt($("qTerms").value, 10) || null,
      install_enabled: $("aInstall").checked,
      install_pct: 0.105,
      packaging: parseFloat($("aPack").value) || 0,
      freight: parseFloat($("aFreight").value) || 0,
      lines: LINES.map((l) => ({ product_id: l.pid, qty: l.qty, line_disc: l.disc })),
    };
    const q = await API.createQuote(payload);
    currentQuoteId = q.id;
    lastPreview = await API.previewQuote(q.id);
    $("builderSub").textContent = q.quote_no + " · " + (q.totals.needs_approval ? "Needs approval" : "Draft");
    toast("Quote " + q.quote_no + " saved.");
    await loadDashboard();
    goto("preview");
  } catch (err) {
    toast("Save failed: " + err.message, true);
  } finally {
    $("saveBtn").disabled = false;
  }
}

// ---- Client preview ----
function renderPreview() {
  const termId = parseInt($("qTerms").value, 10);
  const term = TERMS.find((t) => t.id === termId) || TERMS[0];
  $("pvTerms").innerHTML = "<b>Terms &amp; Conditions</b>\n" + (term ? term.body : "") + "\n\n<b>Evavo Wellness &amp; Solutions LLP</b>";
  $("pvBillTo").innerHTML = "<br>" + $("qCustomer").value + "<br>" + ($("qEmail").value || "");
  $("pvCur").textContent = cur() + " (" + SYM[cur()] + ")";

  // Prefer the server's client-safe payload after a save; else compute locally.
  const b = $("pvBody"); b.innerHTML = "";
  if (lastPreview && currentQuoteId) {
    $("pvNo").textContent = lastPreview.quote_no;
    $("pvDate").textContent = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    lastPreview.lines.forEach((ln, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + (i + 1) + "</td><td>" + ln.name + "<br><span style='color:#7a8a99;font-size:11px'>" + (ln.model_no || "") +
        "</span></td><td class=\"num\">" + fmt(ln.unit_price) + '</td><td class="num">' + ln.qty + '</td><td class="num">' + fmt(ln.line_net) + "</td>";
      b.appendChild(tr);
    });
    const t = lastPreview.totals;
    $("pvSub").textContent = fmt(t.subtotal_net);
    $("pvInstall").textContent = fmt(t.installation);
    $("pvPack").textContent = fmt(lastPreview.packaging || 0);
    $("pvGrand").textContent = fmt(t.grand_total);
  } else {
    recalc();
    $("pvNo").textContent = "(unsaved draft)";
    $("pvDate").textContent = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    LINES.forEach((ln, i) => {
      const p = prod(ln.pid); if (!p) return;
      const net = p.client_unit_price * ln.qty * (1 - ln.disc / 100);
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + (i + 1) + '</td><td><div class="cli-thumb">' + prodImg(p, "sm") +
        "<div><b style='color:var(--navy)'>" + p.name + "</b><br><span style='color:#7a8a99;font-size:11px'>" + (p.model_no || "") +
        "</span></div></div></td><td class=\"num\">" + fmt(p.client_unit_price) + '</td><td class="num">' + ln.qty + '</td><td class="num">' + fmt(net) + "</td>";
      b.appendChild(tr);
    });
    const Q = window._Q || {};
    $("pvSub").textContent = fmt(Q.sub || 0);
    $("pvInstall").textContent = fmt(Q.install || 0);
    $("pvPack").textContent = fmt(Q.pack || 0);
    $("pvGrand").textContent = fmt(Q.grand || 0);
  }
}

// ---- Quote output: PDF / email / revise ----
function requireSaved() {
  if (!currentQuoteId) { toast("Save the quote first.", true); return false; }
  return true;
}
async function downloadPdf() {
  if (!requireSaved()) return;
  try {
    const blob = await API.pdfBlob(currentQuoteId);
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (e) { toast("PDF failed: " + e.message, true); }
}
async function emailCurrent() {
  if (!requireSaved()) return;
  try {
    const r = await API.emailQuote(currentQuoteId);
    toast(r.dry_run ? "Dry run — configure Email Setup to actually send (to " + r.to + ")" : "Emailed to " + r.to);
  } catch (e) { toast("Email failed: " + e.message, true); }
}
async function reviseCurrent() {
  if (!requireSaved()) return;
  try {
    const rev = await API.reviseQuote(currentQuoteId);
    currentQuoteId = rev.id; lastPreview = null;
    LINES = rev.lines.map((l) => ({ pid: l.product_id, qty: l.qty, disc: l.line_disc }));
    $("builderSub").textContent = rev.quote_no + " · Revision draft";
    renderItems(); recalc(); updateCart();
    toast("Created revision " + rev.quote_no);
    goto("builder");
  } catch (e) { toast("Revise failed: " + e.message, true); }
}

// ---- Masters screens ----
let currentMtab = "clients";
function mtab(name) {
  currentMtab = name;
  document.querySelectorAll("#mTabs button").forEach((b) => b.classList.toggle("on", b.dataset.mtab === name));
  renderMasters();
}
async function renderMasters() {
  const c = $("mContent"); c.innerHTML = '<div class="empty">Loading…</div>';
  try {
    if (currentMtab === "clients") await renderClientsMaster(c);
    else if (currentMtab === "leads") await renderLeadsMaster(c);
    else if (currentMtab === "terms") await renderTermsMaster(c);
    else if (currentMtab === "email") await renderEmailMaster(c);
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m])));

async function renderClientsMaster(c) {
  const rows = await API.clients();
  const delCol = canSeeCost ? "<th></th>" : "";
  c.innerHTML =
    '<div class="card pad" style="margin-bottom:16px"><div class="section-title">Add Client</div><div class="f2">' +
    '<div class="field"><label>Name</label><input id="ncName"></div>' +
    '<div class="field"><label>Email</label><input id="ncEmail"></div>' +
    '<div class="field"><label>Phone</label><input id="ncPhone"></div>' +
    '<div class="field"><label>City</label><input id="ncCity"></div></div>' +
    '<button class="btn primary sm" onclick="addClient()">＋ Add Client</button></div>' +
    '<div class="card pad"><div class="section-title">Clients (' + rows.length + ')</div>' +
    '<table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>City</th>' + delCol + "</tr></thead><tbody>" +
    (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.phone) + "</td><td>" + esc(r.city) +
      "</td>" + (canSeeCost ? '<td><button class="del" onclick="delClient(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
      : '<tr><td colspan="5"><div class="empty">No clients yet.</div></td></tr>') + "</tbody></table></div>";
}
async function addClient() {
  const name = $("ncName").value.trim();
  if (!name) { toast("Client name is required.", true); return; }
  await API.createClient({ name, email: $("ncEmail").value.trim() || null, phone: $("ncPhone").value.trim() || null, city: $("ncCity").value.trim() || null });
  toast("Client added."); renderMasters();
}
async function delClient(id) { await API.deleteClient(id); toast("Client deleted."); renderMasters(); }

async function renderLeadsMaster(c) {
  const rows = await API.leads();
  const stageName = ["Leads", "Quoted", "Negotiation", "Won"];
  c.innerHTML =
    '<div class="card pad" style="margin-bottom:16px"><div class="section-title">Add Lead</div><div class="f2">' +
    '<div class="field"><label>Name</label><input id="nlName"></div>' +
    '<div class="field"><label>Owner</label><input id="nlOwner"></div>' +
    '<div class="field"><label>Stage</label><select id="nlStage"><option value="0">Leads</option><option value="1">Quoted</option><option value="2">Negotiation</option><option value="3">Won</option></select></div>' +
    '<div class="field"><label>Amount (₹)</label><input id="nlAmount" type="number" value="0"></div></div>' +
    '<button class="btn primary sm" onclick="addLead()">＋ Add Lead</button></div>' +
    '<div class="card pad"><div class="section-title">Leads (' + rows.length + ')</div>' +
    '<table class="tbl"><thead><tr><th>Name</th><th>Owner</th><th>Stage</th><th class="num">Amount</th></tr></thead><tbody>' +
    (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.owner) + "</td><td>" + stageName[r.stage] +
      '</td><td class="num">₹' + (r.amount || 0).toLocaleString("en-IN") + "</td></tr>").join("")
      : '<tr><td colspan="4"><div class="empty">No leads yet.</div></td></tr>') + "</tbody></table></div>";
}
async function addLead() {
  const name = $("nlName").value.trim();
  if (!name) { toast("Lead name is required.", true); return; }
  await API.createLead({ name, owner: $("nlOwner").value.trim() || null, stage: parseInt($("nlStage").value, 10), amount: parseFloat($("nlAmount").value) || 0 });
  toast("Lead added."); renderMasters(); loadDashboard();
}

async function renderTermsMaster(c) {
  const rows = await API.terms();
  c.innerHTML =
    '<div class="card pad" style="margin-bottom:16px"><div class="section-title">Add Terms Template</div>' +
    '<div class="f2"><div class="field"><label>Name</label><input id="ntName"></div>' +
    '<div class="field"><label>Kind</label><select id="ntKind"><option value="regular">Regular (Domestic)</option><option value="currency">Currency / International</option></select></div></div>' +
    '<div class="field"><label>Body</label><textarea id="ntBody" rows="5"></textarea></div>' +
    '<button class="btn primary sm" onclick="addTerms()">＋ Add Template</button></div>' +
    rows.map((t) =>
      '<div class="card pad" style="margin-bottom:12px"><div class="section-title">' + esc(t.name) + ' <span class="badge cli">' + t.kind + "</span></div>" +
      '<textarea id="tb' + t.id + '" rows="5" style="width:100%;border:1px solid var(--line);border-radius:9px;padding:10px">' + esc(t.body) + "</textarea>" +
      '<button class="btn ghost sm" style="margin-top:10px" onclick="saveTerms(' + t.id + ",'" + esc(t.name).replace(/'/g, "") + "','" + t.kind + "')\">💾 Save</button></div>").join("");
}
async function addTerms() {
  const name = $("ntName").value.trim();
  if (!name) { toast("Template name required.", true); return; }
  await API.createTerms({ name, kind: $("ntKind").value, body: $("ntBody").value });
  toast("Template added."); renderMasters(); loadTerms();
}
async function saveTerms(id, name, kind) {
  await API.updateTerms(id, { name, kind, body: $("tb" + id).value });
  toast("Template saved."); loadTerms();
}

async function renderEmailMaster(c) {
  if (!canSeeCost) { c.innerHTML = '<div class="empty">Email Setup is manager-only.</div>'; return; }
  let s = {};
  try { s = (await API.getEmailSetup()) || {}; } catch (e) { s = {}; }
  c.innerHTML =
    '<div class="card pad"><div class="section-title">SMTP / Email Setup</div>' +
    '<div class="f2"><div class="field"><label>SMTP Host</label><input id="esHost" value="' + esc(s.smtp_host || "") + '"></div>' +
    '<div class="field"><label>SMTP Port</label><input id="esPort" type="number" value="' + (s.smtp_port || 587) + '"></div>' +
    '<div class="field"><label>Username</label><input id="esUser" value="' + esc(s.username || "") + '"></div>' +
    '<div class="field"><label>Password</label><input id="esPass" type="password" placeholder="(unchanged)"></div>' +
    '<div class="field"><label>From Email</label><input id="esFrom" value="' + esc(s.from_email || "") + '"></div>' +
    '<div class="field"><label>Use TLS</label><select id="esTls"><option value="true"' + (s.use_tls !== false ? " selected" : "") + '>Yes</option><option value="false"' + (s.use_tls === false ? " selected" : "") + ">No</option></select></div></div>" +
    '<button class="btn primary sm" onclick="saveEmail()">💾 Save Email Setup</button></div>';
}
async function saveEmail() {
  await API.saveEmailSetup({
    smtp_host: $("esHost").value.trim(), smtp_port: parseInt($("esPort").value, 10) || 587,
    username: $("esUser").value.trim(), password: $("esPass").value,
    from_email: $("esFrom").value.trim(), use_tls: $("esTls").value === "true",
  });
  toast("Email setup saved.");
}

// ---- Dashboard / pipeline ----
const STAGES = ["Leads", "Quoted", "Negotiation", "Won"];
const STAGE_COL = ["var(--blue)", "var(--blue-deep)", "var(--warn)", "var(--good)"];
async function loadDashboard() {
  const [quotes, leads] = await Promise.all([API.quotes(), API.leads()]);
  renderKpis(quotes, leads);
  renderRecentQuotes(quotes);
  renderPipelineBars(leads);
  renderFxRows();
  renderKanban(leads);
}
function renderKpis(quotes, leads) {
  const open = quotes.filter((q) => q.status !== "won").length;
  const pipeline = leads.reduce((s, l) => s + (l.amount || 0), 0);
  const won = quotes.filter((q) => q.status === "won").length;
  const winRate = quotes.length ? Math.round(won / quotes.length * 100) : 0;
  const k = $("kpis");
  k.innerHTML =
    kpi("Open Quotes", open, "") +
    kpi("Pipeline Value", "₹" + (pipeline / 100000).toFixed(1) + "L", "") +
    kpi("Win Rate", winRate + "%", "") +
    '<div class="kpi"><div class="lab">Avg. Margin <span class="badge int" style="margin-left:4px" data-cost>MGR</span></div>' +
    (canSeeCost ? '<div class="val" data-cost>—</div>' : '<div class="val" data-nocost>🔒</div>') + "</div>";
  applyRoleVisibility();
}
const kpi = (lab, val) => '<div class="kpi"><div class="lab">' + lab + '</div><div class="val">' + val + "</div></div>";
function renderRecentQuotes(quotes) {
  const b = $("recentQuotes"); b.innerHTML = "";
  if (!quotes.length) { b.innerHTML = '<tr><td colspan="4"><div class="empty">No quotes yet — create one.</div></td></tr>'; return; }
  quotes.slice(0, 6).forEach((q) => {
    const tr = document.createElement("tr");
    tr.innerHTML = "<td>" + q.quote_no + "</td><td>" + q.customer_name + '</td><td class="num">₹' +
      Math.round(q.grand_total).toLocaleString("en-IN") + '</td><td><span class="st ' + q.status + '">' +
      q.status.charAt(0).toUpperCase() + q.status.slice(1) + "</span></td>";
    b.appendChild(tr);
  });
}
function renderPipelineBars(leads) {
  const totals = [0, 0, 0, 0];
  leads.forEach((l) => { if (l.stage >= 0 && l.stage < 4) totals[l.stage] += l.amount || 0; });
  const max = Math.max(1, ...totals);
  const wrap = $("pipelineBars"); wrap.innerHTML = "";
  STAGES.forEach((s, i) => {
    wrap.innerHTML += '<div class="mb-row"><div class="mb-top"><span>' + s + "</span><span>₹" +
      (totals[i] / 100000).toFixed(0) + 'L</span></div><div class="mb-track"><div class="mb-fill" style="width:' +
      Math.round(totals[i] / max * 100) + "%;background:" + STAGE_COL[i] + '"></div></div></div>';
  });
}
function renderFxRows() {
  const b = $("fxRows"); b.innerHTML = "";
  ["USD", "EUR"].forEach((c) => { if (FX[c]) b.innerHTML += "<tr><td>1 " + c + '</td><td class="num">₹ ' + FX[c].toFixed(2) + "</td></tr>"; });
}
function renderKanban(leads) {
  const k = $("kanban"); k.innerHTML = "";
  STAGES.forEach((st, si) => {
    const items = leads.filter((l) => l.stage === si);
    const col = document.createElement("div"); col.className = "kcol";
    col.innerHTML = '<h3><span><span class="dotline" style="background:' + STAGE_COL[si] + '"></span>' + st + '</span><span class="cnt">' + items.length + "</span></h3>";
    items.forEach((l) => {
      const c = document.createElement("div"); c.className = "kcard";
      c.innerHTML = "<b>" + l.name + '</b><div class="meta"><span>Owner: ' + (l.owner || "—") + '</span></div><div class="amt">₹ ' + (l.amount || 0).toLocaleString("en-IN") + "</div>";
      c.onclick = () => newQuote();
      col.appendChild(c);
    });
    k.appendChild(col);
  });
}

// ---- Start ----
if (API.getToken()) boot(); else showLogin();
