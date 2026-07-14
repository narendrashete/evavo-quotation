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
let BUILDER_LEADS = [], BUILDER_PROJECTS = [], BUILDER_CLIENTS = [];
let selectedClientId = null;  // resolved from the picked Lead, sent with the quote
let SETTINGS = { max_discount_pct: 12, gst_default_pct: 18, install_pct: 0.105,
                 local_freight: 0, intl_freight: 0, import_charge: 0, home_state: "27" };

// GST place-of-supply state codes (India), per the client's spec.
const STATE_CODES = [
  ["01", "Jammu & Kashmir"], ["02", "Himachal Pradesh"], ["03", "Punjab"],
  ["04", "Chandigarh"], ["05", "Uttarakhand"], ["06", "Haryana"], ["07", "Delhi"],
  ["08", "Rajasthan"], ["09", "Uttar Pradesh"], ["10", "Bihar"], ["11", "Sikkim"],
  ["12", "Arunachal Pradesh"], ["13", "Nagaland"], ["14", "Manipur"], ["15", "Mizoram"],
  ["16", "Tripura"], ["17", "Meghalaya"], ["18", "Assam"], ["19", "West Bengal"],
  ["20", "Jharkhand"], ["21", "Odisha"], ["22", "Chhattisgarh"], ["23", "Madhya Pradesh"],
  ["24", "Gujarat"], ["26", "Dadra & Nagar Haveli and Daman & Diu"], ["27", "Maharashtra"],
  ["28", "Andhra Pradesh"], ["29", "Karnataka"], ["30", "Goa"], ["31", "Lakshadweep"],
  ["32", "Kerala"], ["33", "Tamil Nadu"], ["34", "Puducherry"],
  ["35", "Andaman & Nicobar Islands"], ["36", "Telangana"], ["37", "Andhra Pradesh (New)"],
  ["38", "Ladakh"], ["97", "Other Territory"], ["99", "Centre Jurisdiction"],
];

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
  const cls = size === "sm" ? "thumb-sm" : (size === "lg" ? "thumb-lg" : "thumb-md");
  if (p.image) {
    return '<div class="thumb ' + cls + '"><img src="' + p.image +
      '" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:inherit"></div>';
  }
  const c = CATCOLOR[p.category] || ["#1a9fe0", "#0d6efd"];
  return '<div class="thumb ' + cls + '" style="background:linear-gradient(135deg,' +
    c[0] + ',' + c[1] + ')"><span class="tg">' + icon(p.category) + "</span></div>";
}

// ---- Auth / boot ----
window.onUnauthorized = () => showLogin();

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

  await Promise.all([loadFx(), loadTerms(), loadProducts(), loadBuilderLeads(), loadSettings()]);
  buildCurrencyOptions();
  buildCategoryOptions();
  buildPosOptions();
  applyBuilderDefaults();
  renderProducts();
  renderItems();
  recalc();
  updateCart();
  await loadDashboard();
}

// Settings drive the Quote Builder defaults (max discount, GST%, install%, freight).
// Managers/admins can read them; anyone else falls back to the hardcoded defaults.
async function loadSettings() {
  try { SETTINGS = await API.getSettings(); } catch (e) { /* sales role: keep defaults */ }
}
function buildPosOptions() {
  const sel = $("qPos"); if (!sel) return;
  sel.innerHTML = '<option value="">— select state —</option>';
  STATE_CODES.forEach(([code, name]) => {
    const o = document.createElement("option");
    o.value = code; o.textContent = code + " · " + name; sel.appendChild(o);
  });
  sel.value = SETTINGS.home_state || "27";
}
// Pre-fill the editable add-on/GST fields from the configured defaults.
function applyBuilderDefaults() {
  if ($("aInstallPct")) $("aInstallPct").value = (SETTINGS.install_pct * 100).toFixed(1).replace(/\.0$/, "");
  if ($("qGst")) $("qGst").value = SETTINGS.gst_default_pct;
  if ($("aLocalFreight")) $("aLocalFreight").value = SETTINGS.local_freight || 0;
  if ($("aIntlFreight")) $("aIntlFreight").value = SETTINGS.intl_freight || 0;
  if ($("aImport")) $("aImport").value = SETTINGS.import_charge || 0;
}

function applyRoleVisibility() {
  document.querySelectorAll("[data-cost]").forEach((e) => e.classList.toggle("hide", !canSeeCost));
  document.querySelectorAll("[data-nocost]").forEach((e) => e.classList.toggle("hide", canSeeCost));
  document.querySelectorAll("[data-admin]").forEach((e) => e.classList.toggle("hide", currentUser.role !== "admin"));
}

// ---- Data loads ----
async function loadProducts() { PRODUCTS = await API.products(); }
async function loadTerms() {
  TERMS = await API.terms();
  const sel = $("qTerms"); sel.innerHTML = "";
  TERMS.forEach((t) => { const o = document.createElement("option"); o.value = t.id; o.textContent = t.name; sel.appendChild(o); });
}
async function loadFx() {
  // API returns rows newest-first (effective_date DESC); keep only the first
  // (= latest) row per currency so an older dated rate can't overwrite a
  // newer one once multiple dated rows exist for the same currency.
  const rows = await API.fx();
  FX = { INR: 1 };
  rows.filter((r) => r.kind === "display").forEach((r) => {
    if (!(r.currency in FX)) FX[r.currency] = r.rate_to_inr;
  });
}
// Lead → Project → Client lookup for the Quote Builder's Lead selector.
async function loadBuilderLeads() {
  [BUILDER_LEADS, BUILDER_PROJECTS, BUILDER_CLIENTS] =
    await Promise.all([API.leads(), API.projects(), API.clients()]);
  const sel = $("qLead"); if (!sel) return;
  sel.innerHTML = '<option value="">— none, enter manually —</option>';
  BUILDER_LEADS.forEach((l) => {
    const p = BUILDER_PROJECTS.find((x) => x.id === l.project_id);
    const o = document.createElement("option");
    o.value = l.id; o.textContent = l.name + (p ? " — " + p.name : "");
    sel.appendChild(o);
  });
}
function onLeadSelected() {
  const id = parseInt($("qLead").value, 10);
  const info = $("qLeadInfo");
  if (!id) { selectedClientId = null; info.textContent = ""; return; }
  const lead = BUILDER_LEADS.find((l) => l.id === id);
  const project = lead && BUILDER_PROJECTS.find((p) => p.id === lead.project_id);
  const client = project && BUILDER_CLIENTS.find((c) => c.id === project.client_id);
  if (!project || !client) { selectedClientId = null; info.textContent = "This lead has no project/client linked yet."; return; }
  selectedClientId = client.id;
  $("qCustomer").value = client.name;
  $("qEmail").value = client.email || "";
  $("qAddress").value = lead.address || "";
  $("qMobile").value = lead.whatsapp_number || client.mobile || "";
  // Default place of supply from the client's GSTIN state prefix (first 2 digits).
  const posFromGstin = (client.gstin || "").trim().slice(0, 2);
  if (posFromGstin && STATE_CODES.some(([c]) => c === posFromGstin)) {
    $("qPos").value = posFromGstin;
  }
  recalc();
  info.textContent = "Project: " + project.name + " · Client: " + client.name +
    (client.city ? " · " + client.city : "") + " · GSTIN: " + (client.gstin || "—") +
    " · Phone: " + (client.phone || "—");
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
const titles = {
  dashboard: "Dashboard", pipeline: "Sales Pipeline", products: "Product Catalog",
  builder: "Quote Builder", preview: "Client Preview",
  clientsMaster: "Clients", projectsMaster: "Projects", leadsMaster: "Leads",
  termsMaster: "Terms", emailMaster: "Email Setup", settingsMaster: "Settings",
  usersMaster: "Users",
};
function goto(v) {
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === v));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".bottomnav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("tbTitle").textContent = titles[v] || "";
  if (v === "preview") renderPreview();
  if (v === "clientsMaster") renderClientsMaster();
  if (v === "projectsMaster") renderProjectsMaster();
  if (v === "leadsMaster") renderLeadsMaster();
  if (v === "termsMaster") renderTermsMaster();
  if (v === "emailMaster") renderEmailMaster();
  if (v === "settingsMaster") renderSettingsMaster();
  if (v === "usersMaster") renderUsersMaster();
  window.scrollTo(0, 0);
}
document.querySelectorAll(".nav-item,.bottomnav button").forEach((b) => {
  if (b.dataset.view) b.addEventListener("click", () => goto(b.dataset.view));
});
function newQuote() {
  LINES = []; currentQuoteId = null; lastPreview = null; selectedClientId = null;
  $("builderSub").textContent = "New draft";
  $("qLead").value = ""; $("qAddress").value = ""; $("qLeadInfo").textContent = "";
  $("aInstall").checked = true; $("aInstallAmt").value = ""; $("aPack").value = 0;
  if ($("qPos")) $("qPos").value = SETTINGS.home_state || "27";
  applyBuilderDefaults();
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
// Add/remove button for a product, rendered from its current cart membership so
// the picker, re-opens and live filtering all show a consistent state.
function pickAddBtnHtml(p) {
  const inCart = LINES.some((l) => l.pid === p.id);
  const cls = inCart ? "btn added sm" : "btn primary sm";
  const label = inCart ? "✓ Added" : "Add to cart";
  return '<button class="' + cls + '" id="pa' + p.id +
    '" onclick="pickToggle(' + p.id + ')">' + label + "</button>";
}
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
        '" value="1" readonly><button onclick="pq(' + p.id + ',1)">＋</button></div>' + pickAddBtnHtml(p) + '</div>';
      g.appendChild(d);
    });
}
function pq(id, delta) { const i = $("pq" + id); i.value = Math.max(1, (parseInt(i.value, 10) || 1) + delta); }
// ---- Product detail modal (image + description/specs + HSN/GST) ----
function showProductDetail(id) {
  const p = prod(id); if (!p) return;
  $("pdTitle").textContent = p.name;
  const gp = p.gst_pct != null ? p.gst_pct + "%" : "default";
  $("pdBody").innerHTML =
    '<div class="pd-grid">' + prodImg(p, "lg") +
    '<div class="pd-meta">' +
    '<div class="pd-row"><span>Model</span><b>' + esc(p.model_no || "—") + "</b></div>" +
    '<div class="pd-row"><span>Category</span><b>' + esc(p.category || "—") + "</b></div>" +
    '<div class="pd-row"><span>HSN Code</span><b>' + esc(p.hsn_code || "—") + "</b></div>" +
    '<div class="pd-row"><span>GST %</span><b>' + gp + "</b></div>" +
    '<div class="pd-row"><span>List price</span><b>₹ ' + Math.round(p.list_price).toLocaleString("en-IN") + "</b></div>" +
    "</div></div>" +
    '<div class="pd-desc"><b>Specifications</b><p>' + esc(p.description || "No description available.") + "</p></div>";
  $("pdetail").classList.add("open");
}
function closeProductDetail() { $("pdetail").classList.remove("open"); }
// Flip a single card's button to match cart state without re-rendering the grid
// (keeps scroll position).
function setPickBtn(id) {
  const btn = $("pa" + id); if (!btn) return;
  const inCart = LINES.some((l) => l.pid === id);
  btn.textContent = inCart ? "✓ Added" : "Add to cart";
  btn.className = inCart ? "btn added sm" : "btn primary sm";
}
function pickToggle(id) {
  const idx = LINES.findIndex((l) => l.pid === id);
  if (idx >= 0) {
    LINES.splice(idx, 1);                 // already in cart → remove it
  } else {
    const qty = parseInt($("pq" + id).value, 10) || 1;
    LINES.push({ pid: id, qty, disc: 0 });
  }
  setPickBtn(id);
  renderItems(); recalc(); updateCart();
}
function updateCart() {
  const n = LINES.length;
  if ($("cartCnt")) $("cartCnt").textContent = n + " item" + (n !== 1 ? "s" : "") + " in quote";
  if ($("addBadge")) $("addBadge").textContent = n;
}

// ---- Line items ----
function removeItem(idx) { LINES.splice(idx, 1); renderItems(); recalc(); updateCart(); }
// A line's effective GST% = the product's own rate, else the form-level default.
function lineGstPct(p) {
  if (p && p.gst_pct != null) return p.gst_pct;
  return parseFloat($("qGst") && $("qGst").value) || 0;
}
function renderItems() {
  const b = $("itemsBody"); b.innerHTML = "";
  if (!LINES.length) { b.innerHTML = '<tr><td colspan="12"><div class="empty">No items yet — click <b>🛍️ Add Products</b> to build the quote.</div></td></tr>'; return; }
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const tr = document.createElement("tr");
    const gp = lineGstPct(p);
    const costCells = canSeeCost
      ? '<td class="num cost-col" data-cost>' + fmt((p.final_c2e || 0) * ln.qty) + '</td><td class="num cost-col mcell" data-cost></td>'
      : '<td class="num cost-col hide" data-cost></td><td class="num cost-col mcell hide" data-cost></td>';
    tr.innerHTML = '<td><span style="cursor:pointer" title="View details" onclick="showProductDetail(' + p.id + ')">' + prodImg(p, "sm") + "</span></td>" +
      '<td class="pname"><b>' + p.name + "</b><br><small>" + (p.model_no || "") +
      '</small></td><td class="num">' + fmt(p.client_unit_price) +
      '</td><td class="num"><input type="number" min="1" value="' + ln.qty + '" onchange="upd(' + idx + ",'qty',this.value)\"></td>" +
      '<td class="num"><input type="number" min="0" max="100" value="' + ln.disc + '" onchange="upd(' + idx + ",'disc',this.value)\"></td>" +
      '<td class="num"><small>' + (p.hsn_code || "—") + '</small></td>' +
      '<td class="num">' + gp + '%</td><td class="num gstcell"></td>' +
      costCells + '<td class="num amtcell"></td><td><button class="del" onclick="removeItem(' + idx + ')">✕</button></td>';
    b.appendChild(tr);
  });
}
function upd(idx, field, val) {
  let v = parseFloat(val) || 0;
  // Hard discount cap: sales cannot exceed the configured maximum.
  let clamped = false;
  if (field === "disc" && !canSeeCost && v > SETTINGS.max_discount_pct) {
    v = SETTINGS.max_discount_pct;
    clamped = true;
    toast("Max discount is " + SETTINGS.max_discount_pct + "%. A manager can approve more.", true);
  }
  LINES[idx][field] = v;
  if (clamped) renderItems();
  recalc();
}

// ---- Recalc (instant client-side preview; server is authoritative on save) ----
// Mirrors the backend pricing engine: goods GST per line at the product/default
// rate, add-ons taxed at the default rate, split CGST/SGST (intra-state) or IGST.
function recalc() {
  let sub = 0, gross = 0, cost = 0, goodsGst = 0;
  const gstDefault = parseFloat($("qGst") && $("qGst").value) || 0;
  const rows = document.querySelectorAll("#itemsBody tr");
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const lineGross = p.client_unit_price * ln.qty;
    const lineNet = lineGross * (1 - ln.disc / 100);
    const lineCost = (p.final_c2e || 0) * ln.qty;
    const gp = lineGstPct(p);
    const gstAmt = lineNet * gp / 100;
    sub += lineNet; gross += lineGross; cost += lineCost; goodsGst += gstAmt;
    if (rows[idx]) {
      const ac = rows[idx].querySelector(".amtcell"); if (ac) ac.textContent = fmt(lineNet);
      const gc = rows[idx].querySelector(".gstcell"); if (gc) gc.textContent = fmt(gstAmt);
      const mc = rows[idx].querySelector(".mcell");
      if (mc && canSeeCost) { const m = lineNet - lineCost; const mp = lineNet > 0 ? (m / lineNet * 100) : 0; mc.innerHTML = '<span class="' + (m >= 0 ? "mpos" : "mneg") + '">' + fmt(m) + " · " + mp.toFixed(0) + "%</span>"; }
    }
  });
  const discGiven = gross - sub;
  const instPct = parseFloat($("aInstallPct").value) || 0;
  const instOverride = $("aInstallAmt").value.trim();
  const install = !$("aInstall").checked ? 0
    : (instOverride !== "" ? (parseFloat(instOverride) || 0) : sub * instPct / 100);
  const pack = parseFloat($("aPack").value) || 0;
  const localF = parseFloat($("aLocalFreight").value) || 0;
  const intlF = parseFloat($("aIntlFreight").value) || 0;
  const imp = parseFloat($("aImport").value) || 0;
  const freight = localF + intlF + imp;
  const addonBase = install + pack + freight;
  const grand = sub + addonBase;                 // pre-tax
  const taxable = grand;                          // GST base = goods + install + freight
  const gstTotal = goodsGst + addonBase * gstDefault / 100;
  const intra = ($("qPos").value || "") === (SETTINGS.home_state || "27");
  const cgst = intra ? gstTotal / 2 : 0;
  const sgst = intra ? gstTotal / 2 : 0;
  const igst = intra ? 0 : gstTotal;
  const finalPayable = taxable + gstTotal;

  $("sSub").textContent = fmt(sub);
  $("sDisc").textContent = "– " + fmt(discGiven);
  $("sInstall").textContent = fmt(install);
  $("sTaxable").textContent = fmt(taxable);
  $("sGrand").textContent = fmt(grand);
  $("sFinal").textContent = fmt(finalPayable);
  $("rowCgst").classList.toggle("hide", !intra);
  $("rowSgst").classList.toggle("hide", !intra);
  $("rowIgst").classList.toggle("hide", intra);
  $("sCgst").textContent = fmt(cgst);
  $("sSgst").textContent = fmt(sgst);
  $("sIgst").textContent = fmt(igst);
  if (canSeeCost) {
    const totMargin = sub - cost;
    $("mCost").textContent = fmt(cost);
    $("mMargin").textContent = fmt(totMargin);
    $("mPct").textContent = (sub > 0 ? (totMargin / sub * 100) : 0).toFixed(1) + "%";
  }
  const overallDisc = gross > 0 ? (discGiven / gross * 100) : 0;
  const anyHigh = LINES.some((l) => l.disc > 15);
  $("approvalBox").classList.toggle("hide", !(overallDisc > 12 || anyHigh));
  window._Q = { sub, install, pack, freight, grand, taxable, gstTotal,
                cgst, sgst, igst, intra, finalPayable };
}

// ---- Save quote (server computes authoritative totals) ----
async function saveQuote() {
  if (!LINES.length) { toast("Add at least one product first.", true); return; }
  $("saveBtn").disabled = true;
  try {
    const payload = {
      customer_name: $("qCustomer").value.trim(),
      customer_email: $("qEmail").value.trim() || null,
      customer_address: $("qAddress").value.trim() || null,
      customer_mobile: $("qMobile").value.trim() || null,
      client_id: selectedClientId,
      currency: cur(),
      terms_template_id: parseInt($("qTerms").value, 10) || null,
      install_enabled: $("aInstall").checked,
      install_pct: (parseFloat($("aInstallPct").value) || 0) / 100,
      install_amount: $("aInstallAmt").value.trim() !== "" ? (parseFloat($("aInstallAmt").value) || 0) : null,
      packaging: parseFloat($("aPack").value) || 0,
      local_freight: parseFloat($("aLocalFreight").value) || 0,
      intl_freight: parseFloat($("aIntlFreight").value) || 0,
      import_charge: parseFloat($("aImport").value) || 0,
      place_of_supply: $("qPos").value || null,
      gst_default_pct: parseFloat($("qGst").value) || 0,
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
  const addr = $("qAddress").value.trim();
  const mobile = $("qMobile").value.trim();
  $("pvBillTo").innerHTML = "<br>" + esc($("qCustomer").value) + "<br>" + esc($("qEmail").value || "") +
    (mobile ? "<br>" + esc(mobile) : "") +
    (addr ? "<br>" + esc(addr).replace(/\n/g, "<br>") : "");
  $("pvCur").textContent = cur() + " (" + SYM[cur()] + ")";

  // Prefer the server's client-safe payload after a save; else compute locally.
  const b = $("pvBody"); b.innerHTML = "";
  if (lastPreview && currentQuoteId) {
    $("pvNo").textContent = lastPreview.quote_no;
    $("pvDate").textContent = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    lastPreview.lines.forEach((ln, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + (i + 1) + "</td><td>" + ln.name + "<br><span style='color:#7a8a99;font-size:11px'>" + (ln.model_no || "") +
        "</span></td><td class=\"num\"><small>" + (ln.hsn_code || "—") + "</small></td><td class=\"num\">" + fmt(ln.unit_price) +
        '</td><td class="num">' + ln.qty + '</td><td class="num">' + (ln.gst_pct || 0) + '%</td><td class="num">' + fmt(ln.line_net) + "</td>";
      b.appendChild(tr);
    });
    const t = lastPreview.totals;
    $("pvSub").textContent = fmt(t.subtotal_net);
    $("pvInstall").textContent = fmt(t.installation);
    $("pvPack").textContent = fmt(lastPreview.packaging || 0);
    $("pvFreight").textContent = fmt(lastPreview.freight || 0);
    $("pvTaxable").textContent = fmt(t.taxable_amount);
    setPreviewTax(t.is_intra_state, t.cgst, t.sgst, t.igst);
    $("pvGrand").textContent = fmt(t.final_payable);
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
        "</span></div></div></td><td class=\"num\"><small>" + (p.hsn_code || "—") + "</small></td><td class=\"num\">" + fmt(p.client_unit_price) +
        '</td><td class="num">' + ln.qty + '</td><td class="num">' + lineGstPct(p) + '%</td><td class="num">' + fmt(net) + "</td>";
      b.appendChild(tr);
    });
    const Q = window._Q || {};
    $("pvSub").textContent = fmt(Q.sub || 0);
    $("pvInstall").textContent = fmt(Q.install || 0);
    $("pvPack").textContent = fmt(Q.pack || 0);
    $("pvFreight").textContent = fmt(Q.freight || 0);
    $("pvTaxable").textContent = fmt(Q.taxable || 0);
    setPreviewTax(Q.intra, Q.cgst || 0, Q.sgst || 0, Q.igst || 0);
    $("pvGrand").textContent = fmt(Q.finalPayable || 0);
  }
}
function setPreviewTax(intra, cgst, sgst, igst) {
  $("pvRowCgst").classList.toggle("hide", !intra);
  $("pvRowSgst").classList.toggle("hide", !intra);
  $("pvRowIgst").classList.toggle("hide", !!intra);
  $("pvCgst").textContent = fmt(cgst);
  $("pvSgst").textContent = fmt(sgst);
  $("pvIgst").textContent = fmt(igst);
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
async function whatsappCurrent() {
  if (!requireSaved()) return;
  try {
    const r = await API.sendWhatsapp(currentQuoteId);
    window.open(r.url, "_blank");
    toast("WhatsApp opened for " + r.phone);
  } catch (e) { toast("WhatsApp failed: " + e.message, true); }
}
async function openQuote(id) {
  try {
    const q = await API.getQuote(id);
    lastPreview = await API.previewQuote(id);
    currentQuoteId = q.id;
    LINES = q.lines.map((l) => ({ pid: l.product_id, qty: l.qty, disc: l.line_disc }));
    $("qCustomer").value = q.customer_name || "";
    $("qEmail").value = q.customer_email || "";
    $("qAddress").value = q.customer_address || "";
    $("qMobile").value = q.customer_mobile || "";
    $("qLead").value = ""; $("qLeadInfo").textContent = ""; selectedClientId = null;
    if (q.terms_template_id != null) $("qTerms").value = q.terms_template_id;
    if (q.currency && $("curSel").querySelector('option[value="' + q.currency + '"]')) $("curSel").value = q.currency;
    // Restore GST / add-on / freight fields
    $("aInstall").checked = q.install_enabled !== false;
    $("aInstallPct").value = ((q.install_pct || 0.105) * 100).toFixed(1).replace(/\.0$/, "");
    $("aInstallAmt").value = q.install_amount != null ? q.install_amount : "";
    $("aPack").value = q.packaging || 0;
    $("aLocalFreight").value = q.local_freight || 0;
    $("aIntlFreight").value = q.intl_freight || 0;
    $("aImport").value = q.import_charge || 0;
    $("qPos").value = q.place_of_supply || "";
    if (q.gst_default_pct) $("qGst").value = q.gst_default_pct;
    $("builderSub").textContent = q.quote_no + " · " + q.status.charAt(0).toUpperCase() + q.status.slice(1);
    renderItems(); recalc(); updateCart();
    goto("preview");
    toast("Opened " + q.quote_no);
  } catch (e) { toast("Open failed: " + e.message, true); }
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
// Clients, Projects and Leads are now separate pages with a real hierarchy:
// a Client has many Projects, a Project has many Leads (Lead.client_id is
// auto-derived server-side from its Project). Each list reuses an inline
// Add/Edit form (editing*Id tracks which row, if any, is being edited).
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m])));

// --- Clients ---
let editingClientId = null;
async function renderClientsMaster() {
  const c = $("clientsMasterContent");
  c.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const rows = await API.clients();
    const editing = editingClientId != null;
    c.innerHTML =
      '<div class="card pad" style="margin-bottom:16px"><div class="section-title">' + (editing ? "Edit Client" : "Add Client") + '</div><div class="f2">' +
      '<div class="field"><label>Name</label><input id="ncName"></div>' +
      '<div class="field"><label>Email</label><input id="ncEmail"></div>' +
      '<div class="field"><label>Phone</label><input id="ncPhone"></div>' +
      '<div class="field"><label>Mobile (WhatsApp)</label><input id="ncMobile"></div>' +
      '<div class="field"><label>City</label><input id="ncCity"></div></div>' +
      '<button class="btn primary sm" onclick="saveClient()">' + (editing ? "💾 Update Client" : "＋ Add Client") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelClientEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Clients (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Mobile</th><th>City</th><th></th>' +
      (canSeeCost ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.phone) + "</td><td>" + esc(r.mobile) + "</td><td>" + esc(r.city) +
        '</td><td><button class="btn ghost sm" onclick="editClient(' + r.id + ')">Edit</button></td>' +
        (canSeeCost ? '<td><button class="del" onclick="delClient(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
        : '<tr><td colspan="7"><div class="empty">No clients yet.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingClientId);
      if (r) { $("ncName").value = r.name || ""; $("ncEmail").value = r.email || ""; $("ncPhone").value = r.phone || ""; $("ncMobile").value = r.mobile || ""; $("ncCity").value = r.city || ""; }
    }
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function saveClient() {
  const name = $("ncName").value.trim();
  if (!name) { toast("Client name is required.", true); return; }
  const data = { name, email: $("ncEmail").value.trim() || null, phone: $("ncPhone").value.trim() || null, mobile: $("ncMobile").value.trim() || null, city: $("ncCity").value.trim() || null };
  try {
    if (editingClientId != null) { await API.updateClient(editingClientId, data); toast("Client updated."); editingClientId = null; }
    else { await API.createClient(data); toast("Client added."); }
    renderClientsMaster();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
function editClient(id) { editingClientId = id; renderClientsMaster(); }
function cancelClientEdit() { editingClientId = null; renderClientsMaster(); }
async function delClient(id) {
  try { await API.deleteClient(id); toast("Client deleted."); renderClientsMaster(); }
  catch (e) { toast("Delete failed: " + e.message, true); }
}

// --- Projects ---
let editingProjectId = null;
async function renderProjectsMaster() {
  const c = $("projectsMasterContent");
  c.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const [rows, clients] = await Promise.all([API.projects(), API.clients()]);
    const clientName = (id) => { const cl = clients.find((x) => x.id === id); return cl ? cl.name : "—"; };
    const editing = editingProjectId != null;
    const clientOptions = clients.map((cl) => '<option value="' + cl.id + '">' + esc(cl.name) + "</option>").join("");
    c.innerHTML =
      '<div class="card pad" style="margin-bottom:16px"><div class="section-title">' + (editing ? "Edit Project" : "Add Project") + '</div><div class="f2">' +
      '<div class="field"><label>Client</label><select id="npClient"><option value="">Select a client…</option>' + clientOptions + "</select></div>" +
      '<div class="field"><label>Project Name</label><input id="npName"></div>' +
      '<div class="field"><label>City</label><input id="npCity"></div></div>' +
      '<button class="btn primary sm" onclick="saveProject()">' + (editing ? "💾 Update Project" : "＋ Add Project") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelProjectEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Projects (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Client</th><th>Project</th><th>City</th><th></th>' +
      (canSeeCost ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(clientName(r.client_id)) + "</td><td>" + esc(r.name) + "</td><td>" + esc(r.city) +
        '</td><td><button class="btn ghost sm" onclick="editProject(' + r.id + ')">Edit</button></td>' +
        (canSeeCost ? '<td><button class="del" onclick="delProject(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
        : '<tr><td colspan="5"><div class="empty">No projects yet — add a client first.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingProjectId);
      if (r) { $("npClient").value = r.client_id || ""; $("npName").value = r.name || ""; $("npCity").value = r.city || ""; }
    }
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function saveProject() {
  const name = $("npName").value.trim();
  const clientId = parseInt($("npClient").value, 10);
  if (!name) { toast("Project name is required.", true); return; }
  if (!clientId) { toast("Select a client.", true); return; }
  const data = { name, client_id: clientId, city: $("npCity").value.trim() || null };
  try {
    if (editingProjectId != null) { await API.updateProject(editingProjectId, data); toast("Project updated."); editingProjectId = null; }
    else { await API.createProject(data); toast("Project added."); }
    renderProjectsMaster();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
function editProject(id) { editingProjectId = id; renderProjectsMaster(); }
function cancelProjectEdit() { editingProjectId = null; renderProjectsMaster(); }
async function delProject(id) {
  try { await API.deleteProject(id); toast("Project deleted."); renderProjectsMaster(); }
  catch (e) { toast("Delete failed: " + e.message, true); }
}

// --- Leads (master data-entry; the Sales Pipeline Kanban is a separate view
// over the same Lead rows and is unaffected by this) ---
let editingLeadId = null;
function leadClientLabel(projects, clients, projectId) {
  const pr = projects.find((p) => p.id === projectId);
  if (!pr) return "—";
  const cl = clients.find((x) => x.id === pr.client_id);
  return cl ? cl.name : "—";
}
function updateLeadClientLabel() {
  const pid = parseInt($("nlProject").value, 10);
  $("nlClient").value = pid ? leadClientLabel(window._leadProjects || [], window._leadClients || [], pid) : "—";
}
async function renderLeadsMaster() {
  const c = $("leadsMasterContent");
  c.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const [rows, projects, clients] = await Promise.all([API.leads(), API.projects(), API.clients()]);
    window._leadProjects = projects; window._leadClients = clients;
    const projectName = (id) => { const p = projects.find((x) => x.id === id); return p ? p.name : "—"; };
    const stageName = ["Leads", "Quoted", "Negotiation", "Won"];
    const editing = editingLeadId != null;
    const projectOptions = projects.map((p) => '<option value="' + p.id + '">' + esc(p.name) + "</option>").join("");
    c.innerHTML =
      '<div class="card pad" style="margin-bottom:16px"><div class="section-title">' + (editing ? "Edit Lead" : "Add Lead") + '</div><div class="f2">' +
      '<div class="field"><label>Project</label><select id="nlProject" onchange="updateLeadClientLabel()"><option value="">Select a project…</option>' + projectOptions + "</select></div>" +
      '<div class="field"><label>Client</label><input id="nlClient" disabled value="—"></div>' +
      '<div class="field"><label>Name</label><input id="nlName"></div>' +
      '<div class="field"><label>Owner</label><input id="nlOwner"></div>' +
      '<div class="field"><label>Stage</label><select id="nlStage"><option value="0">Leads</option><option value="1">Quoted</option><option value="2">Negotiation</option><option value="3">Won</option></select></div>' +
      '<div class="field"><label>Amount (₹)</label><input id="nlAmount" type="number" value="0"></div>' +
      '<div class="field" style="grid-column:1/-1"><label>Address (site/installation — may differ from the client\'s registered address)</label><textarea id="nlAddress" rows="2"></textarea></div>' +
      '<div class="field" style="grid-column:1/-1"><label>WhatsApp number (site contact — may differ from the client\'s registered mobile)</label><input id="nlWhatsapp"></div></div>' +
      '<button class="btn primary sm" onclick="saveLead()">' + (editing ? "💾 Update Lead" : "＋ Add Lead") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelLeadEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Leads (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Project</th><th>Client</th><th>Name</th><th>Owner</th><th>Stage</th><th class="num">Amount</th><th></th>' +
      (canSeeCost ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(projectName(r.project_id)) + "</td><td>" + esc(leadClientLabel(projects, clients, r.project_id)) +
        "</td><td>" + esc(r.name) + "</td><td>" + esc(r.owner) + "</td><td>" + stageName[r.stage] +
        '</td><td class="num">₹' + (r.amount || 0).toLocaleString("en-IN") + '</td><td><button class="btn ghost sm" onclick="editLead(' + r.id + ')">Edit</button></td>' +
        (canSeeCost ? '<td><button class="del" onclick="delLead(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
        : '<tr><td colspan="8"><div class="empty">No leads yet — add a project first.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingLeadId);
      if (r) {
        $("nlProject").value = r.project_id || "";
        $("nlName").value = r.name || ""; $("nlOwner").value = r.owner || "";
        $("nlStage").value = r.stage; $("nlAmount").value = r.amount || 0;
        $("nlAddress").value = r.address || "";
        $("nlWhatsapp").value = r.whatsapp_number || "";
      }
    }
    updateLeadClientLabel();
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function saveLead() {
  const name = $("nlName").value.trim();
  const projectId = parseInt($("nlProject").value, 10);
  if (!name) { toast("Lead name is required.", true); return; }
  if (!projectId) { toast("Select a project.", true); return; }
  const data = { name, owner: $("nlOwner").value.trim() || null, stage: parseInt($("nlStage").value, 10), amount: parseFloat($("nlAmount").value) || 0, project_id: projectId, address: $("nlAddress").value.trim() || null, whatsapp_number: $("nlWhatsapp").value.trim() || null };
  try {
    if (editingLeadId != null) { await API.updateLead(editingLeadId, data); toast("Lead updated."); editingLeadId = null; }
    else { await API.createLead(data); toast("Lead added."); }
    renderLeadsMaster(); loadDashboard();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
function editLead(id) { editingLeadId = id; renderLeadsMaster(); }
function cancelLeadEdit() { editingLeadId = null; renderLeadsMaster(); }
async function delLead(id) {
  try { await API.deleteLead(id); toast("Lead deleted."); renderLeadsMaster(); loadDashboard(); }
  catch (e) { toast("Delete failed: " + e.message, true); }
}

// --- Terms ---
async function renderTermsMaster() {
  const c = $("termsMasterContent");
  c.innerHTML = '<div class="empty">Loading…</div>';
  try {
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
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function addTerms() {
  const name = $("ntName").value.trim();
  if (!name) { toast("Template name required.", true); return; }
  await API.createTerms({ name, kind: $("ntKind").value, body: $("ntBody").value });
  toast("Template added."); renderTermsMaster(); loadTerms();
}
async function saveTerms(id, name, kind) {
  await API.updateTerms(id, { name, kind, body: $("tb" + id).value });
  toast("Template saved."); loadTerms();
}

// --- Email Setup ---
async function renderEmailMaster() {
  const c = $("emailMasterContent");
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

// --- System Settings (read: manager/admin; save: admin only) ---
async function renderSettingsMaster() {
  const c = $("settingsMasterContent");
  if (!canSeeCost) { c.innerHTML = '<div class="empty">Settings are manager/admin-only.</div>'; return; }
  let s = SETTINGS;
  try { s = await API.getSettings(); SETTINGS = s; } catch (e) { /* keep cached */ }
  const isAdmin = currentUser.role === "admin";
  const stateOpts = STATE_CODES.map(([code, name]) =>
    '<option value="' + code + '"' + (s.home_state === code ? " selected" : "") + ">" + code + " · " + esc(name) + "</option>").join("");
  c.innerHTML =
    '<div class="card pad"><div class="section-title">Quote Builder Defaults</div><div class="f2">' +
    '<div class="field"><label>Max discount % (hard cap)' + (isAdmin ? "" : " — admin only") + '</label><input id="stMaxDisc" type="number" step="0.5" value="' + (s.max_discount_pct) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Default GST %</label><input id="stGst" type="number" step="0.5" value="' + (s.gst_default_pct) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Installation % </label><input id="stInstall" type="number" step="0.5" value="' + (s.install_pct * 100) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Home state (place of supply)</label><select id="stHome"' + (isAdmin ? "" : " disabled") + ">" + stateOpts + "</select></div>" +
    '<div class="field"><label>Local freight (default)</label><input id="stLocal" type="number" value="' + (s.local_freight) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>International freight (default)</label><input id="stIntl" type="number" value="' + (s.intl_freight) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Import charges (default)</label><input id="stImport" type="number" value="' + (s.import_charge) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    "</div>" +
    (isAdmin ? '<button class="btn primary sm" onclick="saveSettings()">💾 Save Settings</button>'
             : '<div class="empty" style="text-align:left">Only an admin can change these defaults.</div>') +
    "</div>";
}
async function saveSettings() {
  try {
    SETTINGS = await API.saveSettings({
      max_discount_pct: parseFloat($("stMaxDisc").value) || 0,
      gst_default_pct: parseFloat($("stGst").value) || 0,
      install_pct: (parseFloat($("stInstall").value) || 0) / 100,
      local_freight: parseFloat($("stLocal").value) || 0,
      intl_freight: parseFloat($("stIntl").value) || 0,
      import_charge: parseFloat($("stImport").value) || 0,
      home_state: $("stHome").value,
    });
    toast("Settings saved.");
  } catch (e) { toast("Save failed: " + e.message, true); }
}

// --- Users (admin-only) ---
let editingUserId = null;
async function renderUsersMaster() {
  const c = $("usersMasterContent");
  c.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const rows = await API.users();
    const editing = editingUserId != null;
    c.innerHTML =
      '<div class="card pad" style="margin-bottom:16px"><div class="section-title">' + (editing ? "Edit User" : "Add User") + '</div><div class="f2">' +
      '<div class="field"><label>Name</label><input id="nuName"></div>' +
      '<div class="field"><label>Email</label><input id="nuEmail"></div>' +
      '<div class="field"><label>Password</label><input id="nuPassword" type="password" placeholder="' + (editing ? "(unchanged)" : "min. 6 characters") + '"></div>' +
      '<div class="field"><label>Role</label><select id="nuRole"><option value="sales">Sales</option><option value="manager">Manager</option><option value="admin">Admin</option></select></div>' +
      '<div class="field"><label>Branch</label><input id="nuBranch"></div>' +
      '<div class="field"><label>Active</label><select id="nuActive"><option value="true">Yes</option><option value="false">No</option></select></div></div>' +
      '<button class="btn primary sm" onclick="saveUser()">' + (editing ? "💾 Update User" : "＋ Add User") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelUserEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Users (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Branch</th><th>Active</th><th></th><th></th></tr></thead><tbody>' +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.role) +
        "</td><td>" + esc(r.branch) + "</td><td>" + (r.is_active ? "Yes" : "No") +
        '</td><td><button class="btn ghost sm" onclick="editUser(' + r.id + ')">Edit</button></td>' +
        '<td><button class="del" onclick="delUser(' + r.id + ')">✕</button></td></tr>').join("")
        : '<tr><td colspan="7"><div class="empty">No users yet.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingUserId);
      if (r) {
        $("nuName").value = r.name || ""; $("nuEmail").value = r.email || "";
        $("nuRole").value = r.role; $("nuBranch").value = r.branch || "";
        $("nuActive").value = r.is_active ? "true" : "false";
      }
    }
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function saveUser() {
  const name = $("nuName").value.trim();
  const email = $("nuEmail").value.trim();
  const password = $("nuPassword").value;
  if (!name) { toast("Name is required.", true); return; }
  if (!email) { toast("Email is required.", true); return; }
  if (editingUserId == null && password.length < 6) { toast("Password must be at least 6 characters.", true); return; }
  const data = {
    name, email, role: $("nuRole").value, branch: $("nuBranch").value.trim() || null,
    is_active: $("nuActive").value === "true", password: password || null,
  };
  try {
    if (editingUserId != null) { await API.updateUser(editingUserId, data); toast("User updated."); editingUserId = null; }
    else { await API.createUser(data); toast("User added."); }
    renderUsersMaster();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
function editUser(id) { editingUserId = id; renderUsersMaster(); }
function cancelUserEdit() { editingUserId = null; renderUsersMaster(); }
async function delUser(id) {
  try { await API.deleteUser(id); toast("User deleted."); renderUsersMaster(); }
  catch (e) { toast("Delete failed: " + e.message, true); }
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
    tr.style.cursor = "pointer";
    tr.title = "Open " + q.quote_no;
    tr.innerHTML = "<td>" + q.quote_no + "</td><td>" + q.customer_name + '</td><td class="num">₹' +
      Math.round(q.grand_total).toLocaleString("en-IN") + '</td><td><span class="st ' + q.status + '">' +
      q.status.charAt(0).toUpperCase() + q.status.slice(1) + "</span></td>";
    tr.onclick = () => openQuote(q.id);
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
async function refreshLiveRates() {
  const btn = $("btnRefreshFx");
  btn.disabled = true; const old = btn.textContent; btn.textContent = "Refreshing…";
  try {
    await API.refreshFx();
    await loadFx();
    renderFxRows();
    toast("Live FX rates refreshed.");
  } catch (e) { toast("Refresh failed: " + e.message, true); }
  finally { btn.disabled = false; btn.textContent = old; }
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
