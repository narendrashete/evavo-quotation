/* Evavo Quotation Platform — front-end app logic, wired to the FastAPI backend.
 * Cost/margin fields only exist in API responses for manager/admin, so the UI
 * simply renders whatever the server returns (defense in depth on top of the
 * server-side gating). */

// ---- State ----
let currentUser = null;
let canSeeCost = false;
let canDelete = false;  // manager/admin, or a sales user granted delete rights by an admin
let PRODUCTS = [];          // from /api/products (cost fields present only for managers)
let LINES = [];             // [{pid, qty, disc}]
let FX = { INR: 1 };        // display rate_to_inr by currency
const SYM = { INR: "₹", USD: "$", EUR: "€" };
let TERMS = [];
let currentQuoteId = null;
let currentQuoteStatus = null;  // status of the loaded quote — non-"draft" locks editing
let lastPreview = null;     // server client-preview payload after save
let BUILDER_LEADS = [], BUILDER_PROJECTS = [], BUILDER_CLIENTS = [];
let selectedClientId = null;  // resolved from the picked Lead, sent with the quote
let SETTINGS = { max_discount_pct: 12, gst_default_pct: 18, install_pct: 0.105,
                 install_dry_pct: 0.105, install_wet_pct: 0.105,
                 local_freight: 0, intl_freight: 0, import_charge: 0, home_state: "27" };

// A line's Unit Price is the product's list price, and the standard offer is
// that price less this discount — mirrors DEFAULT_LINE_DISC_PCT in pricing.py.
const DEFAULT_LINE_DISC_PCT = 10;
// Work-area categories, which pick the installation rate (see Settings).
const AREA_CATEGORIES = ["Dry Area", "Wet Area", "Others"];

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
function toast(msg, isErr, isOk) {
  const t = $("toast"); t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : isOk ? " ok" : "");
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
  canDelete = canSeeCost || !!currentUser.can_delete;
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
  if ($("qGst")) $("qGst").value = SETTINGS.gst_default_pct;
  if ($("aLocalFreight")) $("aLocalFreight").value = SETTINGS.local_freight || 0;
  if ($("aIntlFreight")) $("aIntlFreight").value = SETTINGS.intl_freight || 0;
  if ($("aImport")) $("aImport").value = SETTINGS.import_charge || 0;
  INSTALL_RATES = { dry: pctOf(SETTINGS.install_dry_pct), wet: pctOf(SETTINGS.install_wet_pct),
                    other: pctOf(SETTINGS.install_pct) };
  showInstallRates();
}
// Installation percentages in force for the quote being built — from Settings
// for a new quote, or restored from the quote's own snapshot when one is opened.
let INSTALL_RATES = { dry: 10.5, wet: 10.5, other: 10.5 };
const pctOf = (fraction) => Math.round((fraction || 0) * 1000) / 10;   // 0.105 -> 10.5
function showInstallRates() {
  if ($("lblDryPct")) $("lblDryPct").textContent = INSTALL_RATES.dry;
  if ($("lblWetPct")) $("lblWetPct").textContent = INSTALL_RATES.wet;
  if ($("lblOtherPct")) $("lblOtherPct").textContent = INSTALL_RATES.other;
}
// Installation rate for a product, by its work area.
function installPctFor(p) {
  const area = p && p.area_category;
  if (area === "Dry Area") return INSTALL_RATES.dry;
  if (area === "Wet Area") return INSTALL_RATES.wet;
  return INSTALL_RATES.other;
}

function applyRoleVisibility() {
  document.querySelectorAll("[data-cost]").forEach((e) => e.classList.toggle("hide", !canSeeCost));
  document.querySelectorAll("[data-nocost]").forEach((e) => e.classList.toggle("hide", canSeeCost));
  document.querySelectorAll("[data-admin]").forEach((e) => e.classList.toggle("hide", currentUser.role !== "admin"));
  document.querySelectorAll("[data-delete]").forEach((e) => e.classList.toggle("hide", !canDelete));
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
// Re-fetched on every entry into the Builder (and after Lead master edits) so
// a lead added elsewhere shows up here without a full page refresh.
async function loadBuilderLeads() {
  [BUILDER_LEADS, BUILDER_PROJECTS, BUILDER_CLIENTS] =
    await Promise.all([API.leads(), API.projects(), API.clients()]);
  const sel = $("qLead"); if (!sel) return;
  const keep = sel.value;   // preserve the current selection across the rebuild
  sel.innerHTML = '<option value="">— none, enter manually —</option>';
  BUILDER_LEADS.forEach((l) => {
    const p = BUILDER_PROJECTS.find((x) => x.id === l.project_id);
    const o = document.createElement("option");
    o.value = l.id; o.textContent = l.name + (p ? " — " + p.name : "");
    sel.appendChild(o);
  });
  if (keep && sel.querySelector('option[value="' + keep + '"]')) sel.value = keep;
}
function leadInfoText(lead, project, client) {
  return "Project: " + project.name + " · Company: " + client.name +
    (client.city ? " · " + client.city : "") + " · GSTIN: " + (client.gstin || "—") +
    " · Handled by: " + (lead.owner || "—") +
    (lead.requirement ? " · Requirement: " + clip(lead.requirement, 80) : "");
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
  // The lead's own contact details win over the company's registered ones.
  $("qEmail").value = lead.email || client.email || "";
  $("qAddress").value = lead.address || "";
  $("qMobile").value = lead.whatsapp_number || client.mobile || "";
  // Default place of supply from the client's GSTIN state prefix (first 2 digits).
  const posFromGstin = (client.gstin || "").trim().slice(0, 2);
  if (posFromGstin && STATE_CODES.some(([c]) => c === posFromGstin)) {
    $("qPos").value = posFromGstin;
  }
  recalc();
  info.textContent = leadInfoText(lead, project, client);
}
// Re-select a quote's linked Lead in the dropdown when opening/editing it,
// without overwriting the customer fields already restored from the quote's
// own snapshot (the lead/client's live data may have moved on since).
function selectLeadForBuilder(leadId) {
  const info = $("qLeadInfo");
  if (!leadId) { $("qLead").value = ""; info.textContent = ""; return; }
  const lead = BUILDER_LEADS.find((l) => l.id === leadId);
  if (!lead) { $("qLead").value = ""; info.textContent = ""; return; }
  $("qLead").value = leadId;
  const project = BUILDER_PROJECTS.find((p) => p.id === lead.project_id);
  const client = project && BUILDER_CLIENTS.find((c) => c.id === project.client_id);
  info.textContent = (project && client) ? leadInfoText(lead, project, client) : "";
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
  const list = $("npdCategoryList");
  if (list) list.innerHTML = cats.map((c) => '<option value="' + esc(c) + '">').join("");
}

// ---- Navigation ----
const titles = {
  dashboard: "Dashboard", pipeline: "Sales Pipeline", products: "Product Catalog",
  builder: "Quote Builder", preview: "Client Preview",
  clientsMaster: "Clients", projectsMaster: "Projects", leadsMaster: "Leads",
  termsMaster: "Terms", emailMaster: "Email Setup", settingsMaster: "Settings",
  usersMaster: "Users",
};
// Re-fetch products/leads/settings from the server — called whenever the user
// enters the Builder (or opens the product picker) so a lead/product/setting
// added or edited elsewhere shows up without a full page refresh.
async function refreshBuilderMasters() {
  try {
    await Promise.all([loadProducts(), loadBuilderLeads(), loadSettings()]);
    buildCategoryOptions();
    renderProducts();
    recalc();
  } catch (e) { /* best-effort refresh; keep whatever's already loaded on failure */ }
}
function goto(v) {
  document.querySelectorAll(".view").forEach((s) => s.classList.toggle("active", s.id === v));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  document.querySelectorAll(".bottomnav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("tbTitle").textContent = titles[v] || "";
  if (v === "builder") refreshBuilderMasters();
  if (v === "preview") { renderPreview(); renderHistory(); }
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
  LINES = []; currentQuoteId = null; currentQuoteStatus = null; lastPreview = null; selectedClientId = null;
  $("builderSub").textContent = "New draft";
  $("qLead").value = ""; $("qAddress").value = ""; $("qLeadInfo").textContent = "";
  $("qCustomer").value = ""; $("qEmail").value = ""; $("qMobile").value = "";
  $("aInstall").checked = true; $("aInstallAmt").value = ""; $("aPack").value = 0;
  $("aOverallPct").value = ""; $("aOverallAmt").value = "";
  if ($("qPos")) $("qPos").value = SETTINGS.home_state || "27";
  applyBuilderDefaults();
  applyLockState();
  renderItems(); recalc(); updateCart(); goto("builder");
}

// ---- Edit lock: only a "draft" quote is editable; anything else is locked
// until Revise forks a new draft copy. ----
const BUILDER_LOCK_IDS = ["qLead", "qCustomer", "qEmail", "qMobile", "qAddress", "curSel",
  "qTerms", "qPos", "qGst", "aInstall", "aInstallAmt", "aPack",
  "aOverallPct", "aOverallAmt",
  "aLocalFreight", "aIntlFreight", "aImport", "saveBtn", "addProductsBtn"];
function isLocked() { return !!(currentQuoteStatus && currentQuoteStatus !== "draft"); }
function applyLockState() {
  const locked = isLocked();
  BUILDER_LOCK_IDS.forEach((id) => { const el = $(id); if (el) el.disabled = locked; });
  $("lockedBanner").classList.toggle("hide", !locked);
  if (locked) $("lockedStatus").textContent = currentQuoteStatus;
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
      const areaTag = p.area_category
        ? ' <span class="badge cli">' + esc(p.area_category) + "</span>" : "";
      d.innerHTML = '<span style="cursor:pointer" title="View details" onclick="showProductDetail(' + p.id + ')">' + prodImg(p, "md") + "</span>" +
        '<div class="pcat">' + p.category + areaTag + '</div><b>' + p.name +
        '</b><div class="pmodel">' + (p.model_no || "") + '</div><div class="prow"><span>Unit price</span><span class="price">₹ ' +
        Math.round(p.unit_price).toLocaleString("en-IN") + "</span></div>" +
        '<div class="prow"><span>Discounted unit price</span><span class="price">₹ ' +
        Math.round(p.discounted_unit_price).toLocaleString("en-IN") + "</span></div>" + costRow +
        (canDelete ? '<div class="prow" style="border-top:0;padding-top:0;justify-content:flex-end"><button class="del" onclick="event.stopPropagation();delProduct(' +
          p.id + ')" title="Delete product">✕</button></div>' : "");
      g.appendChild(d);
    });
  if (!g.children.length) g.innerHTML = '<div class="empty">No products match.</div>';
}
function toggleAddProduct() {
  const card = $("addProductCard");
  card.classList.toggle("hide");
  if (!card.classList.contains("hide")) {
    ["npdName", "npdModel", "npdCategory", "npdHsn", "npdGst", "npdSpec"].forEach((id) => $(id).value = "");
    $("npdArea").value = "";
    $("npdSourcePrice").value = 0; $("npdLoading").value = 1.5;
    $("npdMarkup").value = 2.0; $("npdUplift").value = 10;
  }
}
async function saveNewProduct() {
  const name = $("npdName").value.trim();
  const category = $("npdCategory").value.trim();
  if (!name) { toast("Product name is required.", true); return; }
  if (!category) { toast("Category is required.", true); return; }
  const gstRaw = $("npdGst").value.trim();
  const data = {
    name, model_no: $("npdModel").value.trim() || null, category,
    area_category: $("npdArea").value || null,
    hsn_code: $("npdHsn").value.trim() || null,
    gst_pct: gstRaw !== "" ? parseFloat(gstRaw) : null,
    source_price_inr: parseFloat($("npdSourcePrice").value) || 0,
    loading_factor: parseFloat($("npdLoading").value) || 1.5,
    client_markup: parseFloat($("npdMarkup").value) || 2.0,
    list_uplift: (parseFloat($("npdUplift").value) || 0) / 100,
    description: $("npdSpec").value.trim() || null,
  };
  try {
    await API.createProduct(data);
    toast("Product added.");
    toggleAddProduct();
    await loadProducts();
    buildCategoryOptions();
    renderProducts();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
async function delProduct(id) {
  try {
    await API.deleteProduct(id);
    toast("Product deleted.");
    await loadProducts();
    buildCategoryOptions();
    renderProducts();
  } catch (e) { toast("Delete failed: " + e.message, true); }
}

// ---- Picker ----
function openPicker() {
  $("picker").classList.add("open"); renderPicker();
  // Refresh in the background so a product added/edited elsewhere while this
  // quote was being built shows up without reopening the picker.
  loadProducts().then(() => { buildCategoryOptions(); renderPicker(); renderProducts(); });
}
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
      d.innerHTML = '<span style="cursor:pointer" title="View details" onclick="showProductDetail(' + p.id + ')">' + prodImg(p, "md") + "</span>" +
        '<div class="pk-b"><span class="pk-cat">' + p.category +
        '</span><b>' + p.name + '</b><span class="pk-model">' + (p.model_no || "") +
        '</span><span class="pk-price">₹ ' + Math.round(p.discounted_unit_price).toLocaleString("en-IN") + "</span>" + costLine +
        '</div><div class="pk-add"><div class="qstep"><button onclick="pq(' + p.id + ',-1)">−</button><input id="pq' + p.id +
        '" value="1" readonly><button onclick="pq(' + p.id + ',1)">＋</button></div>' + pickAddBtnHtml(p) + '</div>';
      g.appendChild(d);
    });
}
function pq(id, delta) { const i = $("pq" + id); i.value = Math.max(1, (parseInt(i.value, 10) || 1) + delta); }
// ---- Product detail modal (image + specification + area/HSN/GST + prices) ----
// Manager/admin get the editable form (specification, work area, HSN, GST%);
// sales see the same values read-only.
const INPUT_STYLE = "border:1px solid var(--line);border-radius:6px;padding:3px 7px";
function showProductDetail(id) {
  const p = prod(id); if (!p) return;
  $("pdTitle").textContent = p.name;
  const gp = p.gst_pct != null ? p.gst_pct + "%" : "default";
  const areaOpts = ['<option value="">— not set —</option>'].concat(AREA_CATEGORIES.map((a) =>
    '<option value="' + a + '"' + (p.area_category === a ? " selected" : "") + ">" + a + "</option>")).join("");
  const areaRow = canSeeCost
    ? '<div class="pd-row"><span>Product Category</span><select id="pdArea" style="' + INPUT_STYLE + '">' + areaOpts + "</select></div>"
    : '<div class="pd-row"><span>Product Category</span><b>' + esc(p.area_category || "—") + "</b></div>";
  const hsnRow = canSeeCost
    ? '<div class="pd-row"><span>HSN Code</span><input id="pdHsn" value="' + esc(p.hsn_code || "") +
      '" placeholder="—" style="width:120px;text-align:right;' + INPUT_STYLE + '"></div>'
    : '<div class="pd-row"><span>HSN Code</span><b>' + esc(p.hsn_code || "—") + "</b></div>";
  const gstRow = canSeeCost
    ? '<div class="pd-row"><span>GST %</span><input id="pdGst" type="number" min="0" step="0.5" value="' +
      (p.gst_pct != null ? p.gst_pct : "") + '" placeholder="default" style="width:80px;text-align:right;' + INPUT_STYLE + '"></div>'
    : '<div class="pd-row"><span>GST %</span><b>' + gp + "</b></div>";
  const saveRow = canSeeCost
    ? '<button class="btn primary sm" style="margin-top:6px" onclick="saveProductEdit(' + p.id + ')">💾 Save</button>' : "";
  // Specification is editable for manager/admin — same Save button as the rest.
  const specBlock = canSeeCost
    ? '<div class="pd-desc"><b>Specification</b><textarea id="pdSpec" rows="6" style="width:100%;margin-top:6px;' +
      INPUT_STYLE + '" placeholder="Product specification shown on the detailed quotation">' + esc(p.description || "") + "</textarea></div>"
    : '<div class="pd-desc"><b>Specification</b><p>' + esc(p.description || "No specification available.") + "</p></div>";
  $("pdBody").innerHTML =
    '<div class="pd-grid">' + prodImg(p, "lg") +
    '<div class="pd-meta">' +
    '<div class="pd-row"><span>Model</span><b>' + esc(p.model_no || "—") + "</b></div>" +
    '<div class="pd-row"><span>Category</span><b>' + esc(p.category || "—") + "</b></div>" +
    areaRow + hsnRow + gstRow +
    '<div class="pd-row"><span>Unit price</span><b>₹ ' + Math.round(p.unit_price).toLocaleString("en-IN") + "</b></div>" +
    '<div class="pd-row"><span>Discounted unit price (−' + DEFAULT_LINE_DISC_PCT + '%)</span><b>₹ ' +
      Math.round(p.discounted_unit_price).toLocaleString("en-IN") + "</b></div>" +
    saveRow +
    "</div></div>" + specBlock;
  $("pdetail").classList.add("open");
}
async function saveProductEdit(id) {
  const hsn_code = $("pdHsn").value.trim() || null;
  const gstRaw = $("pdGst").value.trim();
  const gst_pct = gstRaw !== "" ? parseFloat(gstRaw) : null;
  const area_category = $("pdArea").value || null;
  const description = $("pdSpec").value.trim() || null;
  try {
    await API.updateProduct(id, { hsn_code, gst_pct, area_category, description });
    const p = prod(id);
    if (p) { p.hsn_code = hsn_code; p.gst_pct = gst_pct; p.area_category = area_category; p.description = description; }
    toast("Product updated.");
    renderProducts();
    recalc();               // the work area may change installation charges
    showProductDetail(id);
  } catch (e) { toast("Update failed: " + e.message, true); }
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
    // New lines start at the standard discount off the list Unit Price.
    LINES.push({ pid: id, qty, disc: DEFAULT_LINE_DISC_PCT });
  }
  setPickBtn(id);
  renderItems(); syncOverallDisc(); recalc(); updateCart();
}
function updateCart() {
  const n = LINES.length;
  if ($("cartCnt")) $("cartCnt").textContent = n + " item" + (n !== 1 ? "s" : "") + " in quote";
  if ($("addBadge")) $("addBadge").textContent = n;
}

// ---- Line items ----
function removeItem(idx) { LINES.splice(idx, 1); renderItems(); syncOverallDisc(); recalc(); updateCart(); }
// A line's effective GST% = the product's own rate, else the form-level default.
function lineGstPct(p) {
  if (p && p.gst_pct != null) return p.gst_pct;
  return parseFloat($("qGst") && $("qGst").value) || 0;
}
// Detail section column order, per the client spec: Sr. No, Product Image,
// Product Name, Unit Price, Discount %, Discounted Unit Price, QTY, HSN, Amount
// (then the manager-only Cost/Margin columns). GST is no longer shown per line —
// it appears once in the Summary as CGST/SGST or IGST.
function renderItems() {
  const b = $("itemsBody"); b.innerHTML = "";
  if (!LINES.length) { b.innerHTML = '<tr><td colspan="12"><div class="empty">No items yet — click <b>🛍️ Add Products</b> to build the quote.</div></td></tr>'; return; }
  const dis = isLocked() ? "disabled" : "";
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const tr = document.createElement("tr");
    const costCells = canSeeCost
      ? '<td class="num cost-col" data-cost>' + fmt((p.final_c2e || 0) * ln.qty) + '</td><td class="num cost-col mcell" data-cost></td>'
      : '<td class="num cost-col hide" data-cost></td><td class="num cost-col mcell hide" data-cost></td>';
    const areaTag = p.area_category ? '<br><small class="muted">' + esc(p.area_category) + "</small>" : "";
    tr.innerHTML = '<td class="num">' + (idx + 1) + "</td>" +
      '<td><span style="cursor:pointer" title="View details" onclick="showProductDetail(' + p.id + ')">' + prodImg(p, "sm") + "</span></td>" +
      '<td class="pname"><b>' + p.name + "</b><br><small>" + (p.model_no || "") + "</small>" + areaTag +
      '</td><td class="num">' + fmt(p.unit_price) +
      '</td><td class="num"><input type="number" min="0" max="100" value="' + ln.disc + '" ' + dis + ' onchange="upd(' + idx + ",'disc',this.value)\"></td>" +
      '<td class="num dupcell"></td>' +
      '<td class="num"><input type="number" min="1" value="' + ln.qty + '" ' + dis + ' onchange="upd(' + idx + ",'qty',this.value)\"></td>" +
      '<td class="num"><small>' + (p.hsn_code || "—") + '</small></td>' +
      '<td class="num amtcell"></td>' + costCells +
      '<td><button class="del" ' + dis + ' onclick="removeItem(' + idx + ')">✕</button></td>';
    b.appendChild(tr);
  });
}
function upd(idx, field, val) {
  let v = parseFloat(val) || 0;
  // Above-cap discounts are allowed for sales now — they just route the quote
  // to Pending Approval on save instead of being rejected.
  if (field === "disc" && !canSeeCost && v > SETTINGS.max_discount_pct) {
    toast("Discount exceeds the " + SETTINGS.max_discount_pct + "% policy — this quote will need manager approval to send.");
  }
  LINES[idx][field] = v;
  syncOverallDisc();
  recalc();
}

// ---- Overall discount: % and amount are two views of one figure ----
// Typing in either box derives the other, so the user can work in whichever
// they think in. The amount is what gets sent (it's unambiguous server-side).
function overallDiscBase() {
  return LINES.reduce((s, ln) => {
    const p = prod(ln.pid);
    return p ? s + p.unit_price * ln.qty * (1 - ln.disc / 100) : s;
  }, 0);
}
function onOverallDiscPct() {
  const base = overallDiscBase();
  const pct = parseFloat($("aOverallPct").value);
  $("aOverallAmt").value = isNaN(pct) || !base ? "" : Math.round(base * pct / 100);
  recalc();
}
function onOverallDiscAmt() {
  const base = overallDiscBase();
  const amt = parseFloat($("aOverallAmt").value);
  $("aOverallPct").value = isNaN(amt) || !base ? "" : (amt / base * 100).toFixed(2).replace(/\.?0+$/, "");
  recalc();
}
// Re-derive the amount from the % after the line items change, so a percentage
// the user entered earlier still means that percentage of the new subtotal.
function syncOverallDisc() {
  if ($("aOverallPct").value.trim() !== "") onOverallDiscPct();
}

// ---- Recalc (instant client-side preview; server is authoritative on save) ----
// Mirrors the backend pricing engine: line net off the LIST unit price, the
// quote-level overall discount scaling goods/installation/GST, installation
// charged per line at its work-area rate, add-ons taxed at the default rate,
// split CGST/SGST (intra-state) or IGST.
function recalc() {
  let sub = 0, gross = 0, cost = 0, goodsGst = 0;
  const gstDefault = parseFloat($("qGst") && $("qGst").value) || 0;
  const rows = document.querySelectorAll("#itemsBody tr");
  const nets = [];
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) { nets.push(0); return; }
    const lineGross = p.unit_price * ln.qty;
    const discUnit = p.unit_price * (1 - ln.disc / 100);
    const lineNet = discUnit * ln.qty;
    const lineCost = (p.final_c2e || 0) * ln.qty;
    const gstAmt = lineNet * lineGstPct(p) / 100;
    nets.push(lineNet);
    sub += lineNet; gross += lineGross; cost += lineCost; goodsGst += gstAmt;
    if (rows[idx]) {
      const dc = rows[idx].querySelector(".dupcell"); if (dc) dc.textContent = fmt(discUnit);
      const ac = rows[idx].querySelector(".amtcell"); if (ac) ac.textContent = fmt(lineNet);
      const mc = rows[idx].querySelector(".mcell");
      if (mc && canSeeCost) { const m = lineNet - lineCost; const mp = lineNet > 0 ? (m / lineNet * 100) : 0; mc.innerHTML = '<span class="' + (m >= 0 ? "mpos" : "mneg") + '">' + fmt(m) + " · " + mp.toFixed(0) + "%</span>"; }
    }
  });
  const discGiven = gross - sub;
  // Overall discount (amount is authoritative; clamped to the subtotal).
  const overallRaw = parseFloat($("aOverallAmt").value) || 0;
  const overall = Math.min(Math.max(overallRaw, 0), sub);
  const goodsNet = sub - overall;
  const factor = sub > 0 ? goodsNet / sub : 1;
  goodsGst *= factor;

  // Installation per line, at the rate for that product's work area.
  let instDry = 0, instWet = 0, instOther = 0;
  LINES.forEach((ln, idx) => {
    const p = prod(ln.pid); if (!p) return;
    const base = nets[idx] * factor;
    const area = p.area_category;
    if (area === "Dry Area") instDry += base * INSTALL_RATES.dry / 100;
    else if (area === "Wet Area") instWet += base * INSTALL_RATES.wet / 100;
    else instOther += base * INSTALL_RATES.other / 100;
  });
  const instOverride = $("aInstallAmt").value.trim();
  const usingOverride = instOverride !== "";
  if (!$("aInstall").checked || usingOverride) instDry = instWet = instOther = 0;
  const install = !$("aInstall").checked ? 0
    : (usingOverride ? (parseFloat(instOverride) || 0) : instDry + instWet + instOther);

  const pack = parseFloat($("aPack").value) || 0;
  const localF = parseFloat($("aLocalFreight").value) || 0;
  const intlF = parseFloat($("aIntlFreight").value) || 0;
  const imp = parseFloat($("aImport").value) || 0;
  const freight = localF + intlF + imp;
  const addonBase = install + pack + freight;
  const grand = goodsNet + addonBase;             // pre-tax
  const taxable = grand;                          // GST base = goods + install + freight
  const gstTotal = goodsGst + addonBase * gstDefault / 100;
  const intra = ($("qPos").value || "") === (SETTINGS.home_state || "27");
  const cgst = intra ? gstTotal / 2 : 0;
  const sgst = intra ? gstTotal / 2 : 0;
  const igst = intra ? 0 : gstTotal;
  const finalPayable = taxable + gstTotal;

  $("sSub").textContent = fmt(sub);
  $("sDisc").textContent = "– " + fmt(discGiven);
  $("sOverall").textContent = "– " + fmt(overall);
  $("sGoodsNet").textContent = fmt(goodsNet);
  $("sInstall").textContent = fmt(install);
  $("sInstDry").textContent = fmt(instDry);
  $("sInstWet").textContent = fmt(instWet);
  $("sInstOther").textContent = fmt(instOther);
  // Only show a breakdown row that's actually carrying a charge.
  $("rowInstDry").classList.toggle("hide", !instDry);
  $("rowInstWet").classList.toggle("hide", !instWet);
  $("rowInstOther").classList.toggle("hide", !instOther);
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
    const totMargin = goodsNet - cost;
    $("mCost").textContent = fmt(cost);
    $("mMargin").textContent = fmt(totMargin);
    $("mPct").textContent = (goodsNet > 0 ? (totMargin / goodsNet * 100) : 0).toFixed(1) + "%";
  }
  const effectiveDisc = gross > 0 ? ((discGiven + overall) / gross * 100) : 0;
  const anyHigh = LINES.some((l) => l.disc > 15 || (!canSeeCost && l.disc > SETTINGS.max_discount_pct));
  $("approvalBox").classList.toggle("hide", !(effectiveDisc > 12 || anyHigh));
  const overallPct = sub > 0 ? (overall / sub * 100) : 0;
  const installPct = goodsNet > 0 ? (install / goodsNet * 100) : 0;
  window._Q = { sub, overall, overallPct, goodsNet, install, installPct, pack,
                localFreight: localF, intlFreight: intlF + imp, freight, grand, taxable,
                gstTotal, cgst, sgst, igst, intra, finalPayable };
}

// ---- Save quote (server computes authoritative totals) ----
async function saveQuote() {
  if (isLocked()) {
    toast("This quote is locked (" + currentQuoteStatus + "). Click Revise to edit a copy.", true);
    return;
  }
  if (!LINES.length) { toast("Add at least one product first.", true); return; }
  $("saveBtn").disabled = true;
  try {
    const payload = {
      customer_name: $("qCustomer").value.trim(),
      customer_email: $("qEmail").value.trim() || null,
      customer_address: $("qAddress").value.trim() || null,
      customer_mobile: $("qMobile").value.trim() || null,
      client_id: selectedClientId,
      lead_id: parseInt($("qLead").value, 10) || null,
      currency: cur(),
      terms_template_id: parseInt($("qTerms").value, 10) || null,
      install_enabled: $("aInstall").checked,
      install_pct: INSTALL_RATES.other / 100,
      install_dry_pct: INSTALL_RATES.dry / 100,
      install_wet_pct: INSTALL_RATES.wet / 100,
      install_amount: $("aInstallAmt").value.trim() !== "" ? (parseFloat($("aInstallAmt").value) || 0) : null,
      packaging: parseFloat($("aPack").value) || 0,
      overall_disc_pct: parseFloat($("aOverallPct").value) || 0,
      overall_disc_amount: $("aOverallAmt").value.trim() !== "" ? (parseFloat($("aOverallAmt").value) || 0) : null,
      local_freight: parseFloat($("aLocalFreight").value) || 0,
      intl_freight: parseFloat($("aIntlFreight").value) || 0,
      import_charge: parseFloat($("aImport").value) || 0,
      place_of_supply: $("qPos").value || null,
      gst_default_pct: parseFloat($("qGst").value) || 0,
      lines: LINES.map((l) => ({ product_id: l.pid, qty: l.qty, line_disc: l.disc })),
    };
    const q = currentQuoteId
      ? await API.updateQuote(currentQuoteId, payload)
      : await API.createQuote(payload);
    currentQuoteId = q.id;
    currentQuoteStatus = q.status;
    lastPreview = await API.previewQuote(q.id);
    $("builderSub").textContent = q.quote_no + " · " + (q.totals.needs_approval && !q.approved ? "Pending Approval" : "Draft");
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
      const spec = ln.specification
        ? "<br><span style='color:#7a8a99;font-size:10.5px'>" + esc(ln.specification).slice(0, 240) + "</span>" : "";
      tr.innerHTML = "<td>" + (i + 1) + "</td><td>" + ln.name + "<br><span style='color:#7a8a99;font-size:11px'>" + (ln.model_no || "") +
        "</span>" + spec + '</td><td class="num">' + fmt(ln.unit_price) +
        '</td><td class="num">' + (ln.line_disc || 0) + '%</td><td class="num">' + fmt(ln.discounted_unit_price) +
        '</td><td class="num">' + ln.qty + "</td><td class=\"num\"><small>" + (ln.hsn_code || "—") +
        '</small></td><td class="num">' + fmt(ln.line_net) + "</td>";
      b.appendChild(tr);
    });
    const t = lastPreview.totals;
    $("pvSub").textContent = fmt(t.subtotal_net);
    setPreviewOverall(t.overall_discount);
    setPreviewPct("pvRowOverallPct", "pvOverallPct", t.overall_discount, t.overall_disc_pct);
    setPreviewPct("pvRowInstallPct", "pvInstallPct", t.installation, t.installation_pct);
    $("pvInstall").textContent = fmt(t.installation);
    $("pvPack").textContent = fmt(lastPreview.packaging || 0);
    setPreviewFreight(lastPreview.local_freight || 0,
                      (lastPreview.intl_freight || 0) + (lastPreview.import_charge || 0));
    $("pvTaxable").textContent = fmt(t.taxable_amount);
    setPreviewTax(t.is_intra_state, t.cgst, t.sgst, t.igst);
    $("pvGrand").textContent = fmt(t.final_payable);
    const pending = !!(t.needs_approval && !lastPreview.approved);
    $("pvApprovalBadge").classList.toggle("hide", !pending);
    $("previewApprovalNote").classList.toggle("hide", !pending);
    const blockSend = pending && !canSeeCost;
    $("emailBtn").disabled = blockSend;
    $("waBtn").disabled = blockSend;
  } else {
    recalc();
    $("pvNo").textContent = "(unsaved draft)";
    $("pvDate").textContent = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
    LINES.forEach((ln, i) => {
      const p = prod(ln.pid); if (!p) return;
      const discUnit = p.unit_price * (1 - ln.disc / 100);
      const net = discUnit * ln.qty;
      const spec = p.description
        ? "<br><span style='color:#7a8a99;font-size:10.5px'>" + esc(p.description).slice(0, 240) + "</span>" : "";
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + (i + 1) + '</td><td><div class="cli-thumb">' + prodImg(p, "sm") +
        "<div><b style='color:var(--navy)'>" + p.name + "</b><br><span style='color:#7a8a99;font-size:11px'>" + (p.model_no || "") +
        "</span>" + spec + '</div></div></td><td class="num">' + fmt(p.unit_price) +
        '</td><td class="num">' + ln.disc + '%</td><td class="num">' + fmt(discUnit) +
        '</td><td class="num">' + ln.qty + "</td><td class=\"num\"><small>" + (p.hsn_code || "—") +
        '</small></td><td class="num">' + fmt(net) + "</td>";
      b.appendChild(tr);
    });
    const Q = window._Q || {};
    $("pvSub").textContent = fmt(Q.sub || 0);
    setPreviewOverall(Q.overall || 0);
    setPreviewPct("pvRowOverallPct", "pvOverallPct", Q.overall, Q.overallPct);
    setPreviewPct("pvRowInstallPct", "pvInstallPct", Q.install, Q.installPct);
    $("pvInstall").textContent = fmt(Q.install || 0);
    $("pvPack").textContent = fmt(Q.pack || 0);
    setPreviewFreight(Q.localFreight || 0, Q.intlFreight || 0);
    $("pvTaxable").textContent = fmt(Q.taxable || 0);
    setPreviewTax(Q.intra, Q.cgst || 0, Q.sgst || 0, Q.igst || 0);
    $("pvGrand").textContent = fmt(Q.finalPayable || 0);
    $("pvApprovalBadge").classList.add("hide");
    $("previewApprovalNote").classList.add("hide");
    $("emailBtn").disabled = false;
    $("waBtn").disabled = false;
  }
}
function setPreviewOverall(amount) {
  $("pvRowOverall").classList.toggle("hide", !amount);
  $("pvOverall").textContent = "– " + fmt(amount || 0);
}
// Shows a "<label> %" row only when its underlying amount is actually charged.
function setPreviewPct(rowId, valId, amount, pct) {
  $(rowId).classList.toggle("hide", !amount);
  $(valId).textContent = (pct || 0).toFixed(1) + "%";
}
function setPreviewFreight(local, intl) {
  $("pvRowLocalFreight").classList.toggle("hide", !local);
  $("pvLocalFreight").textContent = fmt(local || 0);
  $("pvRowIntlFreight").classList.toggle("hide", !intl);
  $("pvIntlFreight").textContent = fmt(intl || 0);
}
// ---- Quotation history: the original plus every revision raised against it ----
async function renderHistory() {
  const card = $("historyCard");
  if (!currentQuoteId) { card.classList.add("hide"); return; }
  try {
    const h = await API.quoteHistory(currentQuoteId);
    // Only worth showing once a revision exists — a lone original is just noise.
    if (h.quotes.length < 2) { card.classList.add("hide"); return; }
    $("historyRows").innerHTML = h.quotes.map((q) => {
      const isCurrent = q.id === h.current_quote_id;
      const date = q.date ? new Date(q.date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "—";
      const parent = q.is_original ? "" : ' <small class="muted">(revised from ' +
        esc((h.quotes.find((x) => x.id === q.revision_of) || {}).quote_no || "—") + ")</small>";
      return '<tr style="cursor:pointer" onclick="openQuote(' + q.id + ')" title="Open ' + esc(q.quote_no) + '">' +
        "<td><b>" + esc(q.label) + "</b>" + (isCurrent ? ' <span class="badge int">viewing</span>' : "") + "</td>" +
        "<td>" + esc(q.quote_no) + parent + "</td><td>" + date +
        '</td><td><span class="st ' + q.status + '">' + q.status.charAt(0).toUpperCase() + q.status.slice(1) + "</span></td>" +
        '<td class="num">₹ ' + Math.round(q.final_payable).toLocaleString("en-IN") + "</td></tr>";
    }).join("");
    card.classList.remove("hide");
  } catch (e) { card.classList.add("hide"); }
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
    if (r.sent && !r.dry_run) { currentQuoteStatus = "sent"; applyLockState(); }
    toast(r.dry_run ? "Dry run — configure Email Setup to actually send (to " + r.to + ")"
                     : "Email sent successfully to " + r.to, false, !r.dry_run);
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
// A quote's revision position, for the builder subtitle — "R2 of EVAVO/.../0045".
function revisionLabel(q) {
  return q.revision_no ? "Revision " + q.revision_no + " of " + q.root_quote_no : "Original";
}
// Load a saved quote's fields into the Quote Builder. Shared by Open and Revise.
function applyQuoteToBuilder(q) {
  currentQuoteId = q.id;
  currentQuoteStatus = q.status;
  LINES = q.lines.map((l) => ({ pid: l.product_id, qty: l.qty, disc: l.line_disc }));
  $("qCustomer").value = q.customer_name || "";
  $("qEmail").value = q.customer_email || "";
  $("qAddress").value = q.customer_address || "";
  $("qMobile").value = q.customer_mobile || "";
  selectedClientId = q.client_id || null;
  selectLeadForBuilder(q.lead_id || null);
  if (q.terms_template_id != null) $("qTerms").value = q.terms_template_id;
  if (q.currency && $("curSel").querySelector('option[value="' + q.currency + '"]')) $("curSel").value = q.currency;
  // Restore GST / add-on / freight fields. Installation rates come from the
  // quote's own snapshot, not current Settings, so an old quote keeps its
  // numbers even after an admin re-tunes the dry/wet percentages.
  $("aInstall").checked = q.install_enabled !== false;
  INSTALL_RATES = {
    dry: pctOf(q.install_dry_pct != null ? q.install_dry_pct : q.install_pct),
    wet: pctOf(q.install_wet_pct != null ? q.install_wet_pct : q.install_pct),
    other: pctOf(q.install_pct),
  };
  showInstallRates();
  $("aInstallAmt").value = q.install_amount != null ? q.install_amount : "";
  $("aOverallPct").value = q.overall_disc_pct || "";
  $("aOverallAmt").value = q.overall_disc_amount != null ? q.overall_disc_amount : "";
  $("aPack").value = q.packaging || 0;
  $("aLocalFreight").value = q.local_freight || 0;
  $("aIntlFreight").value = q.intl_freight || 0;
  $("aImport").value = q.import_charge || 0;
  $("qPos").value = q.place_of_supply || "";
  if (q.gst_default_pct) $("qGst").value = q.gst_default_pct;
  applyLockState();
  renderItems(); recalc(); updateCart();
}
async function openQuote(id) {
  try {
    const q = await API.getQuote(id);
    lastPreview = await API.previewQuote(id);
    applyQuoteToBuilder(q);
    $("builderSub").textContent = q.quote_no + " · " + revisionLabel(q) +
      " · " + q.status.charAt(0).toUpperCase() + q.status.slice(1);
    goto("preview");
    toast("Opened " + q.quote_no);
  } catch (e) { toast("Open failed: " + e.message, true); }
}
async function reviseCurrent() {
  if (!requireSaved()) return;
  try {
    const rev = await API.reviseQuote(currentQuoteId);
    lastPreview = null;
    applyQuoteToBuilder(rev);
    $("builderSub").textContent = rev.quote_no + " · " + revisionLabel(rev) + " · Draft";
    toast("Created revision " + rev.quote_no + " of " + rev.root_quote_no);
    goto("builder");
  } catch (e) { toast("Revise failed: " + e.message, true); }
}
async function deleteCurrentQuote() {
  if (!requireSaved()) return;
  if (!confirm("Delete this quotation permanently? This cannot be undone.")) return;
  try {
    await API.deleteQuote(currentQuoteId);
    toast("Quotation deleted.");
    currentQuoteId = null; currentQuoteStatus = null; lastPreview = null;
    await loadDashboard();
    goto("dashboard");
  } catch (e) { toast("Delete failed: " + e.message, true); }
}

// ---- Masters screens ----
// Clients, Projects and Leads are now separate pages with a real hierarchy:
// a Client has many Projects, a Project has many Leads (Lead.client_id is
// auto-derived server-side from its Project). Each list reuses an inline
// Add/Edit form (editing*Id tracks which row, if any, is being edited).
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m])));
// ISO date (yyyy-mm-dd) as dd Mmm yyyy for list display; blank stays a dash.
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("en-GB",
  { day: "2-digit", month: "short", year: "numeric" }) : "—");
const clip = (s, n) => (!s ? "" : (s.length > n ? s.slice(0, n) + "…" : s));

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
      '<div class="field"><label>Company Name</label><input id="ncName"></div>' +
      '<div class="field"><label>Email</label><input id="ncEmail"></div>' +
      '<div class="field"><label>Phone</label><input id="ncPhone"></div>' +
      '<div class="field"><label>Mobile (WhatsApp)</label><input id="ncMobile"></div>' +
      '<div class="field"><label>City</label><input id="ncCity"></div></div>' +
      '<button class="btn primary sm" onclick="saveClient()">' + (editing ? "💾 Update Client" : "＋ Add Client") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelClientEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Clients (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Company Name</th><th>Email</th><th>Phone</th><th>Mobile</th><th>City</th><th></th>' +
      (canDelete ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.phone) + "</td><td>" + esc(r.mobile) + "</td><td>" + esc(r.city) +
        '</td><td><button class="btn ghost sm" onclick="editClient(' + r.id + ')">Edit</button></td>' +
        (canDelete ? '<td><button class="del" onclick="delClient(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
        : '<tr><td colspan="7"><div class="empty">No clients yet.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingClientId);
      if (r) { $("ncName").value = r.name || ""; $("ncEmail").value = r.email || ""; $("ncPhone").value = r.phone || ""; $("ncMobile").value = r.mobile || ""; $("ncCity").value = r.city || ""; }
    }
  } catch (e) { c.innerHTML = '<div class="empty">' + e.message + "</div>"; }
}
async function saveClient() {
  const name = $("ncName").value.trim();
  if (!name) { toast("Company name is required.", true); return; }
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
      '<div class="field"><label>Company Name</label><select id="npClient"><option value="">Select a company…</option>' + clientOptions + "</select></div>" +
      '<div class="field"><label>Project Name</label><input id="npName"></div>' +
      '<div class="field"><label>City</label><input id="npCity"></div></div>' +
      '<button class="btn primary sm" onclick="saveProject()">' + (editing ? "💾 Update Project" : "＋ Add Project") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelProjectEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Projects (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Company Name</th><th>Project</th><th>City</th><th></th>' +
      (canDelete ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(clientName(r.client_id)) + "</td><td>" + esc(r.name) + "</td><td>" + esc(r.city) +
        '</td><td><button class="btn ghost sm" onclick="editProject(' + r.id + ')">Edit</button></td>' +
        (canDelete ? '<td><button class="del" onclick="delProject(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
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
  if (!clientId) { toast("Select a company.", true); return; }
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
      '<div class="field"><label>Lead Received Date</label><input id="nlReceived" type="date"></div>' +
      '<div class="field"><label>Project</label><select id="nlProject" onchange="updateLeadClientLabel()"><option value="">Select a project…</option>' + projectOptions + "</select></div>" +
      '<div class="field"><label>Company Name</label><input id="nlClient" disabled value="—"></div>' +
      '<div class="field"><label>Client Name</label><input id="nlName" placeholder="Contact person"></div>' +
      '<div class="field"><label>Mobile Number</label><input id="nlWhatsapp" placeholder="Also used for WhatsApp"></div>' +
      '<div class="field"><label>Email ID</label><input id="nlEmail" type="email"></div>' +
      '<div class="field"><label>Sales Person Name / Handled By</label><input id="nlOwner"></div>' +
      '<div class="field"><label>Stage</label><select id="nlStage"><option value="0">Leads</option><option value="1">Quoted</option><option value="2">Negotiation</option><option value="3">Won</option></select></div>' +
      '<div class="field" style="grid-column:1/-1"><label>Requirement</label><textarea id="nlRequirement" rows="2" placeholder="What the customer is asking for"></textarea></div>' +
      '<div class="field" style="grid-column:1/-1"><label>Address (site/installation — may differ from the company\'s registered address)</label><textarea id="nlAddress" rows="2"></textarea></div></div>' +
      '<button class="btn primary sm" onclick="saveLead()">' + (editing ? "💾 Update Lead" : "＋ Add Lead") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelLeadEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Leads (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Received</th><th>Project</th><th>Company Name</th><th>Client Name</th><th>Mobile</th><th>Email ID</th><th>Requirement</th><th>Handled By</th><th>Stage</th><th></th>' +
      (canDelete ? "<th></th>" : "") + "</tr></thead><tbody>" +
      (rows.length ? rows.map((r) => "<tr><td>" + fmtDate(r.received_date) + "</td><td>" + esc(projectName(r.project_id)) +
        "</td><td>" + esc(leadClientLabel(projects, clients, r.project_id)) +
        "</td><td>" + esc(r.name) + "</td><td>" + esc(r.whatsapp_number) + "</td><td>" + esc(r.email) +
        '</td><td><span title="' + esc(r.requirement) + '">' + esc(clip(r.requirement, 40)) +
        "</span></td><td>" + esc(r.owner) + "</td><td>" + stageName[r.stage] +
        '</td><td><button class="btn ghost sm" onclick="editLead(' + r.id + ')">Edit</button></td>' +
        (canDelete ? '<td><button class="del" onclick="delLead(' + r.id + ')">✕</button></td>' : "") + "</tr>").join("")
        : '<tr><td colspan="11"><div class="empty">No leads yet — add a project first.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingLeadId);
      if (r) {
        $("nlProject").value = r.project_id || "";
        $("nlName").value = r.name || ""; $("nlOwner").value = r.owner || "";
        $("nlStage").value = r.stage;
        $("nlReceived").value = r.received_date || "";
        $("nlEmail").value = r.email || "";
        $("nlRequirement").value = r.requirement || "";
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
  if (!name) { toast("Client name is required.", true); return; }
  if (!projectId) { toast("Select a project.", true); return; }
  const data = {
    name, owner: $("nlOwner").value.trim() || null,
    stage: parseInt($("nlStage").value, 10), project_id: projectId,
    received_date: $("nlReceived").value || null,
    email: $("nlEmail").value.trim() || null,
    requirement: $("nlRequirement").value.trim() || null,
    address: $("nlAddress").value.trim() || null,
    whatsapp_number: $("nlWhatsapp").value.trim() || null,
  };
  try {
    if (editingLeadId != null) { await API.updateLead(editingLeadId, data); toast("Lead updated."); editingLeadId = null; }
    else { await API.createLead(data); toast("Lead added."); }
    renderLeadsMaster(); loadDashboard(); loadBuilderLeads();
  } catch (e) { toast("Save failed: " + e.message, true); }
}
function editLead(id) { editingLeadId = id; renderLeadsMaster(); }
function cancelLeadEdit() { editingLeadId = null; renderLeadsMaster(); }
async function delLead(id) {
  try { await API.deleteLead(id); toast("Lead deleted."); renderLeadsMaster(); loadDashboard(); loadBuilderLeads(); }
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
        '<button class="btn ghost sm" style="margin-top:10px" onclick="saveTerms(' + t.id + ",'" + esc(t.name).replace(/'/g, "") + "','" + t.kind + "')\">💾 Save</button>" +
        (canDelete ? ' <button class="btn ghost sm" style="margin-top:10px" onclick="delTerms(' + t.id + ')">🗑 Delete</button>' : "") +
        "</div>").join("");
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
async function delTerms(id) {
  try { await API.deleteTerms(id); toast("Template deleted."); renderTermsMaster(); loadTerms(); }
  catch (e) { toast("Delete failed: " + e.message, true); }
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
    '<div class="field"><label>Dry Area installation charges (%)</label><input id="stInstallDry" type="number" step="0.5" value="' + (s.install_dry_pct * 100) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Wet Area installation charges (%)</label><input id="stInstallWet" type="number" step="0.5" value="' + (s.install_wet_pct * 100) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
    '<div class="field"><label>Others / uncategorised installation (%)</label><input id="stInstall" type="number" step="0.5" value="' + (s.install_pct * 100) + '"' + (isAdmin ? "" : " disabled") + "></div>" +
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
      install_dry_pct: (parseFloat($("stInstallDry").value) || 0) / 100,
      install_wet_pct: (parseFloat($("stInstallWet").value) || 0) / 100,
      local_freight: parseFloat($("stLocal").value) || 0,
      intl_freight: parseFloat($("stIntl").value) || 0,
      import_charge: parseFloat($("stImport").value) || 0,
      home_state: $("stHome").value,
    });
    applyBuilderDefaults();   // new install rates apply to the next quote built
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
      '<div class="field"><label>Active</label><select id="nuActive"><option value="true">Yes</option><option value="false">No</option></select></div>' +
      '<div class="field"><label>Delete Access <span class="muted" style="font-weight:400">(Masters &amp; Quotations)</span></label><select id="nuCanDelete"><option value="false">No</option><option value="true">Yes</option></select></div></div>' +
      '<button class="btn primary sm" onclick="saveUser()">' + (editing ? "💾 Update User" : "＋ Add User") + "</button>" +
      (editing ? ' <button class="btn ghost sm" onclick="cancelUserEdit()">Cancel</button>' : "") + "</div>" +
      '<div class="card pad"><div class="section-title">Users (' + rows.length + ')</div>' +
      '<table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Branch</th><th>Active</th><th>Delete Access</th><th></th><th></th></tr></thead><tbody>' +
      (rows.length ? rows.map((r) => "<tr><td>" + esc(r.name) + "</td><td>" + esc(r.email) + "</td><td>" + esc(r.role) +
        "</td><td>" + esc(r.branch) + "</td><td>" + (r.is_active ? "Yes" : "No") +
        "</td><td>" + (r.role === "manager" || r.role === "admin" ? '<span class="muted">always</span>' : (r.can_delete ? "Yes" : "No")) +
        '</td><td><button class="btn ghost sm" onclick="editUser(' + r.id + ')">Edit</button></td>' +
        '<td><button class="del" onclick="delUser(' + r.id + ')">✕</button></td></tr>').join("")
        : '<tr><td colspan="8"><div class="empty">No users yet.</div></td></tr>') + "</tbody></table></div>";
    if (editing) {
      const r = rows.find((x) => x.id === editingUserId);
      if (r) {
        $("nuName").value = r.name || ""; $("nuEmail").value = r.email || "";
        $("nuRole").value = r.role; $("nuBranch").value = r.branch || "";
        $("nuActive").value = r.is_active ? "true" : "false";
        $("nuCanDelete").value = r.can_delete ? "true" : "false";
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
    can_delete: $("nuCanDelete").value === "true",
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
  renderApprovalsPending(quotes);
  renderPipelineBars(leads);
  renderFxRows();
  renderKanban(leads);
}
function renderApprovalsPending(quotes) {
  const card = $("approvalsPanelCard");
  const pending = quotes.filter((q) => q.needs_approval && !q.approved);
  const show = canSeeCost && pending.length > 0;
  card.classList.toggle("hide", !show);
  const b = $("approvalsPending"); b.innerHTML = "";
  if (!show) return;
  pending.forEach((q) => {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.title = "Open " + q.quote_no;
    tr.innerHTML = "<td>" + q.quote_no + "</td><td>" + q.customer_name + '</td><td class="num">₹' +
      Math.round(q.grand_total).toLocaleString("en-IN") +
      '</td><td><button class="btn teal sm" onclick="approveQuoteRow(' + q.id + ",'" + q.quote_no + "',event)\">✓ Approve</button></td>";
    tr.onclick = () => openQuote(q.id);
    b.appendChild(tr);
  });
}
async function approveQuoteRow(id, quoteNo, event) {
  if (event) event.stopPropagation();
  try {
    await API.approveQuote(id);
    toast("Approved " + quoteNo + ".");
    await loadDashboard();
  } catch (e) { toast("Approve failed: " + e.message, true); }
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
    const approvalTag = q.needs_approval
      ? (q.approved ? '<span class="badge cli" style="margin-left:6px">✓ Approved</span>'
                    : '<span class="badge warn" style="margin-left:6px">⏳ Pending Approval</span>')
      : "";
    const revTag = q.revision_no
      ? ' <span class="badge cli" title="Revision ' + q.revision_no + " of " + esc(q.root_quote_no) + '">R' + q.revision_no + "</span>" : "";
    tr.innerHTML = "<td>" + q.quote_no + revTag + "</td><td>" + q.customer_name + '</td><td class="num">₹' +
      Math.round(q.grand_total).toLocaleString("en-IN") + '</td><td><span class="st ' + q.status + '">' +
      q.status.charAt(0).toUpperCase() + q.status.slice(1) + "</span>" + approvalTag + "</td>";
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
      // Amount is no longer captured on a lead, so only legacy rows that still
      // carry one show a value — a "₹ 0" line would just be noise.
      const amt = l.amount ? '<div class="amt">₹ ' + l.amount.toLocaleString("en-IN") + "</div>" : "";
      c.innerHTML = "<b>" + esc(l.name) + '</b><div class="meta"><span>Handled by: ' + esc(l.owner || "—") + "</span></div>" + amt;
      c.onclick = () => { newQuote(); $("qLead").value = l.id; onLeadSelected(); };
      col.appendChild(c);
    });
    k.appendChild(col);
  });
}

// ---- Start ----
if (API.getToken()) boot(); else showLogin();
