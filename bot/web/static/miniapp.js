/* WENPOLYMARKET Mini App — v5 SPA */

const tg = window.Telegram?.WebApp;
const APP = { initData: tg?.initData || "", user: null, cache: new Map(), mainBtnHandler: null, backHandler: null };

/* ── API ─────────────────────────────────────────── */
async function api(path, opts = {}) {
  let res;
  try {
    res = await fetch("/miniapp/api" + path, {
      method: opts.method || "GET",
      headers: { "Authorization": "tma " + APP.initData, "Content-Type": "application/json", ...(opts.headers || {}) },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch (netErr) {
    throw new Error("Connexion réseau impossible (" + (netErr.message || "fetch failed") + ")");
  }
  if (!res.ok) {
    let detail = "";
    try { const j = await res.json(); detail = j.detail || ""; } catch {}
    const msg = detail || res.statusText || ("HTTP " + res.status);
    throw new Error(`[${path}] ${msg} (HTTP ${res.status})`);
  }
  try { return await res.json(); }
  catch (parseErr) {
    throw new Error(`[${path}] Réponse invalide (${parseErr.message || "parse error"})`);
  }
}
async function cached(key, fn, ttl = 20000) {
  const e = APP.cache.get(key);
  if (e && Date.now() - e.t < ttl) return e.v;
  const v = await fn(); APP.cache.set(key, { v, t: Date.now() }); return v;
}
function invalidate(prefix) { for (const k of [...APP.cache.keys()]) if (k.startsWith(prefix)) APP.cache.delete(k); }
function invalidateAll() { APP.cache.clear(); }

/* ── Utils ───────────────────────────────────────── */
const fmtUsd = x => "$" + Number(x || 0).toFixed(2);
const fmtPct = x => Number(x || 0).toFixed(1) + "%";
const shortAddr = a => a ? a.slice(0,6) + "…" + a.slice(-4) : "";
const pnlClass = x => x > 0 ? "pnl-pos" : x < 0 ? "pnl-neg" : "";
const pnlSign = x => (x > 0 ? "+" : "") + fmtUsd(x);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const haptic = (t="light") => tg?.HapticFeedback?.impactOccurred?.(t);
const hapticNotif = (t="success") => tg?.HapticFeedback?.notificationOccurred?.(t);
function timeAgo(iso) {
  if (!iso) return "";
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "à l'instant";
  if (d < 3600) return Math.floor(d/60) + " min";
  if (d < 86400) return Math.floor(d/3600) + " h";
  return Math.floor(d/86400) + " j";
}
/** Latence d'exécution : temps entre détection du signal et exécution.
 *  Input : ms (int). Retourne "240 ms", "1.2 s", "—".
 *  Bonus : ⚡ devant si sub-seconde. */
function fmtLatency(ms) {
  if (ms == null) return "—";
  const prefix = ms < 1000 ? "⚡ " : "";
  if (ms < 1000) return `${prefix}${ms} ms`;
  if (ms < 60000) return `${(ms/1000).toFixed(1)} s`;
  return `${Math.floor(ms/60000)} min`;
}
/** Couleur selon latence : < 1s vert (objectif), 1-2s neutre, 2-5s orange, > 5s rouge */
function latencyClass(ms) {
  if (ms == null) return "";
  if (ms < 1000) return "pnl-pos";
  if (ms < 2000) return "";
  if (ms < 5000) return "";
  return "pnl-neg";
}
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast("Copié")); haptic("light"); }

function toast(msg, type="success") {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = document.createElement("div");
  t.className = "toast " + type; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transform = "translate(-50%,-10px)"; t.style.transition = "opacity .2s, transform .2s"; }, 1800);
  setTimeout(() => t.remove(), 2100);
  hapticNotif(type === "error" ? "error" : "success");
}
function confirmModal(title, text, confirmText="Confirmer", variant="primary") {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "modal-backdrop";
    bd.innerHTML = `<div class="modal"><h3>${esc(title)}</h3><div class="modal-sub">${esc(text).replace(/\n/g,"<br>")}</div><button class="btn btn-${variant}" id="cm-ok">${esc(confirmText)}</button><button class="btn btn-secondary" id="cm-cancel" style="margin-top:8px">Annuler</button></div>`;
    document.body.appendChild(bd);
    bd.querySelector("#cm-ok").onclick = () => { bd.remove(); resolve(true); };
    bd.querySelector("#cm-cancel").onclick = () => { bd.remove(); resolve(false); };
    bd.addEventListener("click", e => { if (e.target === bd) { bd.remove(); resolve(false); } });
  });
}

function render(html) { document.getElementById("content").innerHTML = html; }
function setTab(name) { document.querySelectorAll(".tab-bar a").forEach(a => a.classList.toggle("active", a.dataset.tab === name)); }
function setBack(hash) {
  if (!tg?.BackButton) return;
  if (APP.backHandler) { try { tg.BackButton.offClick(APP.backHandler); } catch {} }
  if (hash) { APP.backHandler = () => { haptic("light"); go(hash); }; tg.BackButton.onClick(APP.backHandler); tg.BackButton.show(); }
  else { tg.BackButton.hide(); }
}
function setMainBtn(text, onClick) {
  if (!tg?.MainButton) return;
  if (APP.mainBtnHandler) { try { tg.MainButton.offClick(APP.mainBtnHandler); } catch {} }
  APP.mainBtnHandler = () => { haptic("medium"); onClick(); };
  tg.MainButton.setText(text); tg.MainButton.onClick(APP.mainBtnHandler); tg.MainButton.show();
}
function clearMainBtn() {
  if (!tg?.MainButton) return;
  if (APP.mainBtnHandler) { try { tg.MainButton.offClick(APP.mainBtnHandler); } catch {} }
  APP.mainBtnHandler = null; tg.MainButton.hide();
}

const skeleton = () => `<div class="skeleton skeleton-hero"></div><div class="stats" style="margin-bottom:12px">${Array(4).fill(0).map(() => `<div class="skeleton skeleton-stat"></div>`).join("")}</div>${Array(2).fill(0).map(() => `<div class="card"><div class="skeleton skeleton-line wide"></div><div class="skeleton skeleton-line half"></div></div>`).join("")}`;
const stat = (v, l, cls="") => `<div class="stat"><div class="stat-value ${cls}">${v}</div><div class="stat-label">${esc(l)}</div></div>`;
const statsGrid = (items, cols=2) => `<div class="stats ${cols===4?'cols-4':cols===3?'cols-3':''}">${items.map(i=>stat(i.value,i.label,i.cls||"")).join("")}</div>`;
const subNav = (items, active) => `<div class="sub-nav">${items.map(i => `<a href="#${i.href}" class="sub-nav-item ${i.href === active ? "active" : ""}">${esc(i.label)}${i.count != null ? ` <span class="sub-nav-count">${i.count}</span>` : ""}</a>`).join("")}</div>`;
const sectionTitle = (label, action) => `<div class="section-title"><h2>${esc(label)}</h2>${action ? `<a class="card-action" onclick="${action.onclick}">${esc(action.label)} ›</a>` : ""}</div>`;
const emptyState = (icon, title, text, btn) => `<div class="empty"><div class="empty-icon">${icon}</div><div class="empty-title">${esc(title)}</div>${text ? `<div class="empty-text">${esc(text)}</div>` : ""}${btn ? `<button class="btn btn-primary" style="max-width:240px;margin:0 auto" onclick="${btn.onclick}">${esc(btn.label)}</button>` : ""}</div>`;
const badge = (text, variant="blue") => `<span class="badge badge-${variant}">${esc(text)}</span>`;

function modeBadge(user) {
  if (user.paper_trading) return `<div class="mode-banner paper"><span>📝</span><div><div class="mode-title">MODE PAPER</div><div class="mode-sub">Simulation — solde fictif ${fmtUsd(user.paper_balance)}</div></div></div>`;
  return `<div class="mode-banner live"><span>💵</span><div><div class="mode-title">MODE LIVE</div><div class="mode-sub">Trades réels · USDC Polygon</div></div></div>`;
}
function stateBadge(user) {
  if (!user.is_active) return badge("⏹ ARRÊTÉ", "red");
  if (user.is_paused) return badge("⏸ PAUSE", "orange");
  return badge("● ACTIF", "green");
}

/* ── Router ──────────────────────────────────────── */
const routes = [];
function route(pattern, handler, opts={}) { routes.push({pattern, handler, opts}); }
function go(hash) { location.hash = hash; }

const KNOWN_TABS = ["home", "wallet", "copy", "strategies", "notifs", "more"];

async function dispatch() {
  let hash = location.hash.slice(1);
  if (!hash || /tgwebapp/i.test(hash) || !KNOWN_TABS.includes(hash.split("/")[0])) {
    hash = "home"; history.replaceState(null, "", "#home");
  }
  const topTab = hash.split("/")[0];
  for (const r of routes) {
    const m = hash.match(r.pattern);
    if (m) {
      setTab(r.opts.tab || topTab);
      setBack(r.opts.back || null);
      clearMainBtn();
      window.scrollTo(0, 0);
      try { render(skeleton()); await r.handler(m); }
      catch (e) {
        const msg = (e && (e.message || e.toString())) || "Une erreur s'est produite (sans détail)";
        console.error("Route error", hash, e);
        showError(msg);
      }
      return;
    }
  }
  history.replaceState(null, "", "#home"); location.hash = "home";
}
function showError(msg) {
  const detail = msg && String(msg).trim() ? String(msg) : "Erreur inconnue (aucun message). Vérifiez les logs Docker du bot.";
  render(`
    <div class="empty">
      <div class="empty-icon">⚠️</div>
      <div class="empty-title" style="color:var(--red)">Erreur</div>
      <div class="empty-text" style="word-break:break-word">${esc(detail)}</div>
      <div style="display:grid;gap:10px;margin-top:16px;max-width:280px;margin-left:auto;margin-right:auto">
        <button class="btn btn-primary" onclick="dispatch()">⟳ Réessayer</button>
        <button class="btn btn-secondary" onclick="go('home')">🏠 Retour accueil</button>
      </div>
    </div>`);
}

/* ═══════════════════════════════════════════════════ HOME */
route(/^home$/, async () => {
  const me = APP.user;
  const [copyStats, stratStats, week, recent, ctrl] = await Promise.all([
    cached("copy-stats", () => api("/copy/stats")),
    cached("strat-stats", () => api("/strategies/stats")),
    cached("pnl-week", () => api("/reports/pnl?period=week")),
    cached("recent", () => api("/copy/trades?limit=5")),
    cached("ctrl-status", () => api("/controls/status"), 5000),
  ]);
  const totalPnl = (copyStats.total_pnl || 0) + (stratStats.total_pnl || 0);

  let ctrlBanner = "";
  if (ctrl.state === "paused") ctrlBanner = `<div class="alert warning"><h4>⏸ Copy trading en pause</h4><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="window._ctrlResume()">▶ Reprendre</button></div>`;
  else if (ctrl.state === "stopped") ctrlBanner = `<div class="alert"><h4>⏹ Copy trading arrêté</h4><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="window._ctrlResume()">✓ Réactiver</button></div>`;

  let balanceCard = "";
  if (me.wallet_address) {
    try {
      const bal = await cached("wallet-bal", () => api("/wallet/balance"), 15000);
      const usedBadge = me.paper_trading
        ? badge("📝 PAPER actif", "orange")
        : badge("💵 LIVE actif", "green");
      const rpcWarn = (bal.usdc_error || bal.matic_error)
        ? `<div class="small" style="color:var(--orange);margin-top:6px">⚠ ${esc(bal.usdc_error || bal.matic_error)}</div>` : "";
      balanceCard = `
        <div class="card">
          <div class="card-header">
            <div class="tiny">Soldes · ${stateBadge(me)}</div>
            <a class="card-action" onclick="go('wallet')">Gérer ›</a>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
            <div class="balance-cell ${me.paper_trading?'is-active':''}">
              <div class="tiny">📝 Paper</div>
              <div style="font-size:18px;font-weight:700">${fmtUsd(me.paper_balance)}</div>
              <div class="small">USDC fictif</div>
            </div>
            <div class="balance-cell ${!me.paper_trading?'is-active':''}">
              <div class="tiny">💵 Live (on-chain)</div>
              <div style="font-size:18px;font-weight:700">${fmtUsd(bal.usdc)}</div>
              <div class="small">${bal.matic.toFixed(4)} MATIC</div>
            </div>
          </div>
          <div style="margin-top:8px">${usedBadge}<span class="small" style="margin-left:6px">utilisé pour les trades</span></div>
          ${rpcWarn}
          <div class="btn-row" style="margin-top:12px">
            <button class="btn btn-primary btn-sm" onclick="go('wallet/copy/deposit')">📥 Déposer</button>
            <button class="btn btn-secondary btn-sm" onclick="go('wallet/copy/withdraw')">📤 Retirer</button>
          </div>
        </div>`;
    } catch { balanceCard = `<div class="card"><div class="small">Balance indisponible</div></div>`; }
  } else {
    balanceCard = `<div class="alert info"><h4>👛 Configurez votre wallet</h4><button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="go('wallet')">Configurer</button></div>`;
  }

  const controlRow = ctrl.state === "running" ? `<button class="btn btn-secondary" onclick="window._ctrlPause()" style="margin-bottom:12px">⏸ Mettre en pause</button>` : "";

  render(`
    ${modeBadge(me)}
    ${ctrlBanner}
    <div class="hero"><div class="hero-value ${pnlClass(totalPnl)}">${pnlSign(totalPnl)}</div><div class="hero-label">PnL total · ${me.paper_trading ? "paper" : "live"}</div></div>
    ${balanceCard}
    ${controlRow}
    <div class="quick-grid">
      <button class="quick-action" onclick="go('copy/traders')"><div class="quick-action-icon">👥</div><div class="quick-action-label">Traders · ${me.followed_wallets_count}</div></button>
      <button class="quick-action" onclick="go('copy/discover')"><div class="quick-action-icon">🔍</div><div class="quick-action-label">Découvrir</div></button>
      <button class="quick-action" onclick="go('copy/positions')"><div class="quick-action-icon">📊</div><div class="quick-action-label">Positions · ${copyStats.open_positions}</div></button>
      <button class="quick-action" onclick="go('strategies')"><div class="quick-action-icon">🎯</div><div class="quick-action-label">Stratégies · ${me.active_subscriptions}</div></button>
    </div>
    <div class="section">
      ${sectionTitle("7 derniers jours")}
      ${statsGrid([
        {value: pnlSign(week.pnl), label: "PnL", cls: pnlClass(week.pnl)},
        {value: week.trades, label: "Trades"},
        {value: fmtPct(week.win_rate), label: "Win rate"},
        {value: copyStats.open_positions, label: "Positions"},
      ], 4)}
    </div>
    <div class="section">
      ${sectionTitle("Activité récente", recent.trades.length ? {label:"Voir tout", onclick:"go('copy/history')"} : null)}
      ${recent.trades.length === 0
        ? `<div class="card"><div class="empty" style="padding:24px 0"><div class="empty-text">Aucun trade</div></div></div>`
        : `<div class="card card-flush"><div class="list">${recent.trades.slice(0,5).map(t => `
            <div class="list-item">
              <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
              <div class="list-body">
                <div class="list-title">${esc(t.market_question)}</div>
                <div class="list-sub">${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
              </div>
              <div class="list-right">${t.settlement_pnl !== null ? `<span class="${pnlClass(t.settlement_pnl)}">${pnlSign(t.settlement_pnl)}</span>` : `<span class="small">${fmtUsd(t.amount)}</span>`}</div>
            </div>`).join("")}</div></div>`}
    </div>
  `);
});

window._ctrlPause = async function() {
  const ok = await confirmModal("Mettre en pause ?", "Le copy trading s'arrêtera temporairement.", "Mettre en pause");
  if (!ok) return;
  await api("/controls/pause", {method:"POST"}); invalidate("ctrl"); toast("En pause"); dispatch();
};
window._ctrlResume = async function() {
  await api("/controls/resume", {method:"POST"}); invalidate("ctrl"); toast("Reprise ✓"); dispatch();
};
window._toggleMode = async function(toPaper) {
  if (toPaper) {
    const ok = await confirmModal("Passer en Paper ?", "Trades simulés, aucun USDC réel.", "Passer en Paper");
    if (!ok) return;
    await api("/user/mode", {method:"POST", body:{paper_trading: true}});
    toast("Mode Paper activé"); invalidateAll(); await loadUser(); dispatch();
  } else {
    const ok1 = await confirmModal("⚠ Passer en LIVE ?", `ATTENTION — Trades RÉELS avec votre USDC.\nIRRÉVERSIBLE.\n\nWallet : ${shortAddr(APP.user.wallet_address || '')}`, "Je confirme, passer en Live", "danger");
    if (!ok1) return;
    const ok2 = await confirmModal("Dernière confirmation", "Vos fonds réels seront à risque.", "OUI, activer le LIVE", "danger");
    if (!ok2) return;
    try {
      await api("/user/mode", {method:"POST", body:{paper_trading: false, confirm_live: true}});
      toast("⚠ Mode LIVE activé", "warning"); invalidateAll(); await loadUser(); dispatch();
    } catch (e) { toast(e.message, "error"); }
  }
};

/* ═══════════════════════════════════════════════════ WALLET (unified) */
route(/^wallet$/, async () => { go("wallet/copy"); });

const walletNav = (active) => subNav([
  {label:"💰 Copy", href:"wallet/copy"},
  {label:"🎯 Stratégie", href:"wallet/strategy"},
], active);

/* ── Wallet COPY ── */
route(/^wallet\/copy$/, async () => {
  const me = APP.user;
  if (!me.wallet_address) {
    render(`
      <div class="page-title">Wallet</div>
      ${walletNav("wallet/copy")}
      ${emptyState("👛", "Wallet Copy non configuré", "Créez un wallet Polygon ou importez une clé privée.")}
      <button class="btn btn-primary" onclick="go('wallet/copy/create')">✨ Créer un wallet</button>
      <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet/copy/import')">📥 Importer une clé</button>
    `);
    return;
  }
  const bal = await api("/wallet/balance").catch(() => ({usdc:0, matic:0, address:me.wallet_address, usdc_error:"Erreur réseau"}));
  const rpcErr = bal.usdc_error || bal.matic_error;
  render(`
    ${modeBadge(me)}
    <div class="page-title">Wallet</div>
    ${walletNav("wallet/copy")}

    <div class="card">
      <div class="card-title">💼 Soldes du wallet</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="balance-cell ${me.paper_trading?'is-active':''}">
          <div class="tiny">📝 Paper</div>
          <div style="font-size:24px;font-weight:700">${fmtUsd(me.paper_balance)}</div>
          <div class="small">Solde fictif (simulation)</div>
        </div>
        <div class="balance-cell ${!me.paper_trading?'is-active':''}">
          <div class="tiny">💵 Live (on-chain)</div>
          <div style="font-size:24px;font-weight:700">${fmtUsd(bal.usdc)}</div>
          <div class="small">${bal.matic.toFixed(4)} MATIC · gas</div>
        </div>
      </div>
      <div style="margin-top:10px">
        ${me.paper_trading ? badge("📝 PAPER actif", "orange") : badge("💵 LIVE actif", "green")}
        <span class="small" style="margin-left:6px">utilisé pour vos trades</span>
      </div>
      ${rpcErr ? `<div class="small" style="color:var(--orange);margin-top:6px">⚠ ${esc(rpcErr)}</div>` : ""}
    </div>

    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse Polygon (recevez USDC ici)</div>
      <div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="go('wallet/copy/deposit')">📥 Déposer</button>
      <button class="btn btn-secondary" onclick="go('wallet/copy/withdraw')">📤 Retirer</button>
    </div>

    <div class="section">
      ${sectionTitle("💰 Réclamer mes gains")}
      <div id="redeem-card"></div>
    </div>

    <div class="section">
      ${sectionTitle("Avancé")}
      <div class="card card-flush"><div class="list">
        <div class="list-item" onclick="go('wallet/copy/export')">
          <div class="list-icon">🔐</div>
          <div class="list-body"><div class="list-title">Exporter la clé privée</div></div>
          <div class="list-chevron">›</div>
        </div>
        <div class="list-item" onclick="window._walletDelete('copy')">
          <div class="list-icon" style="background:rgba(255,69,58,0.15)">🗑</div>
          <div class="list-body"><div class="list-title" style="color:var(--red)">Supprimer</div></div>
          <div class="list-chevron">›</div>
        </div>
      </div></div>
    </div>
  `);
  // Async load (so the wallet page renders fast)
  loadRedeemCard();
}, {tab: "wallet"});

async function loadRedeemCard() {
  const el = document.getElementById("redeem-card");
  if (!el) return;
  try {
    const r = await api("/positions/redeemable");
    if (!r.items || r.items.length === 0) {
      el.innerHTML = `<div class="card"><div class="small" style="text-align:center;padding:8px 0">✓ Aucun gain en attente. Tous vos USDC ont été perçus.</div></div>`;
      return;
    }
    el.innerHTML = `
      <div class="alert info">
        <h4>🎉 ${r.count} position(s) gagnante(s) à réclamer</h4>
        <p>Total estimé : <b>${fmtUsd(r.total_expected_usdc)}</b>. Sur Polymarket, cliquez "Redeem" pour récupérer ces USDC dans votre wallet.</p>
      </div>
      <a class="btn btn-primary" href="${r.polymarket_portfolio_url}" target="_blank" style="margin-bottom:10px">🌐 Réclamer sur Polymarket ↗</a>
      <div class="card card-flush"><div class="list">
        ${r.items.slice(0, 10).map(it => `
          <div class="list-item">
            <div class="list-icon" style="background:rgba(52,199,89,0.15)">🎉</div>
            <div class="list-body">
              <div class="list-title">${esc(it.market_question)}</div>
              <div class="list-sub">${it.shares.toFixed(2)} sh · résultat ${esc(it.outcome)} · gain ${fmtUsd(it.expected_payout)}</div>
            </div>
            <div class="list-right pnl-pos" style="font-weight:600">${pnlSign(it.pnl)}</div>
          </div>`).join("")}
      </div></div>
      <div class="alert warning" style="margin-top:10px">
        <h4>⚙️ Note technique</h4>
        <p>Le redeem on-chain (appel <code>redeemPositions</code> sur le contrat Conditional Tokens) n'est pas encore automatisé. Cliquez le bouton ci-dessus, Polymarket vous fait redeemer en 2 clics — ça prend 10 sec.</p>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><div class="small">Impossible de charger les gains à réclamer (${esc(e.message)})</div></div>`;
  }
}

/* ── Wallet STRATÉGIE ── */
route(/^wallet\/strategy$/, async () => {
  const me = APP.user;
  if (!me.strategy_wallet_address) {
    render(`
      <div class="page-title">Wallet</div>
      ${walletNav("wallet/strategy")}
      ${emptyState("🎯", "Wallet Stratégie non configuré", "Wallet dédié aux stratégies automatisées, séparé du copy trading.")}
      <button class="btn btn-primary" id="sw-create">✨ Créer un wallet</button>
      <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet/strategy/import')">📥 Importer une clé</button>
    `);
    document.getElementById("sw-create").onclick = async () => {
      const ok = await confirmModal("Créer wallet stratégie ?", "La clé sera affichée UNE SEULE FOIS.", "Créer");
      if (!ok) return;
      try {
        const r = await api("/strategy-wallet/create", {method:"POST"});
        invalidateAll(); await loadUser();
        render(`
          <div class="page-title">✅ Wallet créé</div>
          <div class="alert"><h4>⚠ Sauvegardez MAINTENANT</h4></div>
          <div class="card">
            <div class="tiny" style="margin-bottom:6px">Adresse</div>
            <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
            <div class="tiny" style="margin:14px 0 6px">Clé privée</div>
            <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)" onclick="copy('${r.private_key}')">${r.private_key}</div>
            <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
          </div>
          <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet/strategy')">OK</button>
        `);
      } catch (e) { toast(e.message, "error"); }
    };
    return;
  }
  const bal = await api("/strategy-wallet/balance").catch(() => ({usdc:0, matic:0, address:me.strategy_wallet_address, usdc_error:"Erreur réseau"}));
  const rpcErr = bal.usdc_error || bal.matic_error;
  render(`
    <div class="page-title">Wallet</div>
    ${walletNav("wallet/strategy")}

    <div class="card">
      <div class="card-title">🎯 Solde wallet stratégie</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="balance-cell is-active">
          <div class="tiny">💵 USDC</div>
          <div style="font-size:24px;font-weight:700">${fmtUsd(bal.usdc)}</div>
          <div class="small">disponible pour stratégies</div>
        </div>
        <div class="balance-cell">
          <div class="tiny">⛽ MATIC</div>
          <div style="font-size:24px;font-weight:700">${bal.matic.toFixed(4)}</div>
          <div class="small">gas Polygon</div>
        </div>
      </div>
      ${rpcErr ? `<div class="small" style="color:var(--orange);margin-top:6px">⚠ ${esc(rpcErr)}</div>` : ""}
    </div>

    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse Polygon (recevez USDC ici)</div>
      <div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" onclick="go('wallet/strategy/deposit')">📥 Déposer</button>
      <button class="btn btn-secondary" onclick="go('wallet/strategy/withdraw')">📤 Retirer</button>
    </div>

    <div class="section">
      ${sectionTitle("Avancé")}
      <div class="card card-flush"><div class="list">
        <div class="list-item" onclick="go('wallet/strategy/export')">
          <div class="list-icon">🔐</div>
          <div class="list-body"><div class="list-title">Exporter la clé privée</div></div>
          <div class="list-chevron">›</div>
        </div>
        <div class="list-item" onclick="window._walletDelete('strategy')">
          <div class="list-icon" style="background:rgba(255,69,58,0.15)">🗑</div>
          <div class="list-body"><div class="list-title" style="color:var(--red)">Supprimer ce wallet</div></div>
          <div class="list-chevron">›</div>
        </div>
      </div></div>
    </div>
  `);
}, {tab: "wallet"});

route(/^wallet\/strategy\/deposit$/, async () => {
  const me = APP.user;
  render(`
    <div class="page-title">Déposer (Stratégie)</div>
    <div class="alert info">
      <h4>ℹ Instructions</h4>
      <p>• Réseau : <b>Polygon</b><br>• Token : <b>USDC.e</b><br>• Ajoutez du <b>MATIC</b> (0.1) pour le gas<br>• Crédité ~3 sec</p>
    </div>
    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse de dépôt — wallet stratégie</div>
      <div class="addr-box mono" onclick="copy('${me.strategy_wallet_address}')">${me.strategy_wallet_address}</div>
      <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${me.strategy_wallet_address}')">📋 Copier l'adresse</button>
    </div>
  `);
  setBack("wallet/strategy");
}, {tab: "wallet", back: "wallet/strategy"});

route(/^wallet\/strategy\/withdraw$/, async () => {
  const bal = await api("/strategy-wallet/balance");
  render(`
    <div class="page-title">Retirer (Stratégie)</div>
    <div class="hero" style="padding:20px"><div class="hero-value">${fmtUsd(bal.usdc)}</div><div class="hero-label">Disponible · wallet stratégie</div></div>
    <div class="card">
      <div class="form-row">
        <label class="label">Adresse destination</label>
        <input class="input input-mono" id="to-addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
      </div>
      <div class="form-row">
        <label class="label">Montant USDC</label>
        <div class="input-with-max">
          <input class="input" id="amount" type="number" step="0.01" placeholder="0.00" />
          <button class="input-max-btn" onclick="document.getElementById('amount').value=${bal.usdc}">MAX</button>
        </div>
      </div>
    </div>
    <div class="alert warning">
      <p>Le retrait sort des fonds depuis le wallet stratégie (différent du copy wallet).</p>
    </div>
  `);
  setBack("wallet/strategy");
  setMainBtn("ENVOYER", async () => {
    const to = document.getElementById("to-addr").value.trim();
    const amt = parseFloat(document.getElementById("amount").value);
    if (!to.startsWith("0x") || to.length !== 42) return toast("Adresse invalide", "error");
    if (!amt || amt <= 0) return toast("Montant invalide", "error");
    if (amt > bal.usdc) return toast("Solde insuffisant", "error");
    const ok = await confirmModal("Confirmer retrait", `Envoyer ${fmtUsd(amt)} USDC depuis le wallet STRATÉGIE à ${shortAddr(to)} ?\nIrréversible.`, "Envoyer");
    if (!ok) return;
    try {
      clearMainBtn(); toast("Transaction en cours…");
      const r = await api("/strategy-wallet/withdraw", {method:"POST", body:{to_address: to, amount: amt}});
      invalidateAll();
      render(`
        <div class="empty" style="padding:40px 20px"><div class="empty-icon">✅</div><div class="empty-title" style="color:var(--green)">Retrait envoyé</div></div>
        <div class="card">
          <div class="tiny" style="margin-bottom:8px">Transaction hash</div>
          <div class="addr-box mono" onclick="copy('${r.tx_hash}')">${r.tx_hash}</div>
          <a class="btn btn-secondary" href="https://polygonscan.com/tx/${r.tx_hash}" target="_blank" style="margin-top:12px">Voir sur Polygonscan ↗</a>
        </div>
        <button class="btn btn-primary" onclick="go('wallet/strategy')">Retour</button>
      `);
      setBack("wallet/strategy");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet/strategy"});

route(/^wallet\/strategy\/export$/, async () => {
  render(`
    <div class="page-title">Exporter clé stratégie</div>
    <div class="alert"><h4>🔐 Zone dangereuse</h4><p>Contrôle <b>total</b> du wallet stratégie. Ne partagez JAMAIS.</p></div>
    <div class="card">
      <label class="toggle-row"><div class="toggle-label">Je comprends les risques</div><div class="toggle"><input type="checkbox" id="c1"><span class="slider"></span></div></label>
      <label class="toggle-row"><div class="toggle-label">Je ne suis pas en public</div><div class="toggle"><input type="checkbox" id="c2"><span class="slider"></span></div></label>
    </div>
    <button class="btn btn-danger" id="exp-btn">Afficher la clé</button>
  `);
  setBack("wallet/strategy");
  document.getElementById("exp-btn").onclick = async () => {
    if (!document.getElementById("c1").checked || !document.getElementById("c2").checked) return toast("Cochez les deux cases", "error");
    try {
      const r = await api("/strategy-wallet/export-pk", {method:"POST", body:{confirm: true}});
      render(`
        <div class="page-title">🔐 Clé privée stratégie</div>
        <div class="alert"><h4>⚠ Copiez maintenant</h4></div>
        <div class="card">
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
        </div>
        <button class="btn btn-secondary" onclick="go('wallet/strategy')">Terminé</button>
      `);
      setBack("wallet/strategy");
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "wallet", back: "wallet/strategy"});

/* ── Wallet Copy sub-routes ── */
window._walletDelete = async function(which) {
  const ok = await confirmModal("Supprimer ce wallet ?", "La clé privée sera effacée.", "Supprimer", "danger");
  if (!ok) return;
  await api(which === "strategy" ? "/strategy-wallet" : "/wallet", {method:"DELETE"});
  invalidateAll(); toast("Supprimé"); await loadUser(); go("wallet/" + which);
};

route(/^wallet\/copy\/create$/, async () => {
  render(`
    <div class="page-title">Créer un wallet Copy</div>
    <div class="alert warning"><h4>⚠ Attention</h4><p>La clé privée sera affichée <b>UNE SEULE FOIS</b>.</p></div>
    <button class="btn btn-primary" id="create-btn">✨ Générer mon wallet</button>
  `);
  setBack("wallet/copy");
  document.getElementById("create-btn").onclick = async () => {
    try {
      const r = await api("/wallet/create", {method:"POST"});
      invalidateAll(); await loadUser();
      render(`
        <div class="page-title">✅ Wallet créé</div>
        <div class="alert"><h4>⚠ Sauvegardez MAINTENANT</h4></div>
        <div class="card">
          <div class="tiny" style="margin-bottom:6px">Adresse</div>
          <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
          <div class="tiny" style="margin:14px 0 6px">Clé privée</div>
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)" onclick="copy('${r.private_key}')">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
        </div>
        <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet/copy')">J'ai sauvegardé</button>
      `);
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "wallet", back: "wallet/copy"});

route(/^wallet\/copy\/import$/, async () => {
  render(`
    <div class="page-title">Importer Copy wallet</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Clé privée</label>
        <textarea class="input input-mono" id="pk-input" rows="3" placeholder="0x..." autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
        <div class="input-hint">64 caractères hex</div>
      </div>
    </div>
  `);
  setBack("wallet/copy");
  setMainBtn("IMPORTER", async () => {
    const pk = document.getElementById("pk-input").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try { const r = await api("/wallet/import", {method:"POST", body:{private_key: pk}}); invalidateAll(); await loadUser(); toast("Importé"); go("wallet/copy"); }
    catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet/copy"});

route(/^wallet\/copy\/deposit$/, async () => {
  const me = APP.user;
  render(`
    <div class="page-title">Déposer</div>
    <div class="alert info">
      <h4>ℹ Instructions</h4>
      <p>• Réseau : <b>Polygon</b> uniquement<br>• Token : <b>USDC.e</b><br>• Ajoutez du <b>MATIC</b> (0.1) pour le gas<br>• Crédit ~3 sec</p>
    </div>
    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse de dépôt</div>
      <div class="addr-box mono" onclick="copy('${me.wallet_address}')">${me.wallet_address}</div>
      <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${me.wallet_address}')">📋 Copier</button>
    </div>
  `);
  setBack("wallet/copy");
}, {tab: "wallet", back: "wallet/copy"});

route(/^wallet\/copy\/withdraw$/, async () => {
  const bal = await api("/wallet/balance");
  render(`
    <div class="page-title">Retirer</div>
    <div class="hero" style="padding:20px"><div class="hero-value">${fmtUsd(bal.usdc)}</div><div class="hero-label">Disponible</div></div>
    <div class="card">
      <div class="form-row">
        <label class="label">Adresse destination</label>
        <input class="input input-mono" id="to-addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
      </div>
      <div class="form-row">
        <label class="label">Montant USDC</label>
        <div class="input-with-max">
          <input class="input" id="amount" type="number" step="0.01" placeholder="0.00" />
          <button class="input-max-btn" onclick="document.getElementById('amount').value=${bal.usdc}">MAX</button>
        </div>
      </div>
    </div>
  `);
  setBack("wallet/copy");
  setMainBtn("ENVOYER", async () => {
    const to = document.getElementById("to-addr").value.trim();
    const amt = parseFloat(document.getElementById("amount").value);
    if (!to.startsWith("0x") || to.length !== 42) return toast("Adresse invalide", "error");
    if (!amt || amt <= 0) return toast("Montant invalide", "error");
    if (amt > bal.usdc) return toast("Solde insuffisant", "error");
    const ok = await confirmModal("Confirmer retrait", `Envoyer ${fmtUsd(amt)} à ${shortAddr(to)} ?\nIrréversible.`, "Envoyer");
    if (!ok) return;
    try {
      clearMainBtn(); toast("Transaction en cours…");
      const r = await api("/wallet/withdraw", {method:"POST", body:{to_address: to, amount: amt}});
      invalidate("wallet");
      render(`
        <div class="empty" style="padding:40px 20px"><div class="empty-icon">✅</div><div class="empty-title" style="color:var(--green)">Retrait envoyé</div></div>
        <div class="card">
          <div class="tiny" style="margin-bottom:8px">Transaction hash</div>
          <div class="addr-box mono" onclick="copy('${r.tx_hash}')">${r.tx_hash}</div>
          <a class="btn btn-secondary" href="https://polygonscan.com/tx/${r.tx_hash}" target="_blank" style="margin-top:12px">Voir sur Polygonscan ↗</a>
        </div>
        <button class="btn btn-primary" onclick="go('wallet/copy')">Retour</button>
      `);
      setBack("wallet/copy");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet/copy"});

route(/^wallet\/copy\/export$/, async () => {
  render(`
    <div class="page-title">Exporter la clé privée</div>
    <div class="alert"><h4>🔐 Zone dangereuse</h4><p>Contrôle <b>total</b> du wallet. Ne partagez JAMAIS.</p></div>
    <div class="card">
      <label class="toggle-row"><div class="toggle-label">Je comprends les risques</div><div class="toggle"><input type="checkbox" id="c1"><span class="slider"></span></div></label>
      <label class="toggle-row"><div class="toggle-label">Je ne suis pas en public</div><div class="toggle"><input type="checkbox" id="c2"><span class="slider"></span></div></label>
    </div>
    <button class="btn btn-danger" id="exp-btn">Afficher la clé</button>
  `);
  setBack("wallet/copy");
  document.getElementById("exp-btn").onclick = async () => {
    if (!document.getElementById("c1").checked || !document.getElementById("c2").checked) return toast("Cochez les deux cases", "error");
    try {
      const r = await api("/wallet/export-pk", {method:"POST", body:{confirm: true}});
      render(`
        <div class="page-title">🔐 Clé privée</div>
        <div class="alert"><h4>⚠ Copiez maintenant</h4></div>
        <div class="card">
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
        </div>
        <button class="btn btn-secondary" onclick="go('wallet/copy')">Terminé</button>
      `);
      setBack("wallet/copy");
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "wallet", back: "wallet/copy"});

route(/^wallet\/strategy\/import$/, async () => {
  render(`
    <div class="page-title">Importer clé stratégie</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Clé privée</label>
        <textarea class="input input-mono" id="sw-pk" rows="3" placeholder="0x..."></textarea>
      </div>
    </div>
  `);
  setBack("wallet/strategy");
  setMainBtn("IMPORTER", async () => {
    const pk = document.getElementById("sw-pk").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try { await api("/strategy-wallet/import", {method:"POST", body:{private_key: pk}}); invalidateAll(); await loadUser(); toast("Importé"); go("wallet/strategy"); }
    catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet/strategy"});

/* ═══════════════════════════════════════════════════ COPY (avec Découvrir) */
route(/^copy$/, async () => { go("copy/traders"); });

const copyNav = (active, counts) => subNav([
  {label:"Traders", href:"copy/traders", count: counts?.traders},
  {label:"🔍 Découvrir", href:"copy/discover"},
  {label:"Positions", href:"copy/positions", count: counts?.positions},
  {label:"Historique", href:"copy/history"},
], active);

route(/^copy\/traders$/, async () => {
  const [traders, positions] = await Promise.all([
    api("/copy/traders"),
    cached("copy-positions", () => api("/copy/positions")),
  ]);
  render(`
    ${modeBadge(APP.user)}
    <div class="page-title">Copy Trading</div>
    ${copyNav("copy/traders", {traders: traders.count, positions: positions.count})}
    ${traders.count === 0
      ? `<div class="empty">
          <div class="empty-icon">👥</div>
          <div class="empty-title">Aucun trader suivi</div>
          <div class="empty-text">Ajoutez un trader par son adresse Polygon, ou parcourez le classement des top traders dans l'onglet Découvrir.</div>
          <div style="display:grid;gap:10px;max-width:280px;margin:16px auto 0">
            <button class="btn btn-primary" onclick="go('copy/traders/add')">+ Ajouter par adresse</button>
            <button class="btn btn-secondary" onclick="go('copy/discover')">🔍 Découvrir les top traders</button>
          </div>
        </div>`
      : `<div class="card card-flush"><div class="list">
          ${traders.traders.map(t => `
            <div class="list-item">
              <div class="avatar" onclick="go('copy/trader/${t.wallet}')" style="cursor:pointer">${t.wallet_short.slice(2,4).toUpperCase()}</div>
              <div class="list-body" onclick="go('copy/trader/${t.wallet}')" style="cursor:pointer">
                <div class="list-title mono">${t.wallet_short}</div>
                <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
              </div>
              <div class="list-right" style="display:flex;align-items:center;gap:8px">
                <div class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>
                <button class="btn btn-danger btn-icon" onclick="window._trUnfollow('${t.wallet}')" title="Ne plus suivre" style="flex-shrink:0">🗑</button>
              </div>
            </div>`).join("")}
        </div></div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn btn-primary btn-sm" onclick="go('copy/traders/add')">+ Ajouter par adresse</button>
          <button class="btn btn-secondary btn-sm" onclick="go('copy/discover')">🔍 Découvrir</button>
        </div>`
    }
  `);
}, {tab: "copy"});

/* Découvrir sous Copy — scrape du leaderboard Polymarket par période */
route(/^copy\/discover$/, async () => { go("copy/discover/month"); }, {tab: "copy"});

route(/^copy\/discover\/(day|week|month|all)$/, async (m) => {
  const period = m[1];
  const periodLabel = {day:"24h", week:"7 jours", month:"30 jours", all:"All-time"}[period];
  const [d, traders, positions] = await Promise.all([
    cached("discover-" + period, () => api("/discover/top-traders?period=" + period), 120000),
    cached("copy-traders", () => api("/copy/traders"), 10000),
    cached("copy-positions", () => api("/copy/positions")),
  ]);

  const hasError = !!d.error;
  const hasResults = (d.traders || []).length > 0;

  render(`
    <div class="page-title">🔍 Découvrir</div>
    ${copyNav("copy/discover", {traders: traders?.count || 0, positions: positions?.count || 0})}

    <div class="card" style="margin-bottom:12px">
      <div class="card-title">🏆 Top traders Polymarket — ${periodLabel}</div>
      <div class="small" style="margin-bottom:10px">Classement par profit. Tap un trader pour voir ses positions actuelles, ou "+ Suivre" pour copier ses prochains trades.</div>
      ${subNav([
        {label:"24h", href:"copy/discover/day"},
        {label:"7j", href:"copy/discover/week"},
        {label:"30j", href:"copy/discover/month"},
        {label:"All", href:"copy/discover/all"},
      ], "copy/discover/" + period)}
    </div>

    ${hasError ? `
      <div class="alert warning">
        <h4>⚠ Données indisponibles</h4>
        <p>${esc(d.error)}</p>
        <button class="btn btn-secondary btn-sm" style="margin-top:10px" onclick="invalidate('discover-');dispatch()">⟳ Réessayer</button>
      </div>
      <div class="alert info">
        <h4>💡 En attendant</h4>
        <p>Vous pouvez ajouter manuellement un trader si vous connaissez son adresse Polygon (0x...).</p>
        <button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="go('copy/traders/add')">+ Ajouter par adresse</button>
      </div>
    ` : ""}

    ${hasResults ? `
      <div class="card card-flush"><div class="list">${d.traders.map((t, i) => {
        const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : null;
        const avatarBg = i < 3 ? "linear-gradient(135deg,#ffd700,#ff8c00)" : "linear-gradient(135deg,var(--tg-btn),var(--purple))";
        return `
          <div class="list-item">
            <div class="avatar" style="background:${avatarBg};font-size:${medal?'18px':'14px'}">${medal || '#'+(i+1)}</div>
            <div class="list-body" onclick="go('copy/discover/trader/${t.wallet}')" style="cursor:pointer">
              <div class="list-title mono">${esc(t.username || t.wallet_short)}</div>
              <div class="list-sub">
                <span class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</span>
                ${t.volume > 0 ? ` · ${fmtUsd(t.volume)} vol` : ''}
              </div>
            </div>
            <div class="list-right">
              ${t.followed
                ? `<span class="badge badge-green">✓ Suivi</span>`
                : `<button class="btn btn-primary btn-sm" style="padding:6px 12px" onclick="window._follow('${t.wallet}', event)">+ Suivre</button>`}
            </div>
          </div>`;
      }).join("")}</div></div>
    ` : ""}

    ${!hasError && !hasResults ? emptyState("🔍", "Aucun trader trouvé", "Aucun résultat pour la période " + periodLabel + ".") : ""}
  `);
}, {tab: "copy"});

window._follow = async function(wallet, ev) {
  if (ev) ev.stopPropagation();
  try {
    const r = await api("/copy/traders/add", {method:"POST", body:{wallet}});
    invalidate("copy-"); invalidate("discover-");
    toast("✓ Trader ajouté");
    // Show clear confirmation about the "future trades only" behavior
    await confirmModal(
      "✓ Trader ajouté",
      (r.message || "Le bot commencera à copier ses prochains trades.") + "\n\n" +
      (r.note || "Les trades passés ne sont pas rétro-copiés."),
      "Compris"
    );
    dispatch();
  } catch (e) { toast(e.message, "error"); }
};

route(/^copy\/discover\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
  const wallet = m[1];
  const d = await api("/discover/trader/" + wallet + "/markets");
  const traders = await cached("copy-traders", () => api("/copy/traders"));
  const already = traders.traders.some(t => t.wallet.toLowerCase() === wallet.toLowerCase());
  render(`
    <div style="text-align:center;padding:12px 0 16px">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;margin:0 auto 10px">${wallet.slice(2,4).toUpperCase()}</div>
      <div class="h2 mono">${shortAddr(wallet)}</div>
      <div class="small" style="margin-top:2px">${d.markets.length} positions actives</div>
    </div>
    ${d.error ? `<div class="alert warning"><p>${esc(d.error)}</p></div>` : ""}
    ${d.markets.length === 0 && !d.error
      ? emptyState("📭", "Aucune position", "Ce trader n'a pas de position ouverte.")
      : `<div class="section">${sectionTitle("Positions actives")}<div class="card card-flush"><div class="list">
          ${d.markets.map(mk => `
            <div class="list-item">
              <div class="list-icon">${mk.pnl > 0 ? '🟢' : mk.pnl < 0 ? '🔴' : '⚪'}</div>
              <div class="list-body">
                <div class="list-title">${esc(mk.market_question)}</div>
                <div class="list-sub">${esc(mk.outcome)} @ ${mk.entry_price.toFixed(4)} → ${mk.current_price.toFixed(4)}</div>
              </div>
              <div class="list-right">
                <div class="${pnlClass(mk.pnl)}" style="font-weight:600">${pnlSign(mk.pnl)}</div>
                <div class="small">${fmtUsd(mk.current_value)}</div>
              </div>
            </div>`).join("")}
        </div></div></div>`}
    <button class="btn ${already?'btn-secondary':'btn-primary'}" style="margin-top:16px" onclick="window._follow('${wallet}')" ${already?'disabled':''}>
      ${already ? "✓ Déjà suivi" : "+ Suivre ce trader"}
    </button>
    <a class="btn btn-ghost" href="https://polymarket.com/profile/${wallet}" target="_blank" style="margin-top:8px">Voir sur Polymarket ↗</a>
  `);
  setBack("copy/discover/month");
}, {tab: "copy", back: "copy/discover/month"});

let _positionsTimer = null;
function _stopPositionsAutoRefresh() {
  if (_positionsTimer) { clearInterval(_positionsTimer); _positionsTimer = null; }
}

route(/^copy\/positions$/, async () => {
  _stopPositionsAutoRefresh();
  const traders = await cached("copy-traders", () => api("/copy/traders"));
  render(`
    <div class="page-title">Copy Trading</div>
    ${copyNav("copy/positions", {traders: traders?.count || 0})}
    <div id="positions-content"><div class="loading"><div class="spinner"></div>Chargement…</div></div>
  `);
  await window._loadPositions();
  // Auto-refresh every 15s tant qu'on est sur la page
  _positionsTimer = setInterval(() => {
    if (document.visibilityState === "visible" && location.hash.startsWith("#copy/positions")) {
      window._loadPositions();
    }
  }, 15000);
}, {tab: "copy"});

window._loadPositions = async function() {
  const el = document.getElementById("positions-content");
  if (!el) { _stopPositionsAutoRefresh(); return; }
  try {
    invalidate("copy-positions"); // bust cache for refresh
    const r = await api("/copy/positions");
    const liveCount = r.positions.filter(p => p.live).length;
    if (r.count === 0) {
      el.innerHTML = emptyState("📭", "Aucune position ouverte", "Les positions apparaîtront ici dès qu'un trade sera copié.");
      return;
    }
    el.innerHTML = `
      <div class="hero">
        <div class="hero-value ${pnlClass(r.total_unrealized_pnl)}">${pnlSign(r.total_unrealized_pnl)}</div>
        <div class="hero-label">PnL non-réalisé · ${r.count} positions</div>
      </div>
      ${statsGrid([
        {value: fmtUsd(r.total_invested), label: "Investi"},
        {value: fmtUsd(r.total_current_value), label: "Valeur actuelle"},
      ])}
      <div class="small" style="text-align:center;margin:8px 0">
        🔄 Actualisé toutes les 15s · ${liveCount}/${r.count} en suivi live
        <button class="btn btn-ghost btn-sm" onclick="window._loadPositions()" style="margin-left:8px;padding:2px 8px">⟳</button>
      </div>

      <div class="card card-flush"><div class="list">${r.positions.map(p => `
        <div class="list-item">
          <div class="list-icon">${p.unrealized_pnl > 0 ? '🟢' : p.unrealized_pnl < 0 ? '🔴' : '⚪'}</div>
          <div class="list-body">
            <div class="list-title">${esc(p.market_question)}</div>
            <div class="list-sub">${p.shares.toFixed(2)} sh · entry ${p.entry_price.toFixed(4)} → ${p.current_price.toFixed(4)} ${p.live?'🟢':''}</div>
            <div class="list-sub">${p.master_wallet}${p.is_paper ? ' · ' + badge("PAPER","orange") : ''}</div>
            <div class="list-sub" style="opacity:0.65">
              🕐 ${timeAgo(p.created_at)}
              ${p.execution_time_ms != null ? `· 🚀 latence <span class="${latencyClass(p.execution_time_ms)}">${fmtLatency(p.execution_time_ms)}</span>` : ""}
            </div>
          </div>
          <div class="list-right">
            <div class="${pnlClass(p.unrealized_pnl)}" style="font-weight:700;font-size:15px">${pnlSign(p.unrealized_pnl)}</div>
            <div class="small ${pnlClass(p.unrealized_pnl)}">${p.unrealized_pct >= 0 ? '+' : ''}${p.unrealized_pct.toFixed(1)}%</div>
            <div class="small" style="margin-top:2px">${fmtUsd(p.current_value)}</div>
          </div>
        </div>`).join("")}</div></div>
    `;
  } catch (e) {
    el.innerHTML = `<div class="alert"><p>Erreur: ${esc(e.message)}</p></div>`;
  }
};

// Stop refresh quand on quitte la page
window.addEventListener("hashchange", () => {
  if (!location.hash.startsWith("#copy/positions")) _stopPositionsAutoRefresh();
});

route(/^copy\/history$/, async () => {
  const {trades} = await api("/copy/trades?limit=50");
  const traders = await cached("copy-traders", () => api("/copy/traders"));
  const pos = await cached("copy-positions", () => api("/copy/positions"));
  render(`
    <div class="page-title">Copy Trading</div>
    ${copyNav("copy/history", {traders: traders.count, positions: pos.count})}
    ${trades.length === 0
      ? emptyState("📜", "Aucun trade", "Vos trades copiés apparaîtront ici.")
      : `<div class="card card-flush"><div class="list">${trades.map(t => `
          <div class="list-item">
            <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
            <div class="list-body">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${t.master_wallet} · ${timeAgo(t.created_at)}</div>
              ${t.execution_time_ms != null ? `<div class="list-sub" style="opacity:0.65">🚀 latence <span class="${latencyClass(t.execution_time_ms)}">${fmtLatency(t.execution_time_ms)}</span></div>` : ""}
            </div>
            <div class="list-right">
              ${t.settlement_pnl !== null ? `<div class="${pnlClass(t.settlement_pnl)}" style="font-weight:600">${pnlSign(t.settlement_pnl)}</div>` : `<div>${fmtUsd(t.amount)}</div>`}
              ${t.is_paper ? `<div style="margin-top:2px">${badge("P","orange")}</div>` : ""}
            </div>
          </div>`).join("")}</div></div>`}
  `);
}, {tab: "copy"});

route(/^copy\/traders\/add$/, async () => {
  render(`
    <div class="page-title">Ajouter par adresse</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Adresse Polygon du trader</label>
        <input class="input input-mono" id="addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
        <div class="input-hint">Ou utilisez 🔍 Découvrir pour trouver les meilleurs</div>
      </div>
    </div>
    <button class="btn btn-secondary" onclick="go('copy/discover')">🔍 Découvrir les top traders</button>
  `);
  setBack("copy/traders");
  setMainBtn("SUIVRE", async () => {
    const w = document.getElementById("addr").value.trim();
    if (!w) return toast("Adresse requise", "error");
    try {
      const r = await api("/copy/traders/add", {method:"POST", body:{wallet: w}});
      invalidate("copy-");
      toast("✓ Trader ajouté");
      await confirmModal(
        "✓ Trader ajouté",
        (r.message || "Le bot commencera à copier ses prochains trades.") + "\n\n" +
        (r.note || "Les trades passés ne sont pas rétro-copiés."),
        "Compris"
      );
      go("copy/traders");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "copy", back: "copy/traders"});

route(/^copy\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
  const wallet = m[1];
  const [d, filters, blacklist] = await Promise.all([
    api("/copy/traders/" + wallet + "/stats"),
    cached("trader-filters", () => api("/settings/trader-filters"), 10000),
    cached("blacklist", () => api("/copy/blacklist"), 10000),
  ]);
  const excluded = (filters.trader_filters || {})[wallet.toLowerCase()]?.excluded_categories || [];
  const blSet = new Set((blacklist.blacklist || []).map(m => m.toLowerCase()));

  render(`
    <div style="text-align:center;padding:16px 0 20px">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;margin:0 auto 10px">${wallet.slice(2,4).toUpperCase()}</div>
      <div class="h2 mono">${shortAddr(wallet)}</div>
      <div class="small" style="margin-top:2px">${d.trade_count} trades copiés par vous</div>
    </div>

    ${statsGrid([
      {value: fmtUsd(d.volume), label: "Volume"},
      {value: pnlSign(d.pnl), label: "PnL", cls: pnlClass(d.pnl)},
      {value: d.wins + "/" + d.losses, label: "W/L"},
      {value: fmtPct(d.win_rate), label: "Win rate"},
    ], 4)}
    <div class="small" style="text-align:center;margin:-6px 0 14px;opacity:0.7">
      ℹ Stats basées <b>uniquement</b> sur vos trades copiés de ce trader (pas sur son activité globale).
    </div>

    <!-- Générer un rapport pour ce trader -->
    <div class="section">
      <button class="btn btn-primary" onclick="window._reportForTrader('${wallet}')">
        📊 Faire un rapport de ce trader
      </button>
      <button class="btn btn-ghost btn-sm" style="margin-top:6px" onclick="window._reportForTraderMulti('${wallet}')">
        ➕ Rapport multi-traders (ajouter d'autres)
      </button>
    </div>

    <!-- Marchés actifs sur Polymarket (live) -->
    <div class="section">
      ${sectionTitle("📊 Marchés actifs sur Polymarket", {label:"Actualiser", onclick:"window._loadTraderMarkets('"+wallet+"')"})}
      <div class="small" style="margin-bottom:8px">Positions du trader triées du plus récent au plus ancien. Bloquez celles que vous ne voulez pas suivre.</div>
      <div id="trader-markets-card"><div class="loading"><div class="spinner"></div>Chargement marchés…</div></div>
    </div>

    <!-- Filtre par catégorie -->
    <div class="section">
      ${sectionTitle("🏷 Catégories exclues pour ce trader")}
      <div class="card">
        <div class="small" style="margin-bottom:10px">Plus large que blocage par marché : exclut tous les marchés d'une catégorie.</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${excluded.length === 0 ? '<span class="small">Aucune exclusion</span>' : excluded.map(c => `<span class="badge badge-red">${esc(c)}</span>`).join("")}
        </div>
        <button class="btn btn-secondary btn-sm" style="margin-top:10px" onclick="window._editTraderFilters('${wallet}')">Modifier les catégories</button>
      </div>
    </div>

    <!-- Derniers trades copiés (depuis ma DB) -->
    <div class="section">
      ${sectionTitle("📜 Derniers trades copiés")}
      ${d.recent_trades.length === 0
        ? `<div class="card"><div class="small" style="text-align:center;padding:20px 0">Aucun trade copié de ce trader pour le moment</div></div>`
        : `<div class="card card-flush"><div class="list">${d.recent_trades.map(t => `
            <div class="list-item">
              <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
              <div class="list-body">
                <div class="list-title">${esc(t.market_question)}</div>
                <div class="list-sub">${badge(t.side, t.side==='BUY'?'green':'red')} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
              </div>
              <div class="list-right">${t.pnl !== null ? `<span class="${pnlClass(t.pnl)}">${pnlSign(t.pnl)}</span>` : `<span>${fmtUsd(t.amount)}</span>`}</div>
            </div>`).join("")}</div></div>`}
    </div>

    <div class="section">
      <div class="card"><div class="addr-box mono" onclick="copy('${wallet}')">${wallet}</div></div>
      <a class="btn btn-ghost" href="https://polymarket.com/profile/${wallet}" target="_blank" style="margin-top:8px">Voir profil sur Polymarket ↗</a>
      <button class="btn btn-danger" style="margin-top:8px" onclick="window._trUnfollow('${wallet}')">🗑 Ne plus suivre</button>
    </div>
  `);
  setBack("copy/traders");
  // Async load markets (Polymarket API can be slow)
  window._loadTraderMarkets(wallet);
}, {tab: "copy", back: "copy/traders"});

window._loadTraderMarkets = async function(wallet) {
  const el = document.getElementById("trader-markets-card");
  if (!el) return;
  el.innerHTML = `<div class="loading"><div class="spinner"></div>Chargement marchés…</div>`;
  try {
    const [d, blacklist] = await Promise.all([
      api("/discover/trader/" + wallet + "/markets"),
      api("/copy/blacklist"),
    ]);
    const blSet = new Set((blacklist.blacklist || []).map(m => m.toLowerCase()));

    if (d.error) {
      el.innerHTML = `<div class="card"><div class="small">⚠ ${esc(d.error)}</div></div>`;
      return;
    }
    if (!d.markets || d.markets.length === 0) {
      el.innerHTML = `<div class="card"><div class="small" style="text-align:center;padding:16px 0">Ce trader n'a aucune position ouverte sur Polymarket actuellement.</div></div>`;
      return;
    }

    el.innerHTML = `<div class="card card-flush"><div class="list">${d.markets.map(mk => {
      const mid = (mk.market_id || mk.market_question || "").toLowerCase();
      const isBlocked = blSet.has(mid);
      const actTs = mk.last_activity_ts || 0;
      const actLabel = actTs > 0 ? timeAgo(new Date(actTs * 1000).toISOString()) : "—";
      return `
        <div class="list-item">
          <div class="list-icon">${mk.pnl > 0 ? '🟢' : mk.pnl < 0 ? '🔴' : '⚪'}</div>
          <div class="list-body">
            <div class="list-title">${esc(mk.market_question)}</div>
            <div class="list-sub">${esc(mk.outcome)} @ ${mk.entry_price?.toFixed(4) || '?'} → ${mk.current_price?.toFixed(4) || '?'} · ${fmtUsd(mk.current_value || 0)}</div>
            <div class="list-sub" style="opacity:0.6">🕐 Dernière activité : ${actLabel}</div>
          </div>
          <div class="list-right">
            ${isBlocked
              ? `<button class="btn btn-secondary btn-sm" onclick="window._unblockMarket('${mid}', '${wallet}')">✓ Débloquer</button>`
              : `<button class="btn btn-danger btn-sm" onclick="window._blockMarket('${mid}', '${esc(mk.market_question||'')}', '${wallet}')">🚫 Bloquer</button>`}
          </div>
        </div>`;
    }).join("")}</div></div>`;
  } catch (e) {
    el.innerHTML = `<div class="card"><div class="small">⚠ ${esc(e.message)}</div></div>`;
  }
};

window._blockMarket = async function(marketId, marketQuestion, wallet) {
  if (!marketId) return toast("ID marché invalide", "error");
  const ok = await confirmModal("Bloquer ce marché ?",
    `"${marketQuestion.slice(0, 80)}"\n\nLe bot ne copiera AUCUN trade sur ce marché, peu importe le trader.`,
    "Bloquer", "danger");
  if (!ok) return;
  try {
    await api("/copy/blacklist/add", {method:"POST", body:{market_id: marketId, market_question: marketQuestion}});
    invalidate("blacklist");
    toast("Marché bloqué ✓");
    window._loadTraderMarkets(wallet);
  } catch (e) { toast(e.message, "error"); }
};

window._unblockMarket = async function(marketId, wallet) {
  try {
    await api("/copy/blacklist/" + encodeURIComponent(marketId), {method:"DELETE"});
    invalidate("blacklist");
    toast("Marché débloqué");
    window._loadTraderMarkets(wallet);
  } catch (e) { toast(e.message, "error"); }
};

window._trUnfollow = async function(wallet) {
  const ok = await confirmModal("Arrêter de suivre ?", shortAddr(wallet), "Retirer", "danger");
  if (!ok) return;
  await api("/copy/traders/" + wallet, {method:"DELETE"});
  invalidate("copy-"); toast("Trader retiré"); go("copy/traders");
};

/* Rapport pré-configuré : UN seul trader */
window._reportForTrader = function(wallet) {
  REPORTS_STATE.traders_selected.clear();
  REPORTS_STATE.traders_selected.add(wallet.toLowerCase());
  toast("📊 Rapport configuré pour " + shortAddr(wallet));
  go("more/reports/traders");
};

/* Rapport multi-traders : pré-sélectionne ce trader + ouvre une modale pour cocher les autres */
window._reportForTraderMulti = async function(wallet) {
  REPORTS_STATE.traders_selected.clear();
  REPORTS_STATE.traders_selected.add(wallet.toLowerCase());

  const t = await api("/copy/traders");
  const others = (t.traders || []).filter(x => x.wallet.toLowerCase() !== wallet.toLowerCase());

  if (others.length === 0) {
    toast("Aucun autre trader suivi — rapport sur celui-ci");
    go("more/reports/traders");
    return;
  }

  const bd = document.createElement("div");
  bd.className = "sheet-backdrop";
  bd.innerHTML = `
    <div class="sheet">
      <h3>Rapport multi-traders</h3>
      <div class="sheet-sub">Cochez les traders à inclure dans le rapport (${shortAddr(wallet)} est déjà pré-sélectionné).</div>
      <div class="form-row" style="max-height:50vh;overflow-y:auto">
        <label class="toggle-row" style="opacity:0.6">
          <div>
            <div class="toggle-label mono">${shortAddr(wallet)}</div>
            <div class="toggle-sub">Trader principal (toujours inclus)</div>
          </div>
          <div class="toggle"><input type="checkbox" checked disabled><span class="slider"></span></div>
        </label>
        ${others.map(o => `
          <label class="toggle-row" style="cursor:pointer">
            <div>
              <div class="toggle-label mono">${o.wallet_short}</div>
              <div class="toggle-sub">${o.trade_count} trades · ${pnlSign(o.pnl)} PnL</div>
            </div>
            <div class="toggle"><input type="checkbox" data-tr-multi="${o.wallet.toLowerCase()}"><span class="slider"></span></div>
          </label>`).join("")}
      </div>
      <button class="btn btn-primary" id="go-report">📊 Générer le rapport</button>
      <button class="btn btn-ghost" id="close" style="margin-top:8px">Annuler</button>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener("click", e => { if (e.target === bd) bd.remove(); });
  bd.querySelector("#close").onclick = () => bd.remove();
  bd.querySelector("#go-report").onclick = () => {
    bd.querySelectorAll("[data-tr-multi]:checked").forEach(el => {
      REPORTS_STATE.traders_selected.add(el.dataset.trMulti);
    });
    bd.remove();
    toast(`📊 Rapport sur ${REPORTS_STATE.traders_selected.size} trader(s)`);
    go("more/reports/traders");
  };
};

window._editTraderFilters = async function(wallet) {
  const filters = await api("/settings/trader-filters");
  const excluded = (filters.trader_filters || {})[wallet.toLowerCase()]?.excluded_categories || [];
  const cats = ["Crypto", "Politics", "Sports", "Elections", "NFL", "NBA", "Soccer", "Tennis", "Boxing", "MMA", "Tech", "Science", "Culture", "Economy", "Weather"];
  const bd = document.createElement("div");
  bd.className = "sheet-backdrop";
  bd.innerHTML = `
    <div class="sheet">
      <h3>Filtres pour ${shortAddr(wallet)}</h3>
      <div class="sheet-sub">Cochez les catégories à EXCLURE.</div>
      <div class="form-row">
        ${cats.map(c => `
          <label class="toggle-row">
            <div class="toggle-label">${c}</div>
            <div class="toggle"><input type="checkbox" data-cat="${c}" ${excluded.includes(c)?"checked":""}><span class="slider"></span></div>
          </label>`).join("")}
      </div>
      <button class="btn btn-primary" id="save">💾 Enregistrer</button>
      <button class="btn btn-ghost" id="close" style="margin-top:8px">Fermer</button>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener("click", e => { if (e.target === bd) bd.remove(); });
  bd.querySelector("#close").onclick = () => bd.remove();
  bd.querySelector("#save").onclick = async () => {
    const picked = [...bd.querySelectorAll("[data-cat]:checked")].map(el => el.dataset.cat);
    try { await api("/settings/trader-filter", {method:"POST", body:{wallet, excluded_categories: picked}}); invalidate("trader-filters"); toast("Filtres enregistrés"); bd.remove(); dispatch(); }
    catch (e) { toast(e.message, "error"); }
  };
};

/* ═══════════════════════════════════════════════════ STRATEGIES */
route(/^strategies$/, async () => {
  const [{strategies}, stats, {subscriptions}] = await Promise.all([
    api("/strategies"),
    cached("strat-stats", () => api("/strategies/stats")),
    api("/strategies/subscriptions"),
  ]);
  const activeSubs = subscriptions.filter(s => s.is_active);
  const me = APP.user;
  let walletBanner = "";
  if (!me.strategy_wallet_address && activeSubs.length > 0) {
    walletBanner = `<div class="alert warning"><h4>⚠ Wallet stratégie manquant</h4><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="go('wallet/strategy')">Configurer</button></div>`;
  }
  render(`
    ${modeBadge(me)}
    <div class="page-title">Stratégies</div>
    ${subNav([
      {label:"Disponibles", href:"strategies", count: strategies.length},
      {label:"Mes abos", href:"strategies/my", count: activeSubs.length},
      {label:"Historique", href:"strategies/history"},
    ], "strategies")}
    ${walletBanner}
    ${statsGrid([
      {value: pnlSign(stats.total_pnl), label: "PnL", cls: pnlClass(stats.total_pnl)},
      {value: fmtPct(stats.win_rate), label: "Win rate"},
      {value: stats.total_trades, label: "Trades"},
      {value: activeSubs.length, label: "Abos"},
    ], 4)}
    <div class="section">
      ${strategies.length === 0
        ? emptyState("🎯", "Aucune stratégie", "Les stratégies publiques seront listées ici.")
        : strategies.map(s => `
          <div class="card" style="cursor:pointer" onclick="window._stratOpen('${s.id}')">
            <div class="card-header">
              <div class="h3">${esc(s.name)}</div>
              ${s.subscribed ? badge("Abonné", "green") : badge(s.status, "blue")}
            </div>
            ${s.description ? `<div class="small" style="margin-bottom:12px;line-height:1.5">${esc(s.description)}</div>` : ""}
            <div class="stats-inline">
              <div class="stat-mini"><div class="stat-value ${pnlClass(s.total_pnl)}">${pnlSign(s.total_pnl)}</div><div class="stat-label">PnL</div></div>
              <div class="stat-mini"><div class="stat-value">${fmtPct(s.win_rate)}</div><div class="stat-label">Win rate</div></div>
              <div class="stat-mini"><div class="stat-value">${s.total_trades}</div><div class="stat-label">Trades</div></div>
            </div>
          </div>`).join("")}
    </div>
  `);
});

route(/^strategies\/my$/, async () => {
  const [{strategies}, {subscriptions}] = await Promise.all([api("/strategies"), api("/strategies/subscriptions")]);
  const activeSubs = subscriptions.filter(s => s.is_active);
  render(`
    <div class="page-title">Stratégies</div>
    ${subNav([
      {label:"Disponibles", href:"strategies", count: strategies.length},
      {label:"Mes abos", href:"strategies/my", count: activeSubs.length},
      {label:"Historique", href:"strategies/history"},
    ], "strategies/my")}
    ${subscriptions.length === 0
      ? emptyState("📭", "Aucun abonnement", "Abonnez-vous pour commencer.", {label:"Voir les stratégies", onclick:"go('strategies')"})
      : `<div class="card card-flush"><div class="list">${subscriptions.map(s => `
          <div class="list-item" onclick="window._stratOpen('${s.strategy_id}')">
            <div class="list-icon">${s.is_active?'🎯':'⏸'}</div>
            <div class="list-body">
              <div class="list-title">${esc(s.strategy_name)}</div>
              <div class="list-sub">${fmtUsd(s.trade_size)} / trade · ${s.is_active ? "Actif" : "Pause"}</div>
            </div>
            <div class="list-chevron">›</div>
          </div>`).join("")}</div></div>`}
  `);
}, {tab: "strategies"});

route(/^strategies\/history$/, async () => {
  const {trades} = await api("/strategies/trades?limit=50");
  const [{strategies}, {subscriptions}] = await Promise.all([api("/strategies"), api("/strategies/subscriptions")]);
  const activeSubs = subscriptions.filter(s => s.is_active);
  render(`
    <div class="page-title">Stratégies</div>
    ${subNav([
      {label:"Disponibles", href:"strategies", count: strategies.length},
      {label:"Mes abos", href:"strategies/my", count: activeSubs.length},
      {label:"Historique", href:"strategies/history", count: trades.length},
    ], "strategies/history")}
    ${trades.length === 0
      ? emptyState("📜", "Aucun trade", "Les exécutions apparaîtront ici.")
      : `<div class="card card-flush"><div class="list">${trades.map(t => `
          <div class="list-item">
            <div class="list-icon">${t.result==='WON'?'✅':t.result==='LOST'?'❌':'⏳'}</div>
            <div class="list-body">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${esc(t.strategy_id)} · ${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
            </div>
            <div class="list-right">${t.pnl !== null ? `<div class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>` : `<div>${fmtUsd(t.amount)}</div>`}</div>
          </div>`).join("")}</div></div>`}
  `);
}, {tab: "strategies"});

window._stratOpen = async function(id) {
  const {strategies} = await api("/strategies");
  const s = strategies.find(x => x.id === id);
  if (!s) return toast("Stratégie introuvable", "error");
  const bd = document.createElement("div");
  bd.className = "sheet-backdrop";
  bd.innerHTML = `
    <div class="sheet">
      <h3>${esc(s.name)}</h3>
      ${s.description ? `<div class="sheet-sub">${esc(s.description)}</div>` : ""}
      <div class="stats" style="margin-bottom:16px">
        ${stat(pnlSign(s.total_pnl), "PnL", pnlClass(s.total_pnl))}
        ${stat(fmtPct(s.win_rate), "Win rate")}
      </div>
      <div class="form-row">
        <label class="label">Taille par trade (${s.min_trade_size} – ${s.max_trade_size} USDC)</label>
        <input class="input" id="ts" type="number" step="0.5" min="${s.min_trade_size}" max="${s.max_trade_size}" value="${s.my_trade_size || s.min_trade_size}">
      </div>
      ${s.subscribed
        ? `<button class="btn btn-primary" id="save">💾 Mettre à jour</button><button class="btn btn-danger" id="unsub" style="margin-top:8px">Désinscrire</button>`
        : `<button class="btn btn-primary" id="sub">✓ Souscrire</button>`}
      <button class="btn btn-ghost" id="close" style="margin-top:8px">Fermer</button>
    </div>`;
  document.body.appendChild(bd);
  bd.addEventListener("click", e => { if (e.target === bd) bd.remove(); });
  bd.querySelector("#close").onclick = () => bd.remove();
  const size = () => parseFloat(bd.querySelector("#ts").value);
  const done = () => { bd.remove(); invalidate("strat"); dispatch(); };
  if (s.subscribed) {
    bd.querySelector("#save").onclick = async () => {
      try { await api(`/strategies/${id}/subscription`, {method:"PATCH", body:{trade_size: size()}}); toast("Mis à jour"); done(); }
      catch (e) { toast(e.message, "error"); }
    };
    bd.querySelector("#unsub").onclick = async () => {
      const ok = await confirmModal("Désinscrire ?", `De "${s.name}".`, "Désinscrire", "danger");
      if (!ok) return;
      await api(`/strategies/${id}/unsubscribe`, {method:"POST"}); toast("Désinscrit"); done();
    };
  } else {
    bd.querySelector("#sub").onclick = async () => {
      try { await api(`/strategies/${id}/subscribe`, {method:"POST", body:{trade_size: size()}}); toast("Souscrit ✓"); done(); }
      catch (e) { toast(e.message, "error"); }
    };
  }
};

/* ═══════════════════════════════════════════════════ PLUS */
route(/^more$/, async () => {
  render(`
    <div class="page-title">Plus</div>
    <div class="card card-flush"><div class="list">
      <div class="list-item" onclick="go('more/settings')">
        <div class="list-icon">⚙️</div>
        <div class="list-body"><div class="list-title">Réglages</div><div class="list-sub">Mode, capital, risque, smart analysis</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/notifs-tg')">
        <div class="list-icon">🔔</div>
        <div class="list-body"><div class="list-title">Notifications Telegram</div><div class="list-sub">Destination + filtres événements</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/blacklist')">
        <div class="list-icon">🚫</div>
        <div class="list-body"><div class="list-title">Marchés bloqués</div><div class="list-sub">Gérer la liste des marchés à ne jamais copier</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/reports')">
        <div class="list-icon">📊</div>
        <div class="list-body"><div class="list-title">Rapports</div><div class="list-sub">PnL, traders, marchés · Export HTML/PDF</div></div>
        <div class="list-chevron">›</div>
      </div>
    </div></div>
    <div class="section">
      ${sectionTitle("Compte")}
      <div class="card">
        <div class="tiny" style="margin-bottom:6px">Utilisateur</div>
        <div>${esc(APP.user.username || "—")}</div>
        <div class="small" style="margin-top:2px">ID ${APP.user.telegram_id}</div>
      </div>
    </div>
    <div class="section" style="text-align:center;padding-top:20px"><div class="small">WENPOLYMARKET · v5</div></div>
  `);
});

/* ═══════════════════════════════════════════════════ SETTINGS */
route(/^more\/settings$/, async () => {
  const s = await api("/settings");
  const me = APP.user;
  const tgl = (key, label, sub, val) => `
    <label class="toggle-row">
      <div><div class="toggle-label">${label}</div>${sub ? `<div class="toggle-sub">${sub}</div>` : ""}</div>
      <div class="toggle"><input type="checkbox" data-key="${key}" ${val?"checked":""}><span class="slider"></span></div>
    </label>`;
  const num = (key, label, val, step=1, min=0, max=1000, hint, required=false) => `
    <div class="form-row"><label class="label ${required?'label-required':''}">${label}</label>
      <input class="input" type="number" data-key="${key}" value="${val ?? ""}" step="${step}" min="${min}" max="${max}">
      ${hint ? `<div class="input-hint">${hint}</div>` : ""}
    </div>`;
  const sel = (key, label, val, options, hint, required=false) => `
    <div class="form-row"><label class="label ${required?'label-required':''}">${label}</label>
      <select class="input" data-key="${key}">
        ${options.map(o => { const v=typeof o==='object'?o.value:o; const t=typeof o==='object'?o.label:o; return `<option value="${v}" ${v===val?"selected":""}>${t}</option>`; }).join("")}
      </select>
      ${hint ? `<div class="input-hint">${hint}</div>` : ""}
    </div>`;

  // Hint helper: "Recommandé X · Si Y → Z"
  const hint = (recommended, strategyTips) => {
    let h = `<b>✅ Recommandé : ${recommended}</b>`;
    if (strategyTips) h += `<br>${strategyTips}`;
    return h;
  };

  render(`
    <div class="page-title">Réglages</div>

    <div class="alert info" style="margin-bottom:14px">
      <h4>💡 Comment ça marche</h4>
      <p>• Cliquez sur chaque section pour la <b>déplier/replier</b><br>
      • Les champs marqués d'un <b style="color:var(--red)">*</b> sont <b>obligatoires</b><br>
      • Les paramètres <b>grisés</b> dépendent d'un toggle désactivé — activez le toggle parent pour les utiliser<br>
      • Pour copier <b>tout</b> sans filtre : cliquez <b>🔓 Mode permissif</b> plus bas</p>
    </div>

    <div class="card shortcuts-card" style="margin-bottom:14px">
      <div class="card-title">🎛 Raccourcis</div>

      <div class="permissive-row ${s.permissive_mode?'is-on':''}" onclick="window._togglePermissive(${!s.permissive_mode})">
        <div class="permissive-icon">${s.permissive_mode?'🔓':'🔒'}</div>
        <div class="permissive-body">
          <div class="permissive-title">Mode permissif</div>
          <div class="permissive-sub">${s.permissive_mode
            ? '✅ ACTIF — tous les filtres sont bypassés, le bot copie tout'
            : 'OFF — les filtres ci-dessous sont appliqués'}</div>
        </div>
        <div class="toggle"><input type="checkbox" ${s.permissive_mode?'checked':''}><span class="slider"></span></div>
      </div>

      <div class="btn-row cols-2" style="margin-top:12px">
        <button class="btn btn-secondary btn-sm" onclick="window._diagCopy()">🩺 Pourquoi pas copié ?</button>
        <button class="btn btn-ghost btn-sm" onclick="window._resetSettings()">♻️ Restaurer défauts</button>
      </div>
    </div>

    <details class="card" open>
      <summary>🔌 Mode de trading</summary>
      ${me.paper_trading
        ? `<div class="alert info" style="margin-bottom:10px"><h4>📝 Mode PAPER actif</h4><p>Tous les trades sont <b>simulés</b> avec un solde fictif de ${fmtUsd(me.paper_balance)}. Aucun USDC réel n'est utilisé. Idéal pour tester votre config.</p></div>
           <button class="btn btn-danger" onclick="window._toggleMode(false)">⚠ Passer en mode LIVE (USDC réel)</button>`
        : `<div class="alert warning" style="margin-bottom:10px"><h4>💵 Mode LIVE actif</h4><p>Les trades sont <b>réels</b> sur Polygon. Chaque copie utilise votre USDC on-chain.</p></div>
           <button class="btn btn-secondary" onclick="window._toggleMode(true)">📝 Repasser en mode Paper</button>`}
      <div style="height:10px"></div>
      ${tgl("is_paused", "Mettre le copy trading en pause", "Stoppe temporairement la copie. Les positions ouvertes restent gérées (SL/TP actifs).", s.is_paused)}
    </details>

    <details class="card" open>
      <summary>💰 Capital & taille des trades</summary>
      ${num("allocated_capital", "Capital alloué (USDC)", s.allocated_capital, 10, 10, 100000,
        hint("10% de votre capital total", "Mettez ici juste la somme que vous acceptez de perdre en totalité, pas tout votre USDC."), true)}
      ${sel("sizing_mode", "Mode de sizing", s.sizing_mode || "fixed",
        [{value:"fixed", label:"🟰 Fixe — toujours le même montant"},
         {value:"percent", label:"% — % du capital alloué"},
         {value:"proportional", label:"📏 Proportionnel — copie la proportion du master"},
         {value:"kelly", label:"🧠 Kelly — formule mathématique (avancé)"}],
        hint("Fixe pour débuter", "Fixe = prévisible. Proportionnel = on mime vraiment le master mais tailles variables. Kelly = rareté mathématique."), true)}

      <!-- Mode FIXE -->
      <div class="dep-group" data-depends-on-value="sizing_mode=fixed">
        ${num("fixed_amount", "Montant fixe USDC", s.fixed_amount, 0.5, 0.1, 1000,
          hint("5-10 USDC pour débuter", "Chaque trade fera ce montant précis. Débutant → 2-5. Confiant → 10-50."), true)}
      </div>

      <!-- Mode PERCENT -->
      <div class="dep-group" data-depends-on-value="sizing_mode=percent">
        ${num("percent_per_trade", "% du capital par trade", s.percent_per_trade, 0.5, 0.1, 100,
          hint("2-5%", "Augmentez si peu de traders suivis (concentré). Diminuez si beaucoup (risque dispersé)."), true)}
      </div>

      <!-- Mode PROPORTIONAL -->
      <div class="dep-group" data-depends-on-value="sizing_mode=proportional">
        ${num("proportional_factor", "Facteur de proportion", s.proportional_factor || 1.0, 0.1, 0.01, 10,
          hint("1.0", "Le bot fait `master_amount × facteur × (votre_capital ÷ master_capital)`. Ajustez pour scaler la copie."))}
      </div>

      <!-- Mode KELLY -->
      <div class="dep-group" data-depends-on-value="sizing_mode=kelly">
        ${num("kelly_fraction", "Fraction de Kelly", s.kelly_fraction || 0.25, 0.05, 0.05, 1.0,
          hint("0.25 (Kelly/4)", "0.25 = recommandé. 1.0 = full Kelly (très agressif)."))}
      </div>

      <div style="height:6px"></div>
      ${num("multiplier", "Multiplicateur global", s.multiplier, 0.1, 0.1, 10,
        hint("1.0 (neutre)", "0.5 = trades 2× plus petits. 2.0 = 2× plus gros. Pour ajuster vite sans changer le mode."))}
      ${num("min_trade_usdc", "Montant minimum (USDC)", s.min_trade_usdc, 0.5, 0, 1000,
        hint("1 USDC", "Plus haut → skip les micro-trades. Polymarket a un min technique de 1 USDC par ordre."))}
      ${num("max_trade_usdc", "Montant maximum (USDC)", s.max_trade_usdc, 0.5, 0, 10000,
        hint("10% de votre capital", "Plus bas → protection contre les gros trades du master. Plus haut → moins de limitation."), true)}
      ${num("daily_limit_usdc", "Limite quotidienne (USDC)", s.daily_limit_usdc, 1, 0, 100000,
        hint("20-30% de votre capital", "Protège des journées perdantes en série. Reset minuit UTC."), true)}
    </details>

    <details class="card">
      <summary>🧠 Scoring des signaux (0-100)<span class="summary-status">${s.signal_scoring_enabled?'ON':'OFF'}</span></summary>
      <div class="small" style="margin-bottom:10px">Évalue chaque signal sur 6 critères (spread, liquidité, conviction, forme du trader, timing, consensus). Si désactivé → tous les signaux passent.</div>
      ${tgl("signal_scoring_enabled", "Activer le scoring", null, s.signal_scoring_enabled)}
      <div class="dep-group" data-depends-on="signal_scoring_enabled">
        ${num("min_signal_score", "Score minimum (0-100)", s.min_signal_score, 5, 0, 100,
          hint("40 (équilibré)", "20 = agressif (copie presque tout). 40 = équilibré. 65+ = strict (moins de trades, meilleure qualité)."))}
      </div>

      <div class="section-title" style="margin-top:16px"><h2>🎯 Profils rapides</h2></div>
      <div class="small" style="margin-bottom:10px">Cliquer un profil remplit le scoring + les 4 filtres Smart Filter ci-dessous avec un preset cohérent. Pas de 'profil actif' stocké — seules les valeurs comptent.</div>
      <div class="btn-row cols-3">
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('prudent')">🛡 Prudent</button>
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('balanced')">⚖️ Équilibré</button>
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('aggressive')">⚡ Agressif</button>
      </div>
      <div class="small" style="margin-top:10px">
        <b>🛡 Prudent</b> : score 65, conviction 5%, drift max 3%, skip coin-flip. Qualité &gt; quantité.<br>
        <b>⚖️ Équilibré</b> : score 40, conviction 2%, drift max 5%. Recommandé par défaut.<br>
        <b>⚡ Agressif</b> : score 20, spread + timing désactivés. Plus de trades, plus de variance.
      </div>
    </details>

    <details class="card">
      <summary>🎛 Smart filter avancé<span class="summary-status">${s.smart_filter_enabled?'ON':'OFF'}</span></summary>
      <div class="small" style="margin-bottom:10px">Filtres par-type-de-marché : coin-flip, conviction du master, drift du prix, winrate du trader sur Crypto/Sport. Si désactivé → tous ces filtres sont ignorés.</div>
      ${tgl("smart_filter_enabled", "Activer Smart Filter", null, s.smart_filter_enabled)}
      <div class="dep-group" data-depends-on="smart_filter_enabled">
        ${tgl("skip_coin_flip", "Ignorer les 50/50", "Skip si le prix est entre 0.45 et 0.55 (pas de conviction claire)", s.skip_coin_flip)}
        ${num("min_conviction_pct", "Conviction minimum (%)", s.min_conviction_pct, 0.5, 0, 100,
          hint("2%", "Exige que le master mise ≥ X% de SON portfolio. 0 = désactivé, 1 = permissif, 5+ = uniquement ses gros bets."))}
        ${num("max_price_drift_pct", "Drift prix max (%)", s.max_price_drift_pct, 0.5, 0, 50,
          hint("5%", "Si le prix a bougé de plus de X% depuis le master → skip. Baissez pour éviter d'acheter trop cher."))}
        ${num("min_trader_winrate_for_type", "Win rate min trader / type (%)", s.min_trader_winrate_for_type, 5, 0, 100,
          hint("55%", "Exige que le master ait > X% WR sur ce TYPE de marché. 0 = désactivé."))}
        ${num("min_trader_trades_for_type", "Min trades trader / type", s.min_trader_trades_for_type, 1, 1, 1000,
          hint("10", "Minimum d'historique pour fiabiliser la stat WR. 1 = toujours appliqué, 30+ = traders prouvés."))}
      </div>
    </details>

    <details class="card">
      <summary>🛡 Stop Loss & Take Profit</summary>
      <div class="small" style="margin-bottom:10px">Sorties automatiques sur prix. Chaque mécanisme a son propre toggle.</div>
      ${tgl("stop_loss_enabled", "Stop Loss", "ESSENTIEL pour éviter de perdre gros sur un trade qui tourne mal", s.stop_loss_enabled)}
      <div class="dep-group" data-depends-on="stop_loss_enabled">
        ${num("stop_loss_pct", "Seuil Stop Loss (%)", s.stop_loss_pct, 1, 1, 100,
          hint("20%", "Prudent → 10-15%. Moyen → 20%. Long terme → 30-40%."))}
      </div>
      ${tgl("take_profit_enabled", "Take Profit", "Vend automatiquement à un certain gain. Désactivé par défaut : le trailing est souvent meilleur.", s.take_profit_enabled)}
      <div class="dep-group" data-depends-on="take_profit_enabled">
        ${num("take_profit_pct", "Seuil Take Profit (%)", s.take_profit_pct, 1, 1, 500,
          hint("50%", "Court terme → 30%. Moyen → 50%. Laisse courir → 100%+."))}
      </div>
      ${tgl("trailing_stop_enabled", "Trailing Stop", "MEILLEUR QUE TP FIXE : SL qui suit le prix vers le haut, verrouille progressivement les gains", s.trailing_stop_enabled)}
      <div class="dep-group" data-depends-on="trailing_stop_enabled">
        ${num("trailing_stop_pct", "Marge trailing (%)", s.trailing_stop_pct, 1, 1, 100,
          hint("10%", "Serré (5%) = sortie rapide. Lâche (15-20%) = laisse respirer."))}
      </div>
    </details>

    <details class="card">
      <summary>⏱ Sorties avancées</summary>
      <div class="small" style="margin-bottom:10px">Time exit et scale out (TP partiel). Optionnels.</div>
      ${tgl("time_exit_enabled", "Sortie temporelle", "Ferme la position après X heures, peu importe le prix", s.time_exit_enabled)}
      <div class="dep-group" data-depends-on="time_exit_enabled">
        ${num("time_exit_hours", "Durée max (heures)", s.time_exit_hours, 1, 1, 720,
          hint("24h", "Court → 6-12h. Moyen → 24-72h. Long → 168h+."))}
      </div>
      ${tgl("scale_out_enabled", "Scale out (TP partiel)", "Au TP : vend X% au lieu de 100%, garde le reste avec SL=entrée", s.scale_out_enabled)}
      <div class="dep-group" data-depends-on="scale_out_enabled">
        ${num("scale_out_pct", "% à vendre au TP1", s.scale_out_pct, 5, 5, 95,
          hint("50%", "Prudent → 70%. Ambitieux → 30%."))}
      </div>
    </details>

    <details class="card">
      <summary>📊 Risque portefeuille</summary>
      <div class="small" style="margin-bottom:10px">Plafonds appliqués à chaque nouveau trade. 0 = désactivé pour ce critère.</div>
      ${num("max_positions", "Max positions ouvertes", s.max_positions, 1, 1, 100,
        hint("10-15", "Débutant → 5-10. Expérimenté → 15-30."))}
      ${num("max_category_exposure_pct", "Max exposition / catégorie (%)", s.max_category_exposure_pct, 5, 0, 100,
        hint("30%", "Ex: max 30% Crypto, max 30% Politics. 0 ou 100 = désactivé."))}
      ${num("max_direction_bias_pct", "Max biais directionnel (%)", s.max_direction_bias_pct, 5, 50, 100,
        hint("70%", "70 = bloque si > 70% des positions sont du même côté. 100 = désactivé."))}
    </details>

    <details class="card">
      <summary>🔥 Suivi performance traders<span class="summary-status">${s.auto_pause_cold_traders?'ON':'OFF'}</span></summary>
      <div class="small" style="margin-bottom:10px">Pause auto des traders qui décrochent + bonus sizing sur les streaks chauds.</div>
      ${tgl("auto_pause_cold_traders", "Pause auto traders cold", "Skip les copies si le trader a un win rate sous le seuil sur 7j", s.auto_pause_cold_traders)}
      <div class="dep-group" data-depends-on="auto_pause_cold_traders">
        ${num("cold_trader_threshold", "Seuil cold win rate (%)", s.cold_trader_threshold, 1, 0, 100,
          hint("40%", "Plus haut (45-50) = plus sélectif. Plus bas (30) = tolérant."))}
      </div>
      ${num("hot_streak_boost", "Multiplicateur hot streak", s.hot_streak_boost, 0.1, 1, 5,
        hint("1.0 (OFF)", "1.0 = pas de boost. 1.5 = +50% sur trader chaud. 2.0 = ×2."))}
    </details>

    <details class="card">
      <summary>⛽ Gas & Timing</summary>
      ${sel("gas_mode", "Vitesse des transactions Polygon", s.gas_mode || "fast",
        [{value:"normal", label:"🐢 Normal — 30 gwei (~2s)"},
         {value:"fast", label:"🚀 Fast — 50 gwei (~1.5s)"},
         {value:"ultra", label:"⚡ Ultra — 100 gwei (<1s)"},
         {value:"instant", label:"💎 Instant — 200 gwei"}],
        hint("Fast", "Normal = éco. Fast = meilleur rapport. Ultra/Instant = si compétition."))}
      ${num("copy_delay_seconds", "Délai avant copie (sec)", s.copy_delay_seconds, 1, 0, 600,
        hint("0 (immédiat)", "0 = max speed. 2-5s = anti front-running. 10+ = trop lent."))}
      ${tgl("manual_confirmation", "Confirmation manuelle au-delà d'un seuil", "Pour les gros trades, notif + approbation requise", s.manual_confirmation)}
      <div class="dep-group" data-depends-on="manual_confirmation">
        ${num("confirmation_threshold_usdc", "Seuil confirmation (USDC)", s.confirmation_threshold_usdc, 1, 0, 10000,
          hint("50 USDC", "Demande à partir de ce montant."))}
      </div>
    </details>

    <details class="card">
      <summary>🔔 Notifications Telegram</summary>
      ${sel("notification_mode", "Où recevoir les alertes", s.notification_mode || "dm",
        [{value:"dm", label:"📱 Direct message"},{value:"group", label:"👥 Groupe"},{value:"both", label:"📨 Les deux"}],
        hint("DM", "DM = privé. Group = partagé. Both = les deux."))}
      ${tgl("notify_on_buy", "Notifier sur achats BUY", null, s.notify_on_buy)}
      ${tgl("notify_on_sell", "Notifier sur ventes SELL", null, s.notify_on_sell)}
      ${tgl("notify_on_sl_tp", "Notifier SL/TP/Sortie auto", null, s.notify_on_sl_tp)}
    </details>

    <details class="card">
      <summary>🎯 Stratégies automatisées</summary>
      ${num("strategy_trade_fee_rate", "Frais par trade (taux)", s.strategy_trade_fee_rate, 0.01, 0.01, 0.20,
        hint("0.01 (1%)", "1% = min. 3-5% = priorité dans la file d'exécution."))}
      ${num("strategy_max_trades_per_day", "Max trades par jour", s.strategy_max_trades_per_day, 1, 1, 200,
        hint("50", "Protection si strat trade trop. 200 = pas de limite."))}
      ${tgl("strategy_is_paused", "Mettre les stratégies en pause", null, s.strategy_is_paused)}
    </details>

    <div style="height:20px"></div>
  `);
  setBack("more");

  /* — Dependency grey-out : 2 patterns supportés —
        1. data-depends-on="toggle_key"            → grise si le toggle est OFF
        2. data-depends-on-value="key=valeur"      → MASQUE si la valeur du SELECT/input ne match pas
                                                     (ex. champs spécifiques à sizing_mode=fixed)
  */
  function applyDeps() {
    // Pattern 1 — toggle dependency
    document.querySelectorAll("[data-depends-on]").forEach(group => {
      const parentKey = group.dataset.dependsOn;
      const parentInput = document.querySelector(`[data-key="${parentKey}"]`);
      if (parentInput && parentInput.type === "checkbox") {
        group.classList.toggle("depends-off", !parentInput.checked);
      }
    });

    // Pattern 2 — value match (SELECT, input value)
    document.querySelectorAll("[data-depends-on-value]").forEach(group => {
      const expr = group.dataset.dependsOnValue || "";
      const [parentKey, expected] = expr.split("=").map(x => x.trim());
      if (!parentKey || expected === undefined) return;
      const parentInput = document.querySelector(`[data-key="${parentKey}"]`);
      if (!parentInput) return;
      const currentVal = String(parentInput.value || "");
      const match = currentVal === expected;
      // Masquage complet (pas grey-out) — plus clair
      group.style.display = match ? "" : "none";
    });

    // Met à jour les badges ON/OFF dans les <summary>
    document.querySelectorAll("details.card").forEach(det => {
      const statusSpan = det.querySelector("summary > .summary-status");
      if (!statusSpan) return;
      const firstDep = det.querySelector(".dep-group[data-depends-on]");
      if (!firstDep) return;
      const parentInput = document.querySelector(`[data-key="${firstDep.dataset.dependsOn}"]`);
      if (parentInput && parentInput.type === "checkbox") {
        statusSpan.textContent = parentInput.checked ? "ON" : "OFF";
        statusSpan.style.color = parentInput.checked ? "var(--ok, #4ade80)" : "var(--muted, #888)";
      }
    });
  }
  applyDeps();

  const debounce = {};
  document.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    const send = async () => {
      let val;
      if (el.type === "checkbox") val = el.checked;
      else if (el.type === "number") val = el.value === "" ? null : parseFloat(el.value);
      else val = el.value;
      if (val === null) return;
      try { await api("/settings", {method:"POST", body:{[key]: val}}); toast("✓ Sauvegardé"); }
      catch (e) { toast(e.message, "error"); }
    };
    if (el.type === "checkbox" || el.tagName === "SELECT") {
      el.addEventListener("change", () => { send(); applyDeps(); });
    } else {
      el.addEventListener("input", () => { clearTimeout(debounce[key]); debounce[key] = setTimeout(send, 600); });
    }
  });
}, {tab: "more", back: "more"});

window._applyProfile = async function(profile) {
  const names = {prudent: "Prudent", balanced: "Équilibré", aggressive: "Agressif"};
  const ok = await confirmModal("Appliquer " + names[profile] + " ?", "Remplace les réglages de scoring.", "Appliquer");
  if (!ok) return;
  try { await api("/settings/scoring-profile", {method:"POST", body:{profile}}); toast("Profil appliqué ✓"); dispatch(); }
  catch (e) { toast(e.message, "error"); }
};

window._permissiveMode = async function() {
  // ancien bouton — rediriger vers le nouveau toggle
  return window._togglePermissive(true);
};

window._togglePermissive = async function(turnOn) {
  if (turnOn) {
    const ok = await confirmModal(
      "🔓 Activer le mode permissif ?",
      "Le bot copiera TOUS les signaux des traders suivis sans filtre.\n\nFiltres bypassés : scoring, smart filter, coin flip, cold trader, portfolio manager, confirmation manuelle, copy delay.\n\nRestent actifs (vraies sécurités) : balance USDC, gas MATIC, daily limit, max_trade_usdc, blacklist marché.\n\n⚠ Configurez bien max_trade_usdc + daily_limit_usdc pour maîtriser le risque.",
      "Activer"
    );
    if (!ok) { dispatch(); return; }
    try {
      await api("/settings", {method:"POST", body:{
        permissive_mode: true,
        signal_scoring_enabled: false,
        smart_filter_enabled: false,
        skip_coin_flip: false,
        auto_pause_cold_traders: false,
        manual_confirmation: false,
        idempotency_window_seconds: 60,
        max_same_category_positions: 999,
      }});
      toast("🔓 Mode permissif ACTIF");
      dispatch();
    } catch (e) { toast(e.message, "error"); dispatch(); }
  } else {
    try {
      await api("/settings", {method:"POST", body:{permissive_mode: false}});
      toast("🔒 Mode permissif désactivé");
      dispatch();
    } catch (e) { toast(e.message, "error"); dispatch(); }
  }
};

/* 🩺 Diagnostic — modale qui montre tous les bloqueurs */
window._diagCopy = async function() {
  const bd = document.createElement("div");
  bd.className = "sheet-backdrop";
  bd.innerHTML = `<div class="sheet"><div class="loading"><div class="spinner"></div>Diagnostic en cours…</div></div>`;
  document.body.appendChild(bd);
  bd.addEventListener("click", e => { if (e.target === bd) bd.remove(); });
  try {
    const d = await api("/diagnostic/copy-status");
    const iconFor = c => c.status === "ok" ? "✅" : c.status === "warning" ? "⚠️" : "❌";
    const colorFor = c => c.status === "ok" ? "var(--ok,#4ade80)" : c.status === "warning" ? "var(--warn,#f59e0b)" : "var(--red,#ef4444)";
    bd.innerHTML = `
      <div class="sheet" style="max-height:85vh;overflow-y:auto">
        <h3>🩺 Diagnostic copy</h3>
        <div class="alert ${d.blockers_count > 0 ? 'warning' : 'info'}" style="margin-bottom:14px">
          <p>${esc(d.summary)}</p>
        </div>
        ${d.checks.map(c => `
          <div style="display:flex;gap:10px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)">
            <div style="font-size:18px">${iconFor(c)}</div>
            <div style="flex:1">
              <div style="font-weight:600;color:${colorFor(c)}">${esc(c.label)}</div>
              <div class="small" style="margin-top:2px">${esc(c.message)}</div>
              ${c.fix ? `<div class="small" style="margin-top:4px;opacity:0.6;font-family:monospace">→ ${esc(c.fix)}</div>` : ""}
            </div>
          </div>`).join("")}
        <button class="btn btn-primary" id="diag-close" style="margin-top:14px">Fermer</button>
      </div>`;
    bd.querySelector("#diag-close").onclick = () => bd.remove();
  } catch (e) {
    bd.innerHTML = `<div class="sheet"><h3>🩺 Diagnostic</h3><div class="alert"><p>Erreur: ${esc(e.message)}</p></div><button class="btn btn-primary" id="x">Fermer</button></div>`;
    bd.querySelector("#x").onclick = () => bd.remove();
  }
};

window._resetSettings = async function() {
  const ok = await confirmModal(
    "♻️ Restaurer les valeurs par défaut ?",
    "Tous les paramètres (sizing, SL/TP, smart analysis, notifs, etc.) seront remis aux valeurs recommandées.\n\nNE TOUCHE PAS à :\n• Votre wallet et clés privées\n• Vos traders suivis\n• Mode Paper/Live\n• Marchés bloqués\n\nConfirmer ?",
    "Restaurer",
    "danger"
  );
  if (!ok) return;
  try {
    const r = await api("/settings/reset-defaults", {method:"POST"});
    toast(`✓ ${r.reset_count} paramètres réinitialisés`);
    dispatch();
  } catch (e) { toast(e.message, "error"); }
};

/* ═══════════════════════════════════════════════════ RAPPORTS (split: Mes trades / Mes traders) */
route(/^more\/reports$/, async () => { go("more/reports/me"); }, {tab: "more", back: "more"});

const reportsNav = (active) => subNav([
  {label:"📊 Mes trades", href:"more/reports/me"},
  {label:"👥 Mes traders", href:"more/reports/traders"},
  {label:"📄 Export", href:"more/reports/export"},
], active);

/* État local rapports */
const REPORTS_STATE = { my_period: "week", traders_period: "month", traders_selected: new Set() };

/* ── Mes trades — sélecteur période + Générer ── */
route(/^more\/reports\/me$/, async () => {
  render(`
    <div class="page-title">Rapports</div>
    ${reportsNav("more/reports/me")}
    <div class="small" style="margin-bottom:12px">Performance de <b>vos</b> trades exécutés.</div>

    <div class="card">
      <div class="card-title">📅 Choisir la période</div>
      <div class="form-row">
        <select class="input" id="my-period">
          <option value="day" ${REPORTS_STATE.my_period==='day'?'selected':''}>Aujourd'hui</option>
          <option value="week" ${REPORTS_STATE.my_period==='week'?'selected':''}>7 derniers jours</option>
          <option value="month" ${REPORTS_STATE.my_period==='month'?'selected':''}>30 derniers jours</option>
        </select>
      </div>
      <button class="btn btn-primary" id="gen-my">📊 Générer le rapport</button>
    </div>

    <div id="my-result"></div>
  `);
  setBack("more");
  document.getElementById("gen-my").onclick = async () => {
    const period = document.getElementById("my-period").value;
    REPORTS_STATE.my_period = period;
    const out = document.getElementById("my-result");
    out.innerHTML = `<div class="loading"><div class="spinner"></div>Génération…</div>`;
    try {
      const [pnl, signals, byMarket, portfolio] = await Promise.all([
        api("/reports/pnl?period=" + period),
        api("/analytics/signals"),
        api("/reports/by-market"),
        api("/analytics/portfolio"),
      ]);
      const periodLabel = period==='day'?"Aujourd'hui":period==='week'?"7 derniers jours":"30 derniers jours";
      const maxCount = Math.max(1, ...(signals?.by_day || []).map(x => x.count));
      out.innerHTML = `
        <div class="card">
          <div class="card-header">
            <div class="h3">${periodLabel}</div>
            <span class="${pnlClass(pnl.pnl)}" style="font-weight:700;font-size:20px">${pnlSign(pnl.pnl)}</span>
          </div>
          <div class="stats-inline">
            <div class="stat-mini"><div class="stat-value">${pnl.trades}</div><div class="stat-label">Trades</div></div>
            <div class="stat-mini"><div class="stat-value">${fmtPct(pnl.win_rate)}</div><div class="stat-label">Win rate</div></div>
            <div class="stat-mini"><div class="stat-value ${pnlClass(pnl.best_trade)}">${fmtUsd(pnl.best_trade)}</div><div class="stat-label">Best</div></div>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="window._exportReport('${period}')" style="margin-bottom:16px">📄 Exporter HTML/PDF</button>

        <div class="section">${sectionTitle("Activité par jour (7j)")}
          <div class="card">
            ${(signals?.by_day || []).length === 0
              ? `<div class="small" style="text-align:center;padding:20px 0">Aucune activité</div>`
              : signals.by_day.map(x => `
                  <div style="margin-bottom:10px">
                    <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
                      <span>${x.date}</span><span>${x.count} trades</span>
                    </div>
                    <div class="progress"><div class="progress-fill" style="width:${(x.count/maxCount)*100}%;background:var(--tg-btn)"></div></div>
                  </div>`).join("")}
          </div>
        </div>

        ${(portfolio?.by_source || []).length > 0 ? `
          <div class="section">${sectionTitle("Répartition positions ouvertes")}
            <div class="card">
              ${portfolio.by_source.slice(0,10).map(s => `
                <div style="margin-bottom:12px">
                  <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
                    <span class="mono">${s.source.length > 30 ? s.source.slice(0,10)+'…'+s.source.slice(-4) : s.source}</span>
                    <span>${fmtUsd(s.value)} · ${s.pct}%</span>
                  </div>
                  <div class="progress"><div class="progress-fill" style="width:${s.pct}%"></div></div>
                </div>`).join("")}
            </div>
          </div>` : ""}

        <div class="section">${sectionTitle("PnL par marché")}
          ${(byMarket?.markets || []).length === 0
            ? `<div class="card small" style="text-align:center;padding:24px">Aucune donnée</div>`
            : `<div class="card card-flush"><div class="list">${byMarket.markets.slice(0,15).map(m => `
                <div class="list-item">
                  <div class="list-icon">📊</div>
                  <div class="list-body">
                    <div class="list-title">${esc(m.market_question)}</div>
                    <div class="list-sub">${m.trade_count} trades · ${fmtUsd(m.volume)}</div>
                  </div>
                  <div class="list-right ${pnlClass(m.pnl)}" style="font-weight:600">${pnlSign(m.pnl)}</div>
                </div>`).join("")}</div></div>`}
        </div>
      `;
    } catch (e) {
      out.innerHTML = `<div class="alert"><p>Erreur: ${esc(e.message)}</p></div>`;
    }
  };
}, {tab: "more", back: "more"});

/* ── Mes traders — sélecteur traders + période + Générer ── */
route(/^more\/reports\/traders$/, async () => {
  const traders = await api("/copy/traders");
  if (REPORTS_STATE.traders_selected.size === 0) {
    traders.traders.forEach(t => REPORTS_STATE.traders_selected.add(t.wallet.toLowerCase()));
  }
  render(`
    <div class="page-title">Rapports</div>
    ${reportsNav("more/reports/traders")}
    <div class="small" style="margin-bottom:12px">Performance détaillée des traders sélectionnés.</div>

    <div class="card">
      <div class="card-title">🎯 Sélectionner les traders</div>
      <div style="display:flex;justify-content:space-between;margin-bottom:8px">
        <button class="btn btn-ghost btn-sm" onclick="window._traderSelectAll()">Tout cocher</button>
        <button class="btn btn-ghost btn-sm" onclick="window._traderSelectNone()">Tout décocher</button>
      </div>
      ${traders.traders.length === 0
        ? `<div class="small" style="text-align:center;padding:20px 0">Aucun trader suivi</div>`
        : traders.traders.map(t => `
            <label class="toggle-row" style="cursor:pointer">
              <div>
                <div class="toggle-label mono">${t.wallet_short}</div>
                <div class="toggle-sub">${t.trade_count} trades · ${pnlSign(t.pnl)} PnL</div>
              </div>
              <div class="toggle"><input type="checkbox" data-trader="${t.wallet.toLowerCase()}" ${REPORTS_STATE.traders_selected.has(t.wallet.toLowerCase())?'checked':''}><span class="slider"></span></div>
            </label>`).join("")}

      <div class="form-row" style="margin-top:14px">
        <label class="label">Période</label>
        <select class="input" id="tr-period">
          <option value="week" ${REPORTS_STATE.traders_period==='week'?'selected':''}>7 derniers jours</option>
          <option value="month" ${REPORTS_STATE.traders_period==='month'?'selected':''}>30 derniers jours</option>
        </select>
      </div>

      <button class="btn btn-primary" id="gen-tr">📊 Générer le rapport</button>
    </div>

    <div id="tr-result"></div>
  `);
  setBack("more");

  document.querySelectorAll("[data-trader]").forEach(el => {
    el.addEventListener("change", () => {
      const w = el.dataset.trader;
      if (el.checked) REPORTS_STATE.traders_selected.add(w);
      else REPORTS_STATE.traders_selected.delete(w);
    });
  });

  document.getElementById("gen-tr").onclick = async () => {
    REPORTS_STATE.traders_period = document.getElementById("tr-period").value;
    const selected = REPORTS_STATE.traders_selected;
    if (selected.size === 0) return toast("Sélectionnez au moins un trader", "error");

    const out = document.getElementById("tr-result");
    out.innerHTML = `<div class="loading"><div class="spinner"></div>Génération…</div>`;
    try {
      const [byTrader, analytics] = await Promise.all([
        api("/reports/by-trader"),
        api("/analytics/traders"),
      ]);
      const traderDetail = (w) => (analytics?.traders || []).find(t => t.wallet.toLowerCase() === w.toLowerCase());
      const catBadge = (c) => c === "hot" ? badge("🔥 HOT", "green")
        : c === "cold" ? badge("❄️ COLD", "red") : c === "warm" ? badge("Actif", "blue") : badge("Nouveau", "muted");
      const filtered = (byTrader.traders || []).filter(t => selected.has(t.wallet.toLowerCase()));

      out.innerHTML = `
        <div class="small" style="margin:12px 0">${filtered.length} trader(s) · période ${REPORTS_STATE.traders_period==='week'?'7j':'30j'}</div>
        ${filtered.length === 0
          ? emptyState("📭", "Aucune donnée", "Aucun des traders sélectionnés n'a de trade dans la période.")
          : filtered.map(t => {
              const det = traderDetail(t.wallet) || {};
              return `
              <div class="card">
                <div class="card-header">
                  <div style="display:flex;align-items:center;gap:10px">
                    <div class="avatar" style="width:36px;height:36px;font-size:14px">${t.wallet_short.slice(2,4).toUpperCase()}</div>
                    <div>
                      <div class="mono" style="font-weight:600">${t.wallet_short}</div>
                      <div class="small">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
                    </div>
                  </div>
                  <div style="text-align:right">
                    ${det.category ? catBadge(det.category) : ""}
                    <div class="${pnlClass(t.pnl)}" style="font-weight:700;margin-top:4px">${pnlSign(t.pnl)}</div>
                  </div>
                </div>
                ${det.current_streak && det.current_streak >= 3 ? `<div style="margin-top:6px">${badge((det.streak_type==='win'?'🔥 '+det.current_streak+' wins consécutifs':'❄️ '+det.current_streak+' losses consécutifs'), det.streak_type==='win'?'green':'red')}</div>` : ""}
                ${(det.strong_categories || []).length > 0 ? `<div class="small" style="margin-top:8px"><b>✅ Forts :</b> ${det.strong_categories.map(c => `${c.category} (${fmtPct(c.win_rate)})`).join(", ")}</div>` : ""}
                ${(det.weak_categories || []).length > 0 ? `<div class="small" style="margin-top:4px"><b>❌ Faibles :</b> ${det.weak_categories.map(c => `${c.category} (${fmtPct(c.win_rate)})`).join(", ")}</div>` : ""}
                <button class="btn btn-secondary btn-sm" style="margin-top:10px" onclick="go('copy/trader/${t.wallet}')">Voir fiche complète ›</button>
              </div>`;
            }).join("")}
      `;
    } catch (e) {
      out.innerHTML = `<div class="alert"><p>Erreur: ${esc(e.message)}</p></div>`;
    }
  };
}, {tab: "more", back: "more"});

window._traderSelectAll = function() {
  document.querySelectorAll("[data-trader]").forEach(el => {
    el.checked = true;
    REPORTS_STATE.traders_selected.add(el.dataset.trader);
  });
};
window._traderSelectNone = function() {
  document.querySelectorAll("[data-trader]").forEach(el => {
    el.checked = false;
  });
  REPORTS_STATE.traders_selected.clear();
};

/* ── Export PDF/HTML — sélecteur période + bouton Générer ── */
route(/^more\/reports\/export$/, async () => {
  render(`
    <div class="page-title">Rapports</div>
    ${reportsNav("more/reports/export")}
    <div class="card">
      <div class="card-title">📄 Exporter un rapport HTML</div>
      <div class="small" style="margin-bottom:14px">Rapport détaillé imprimable en PDF (Ctrl+P après ouverture).</div>
      <div class="form-row">
        <label class="label">Choisir la période</label>
        <select class="input" id="exp-period">
          <option value="day">Aujourd'hui</option>
          <option value="week" selected>7 derniers jours</option>
          <option value="month">30 derniers jours</option>
        </select>
      </div>
      <button class="btn btn-primary" id="gen-exp">📥 Générer & ouvrir le rapport</button>
    </div>
    <div class="alert info">
      <h4>ℹ Inclus dans le rapport</h4>
      <p>• Hero PnL total avec breakdown copy/stratégie<br>• Win rate, best/worst trade<br>• Tableau par trader (top 20)<br>• Tableau par marché (top 20)<br>• Détail des 100 derniers trades</p>
    </div>
  `);
  setBack("more");
  document.getElementById("gen-exp").onclick = () => {
    window._exportReport(document.getElementById("exp-period").value);
  };
}, {tab: "more", back: "more"});

window._exportReport = function(period) {
  const url = `/miniapp/api/reports/export.html?period=${period}&auth=${encodeURIComponent(APP.initData)}`;
  const fullUrl = new URL(url, location.origin).href;
  if (tg?.openLink) tg.openLink(fullUrl);
  else window.open(fullUrl, "_blank");
  toast("Rapport ouvert ↗");
};

/* ═══════════════════════════════════════════════════ MARCHÉS BLOQUÉS (blacklist global) */
route(/^more\/blacklist$/, async () => {
  const r = await api("/copy/blacklist");
  render(`
    <div class="page-title">🚫 Marchés bloqués</div>
    <div class="small" style="margin-bottom:14px">Le bot ne copiera <b>aucun trade</b> sur ces marchés, peu importe le trader.</div>
    ${r.count === 0
      ? emptyState("✓", "Aucun marché bloqué", "Vous pouvez bloquer un marché depuis la fiche d'un trader (dans la section Marchés actifs).")
      : `<div class="card card-flush"><div class="list">${r.blacklist.map(mid => `
          <div class="list-item">
            <div class="list-icon" style="background:rgba(255,69,58,0.15)">🚫</div>
            <div class="list-body">
              <div class="list-title mono" style="word-break:break-all">${esc(mid).slice(0, 60)}${mid.length>60?'…':''}</div>
            </div>
            <div class="list-right">
              <button class="btn btn-secondary btn-sm" onclick="window._unblockGlobal('${esc(mid)}')">Débloquer</button>
            </div>
          </div>`).join("")}</div></div>`}
  `);
  setBack("more");
}, {tab: "more", back: "more"});

window._unblockGlobal = async function(mid) {
  try {
    await api("/copy/blacklist/" + encodeURIComponent(mid), {method:"DELETE"});
    invalidate("blacklist"); toast("Débloqué"); dispatch();
  } catch (e) { toast(e.message, "error"); }
};

/* ═══════════════════════════════════════════════════ NOTIFS — Mini App feed */
route(/^notifs$/, async () => { go("notifs/all"); });

const notifsNav = (active) => subNav([
  {label:"Tout", href:"notifs/all"},
  {label:"Trades", href:"notifs/trades"},
  {label:"Sorties", href:"notifs/exits"},
], active);

route(/^notifs\/(all|trades|exits)$/, async (m) => {
  const filter = m[1];
  const data = await api("/notifications?limit=80&kind=" + filter);
  // Auto-mark all read once we visit any tab
  api("/notifications/mark-read", {method: "POST"}).catch(() => {});
  setTimeout(() => updateNotifBadge(0), 200);

  const sevColor = (s) => s === "success" ? "var(--green)" : s === "error" ? "var(--red)" : s === "warning" ? "var(--orange)" : "var(--tg-link)";
  const items = data.items || [];

  render(`
    <div class="page-title">🔔 Notifications</div>
    <div class="small" style="margin-bottom:12px">Tous les événements de votre bot — trades exécutés, sorties de positions, alerts.</div>
    ${notifsNav("notifs/" + filter)}

    ${items.length === 0
      ? emptyState("📭", "Aucune notification", "Les événements apparaîtront ici dès qu'un trade ou une sortie aura lieu.")
      : `<div class="card card-flush"><div class="list">${items.map(it => `
          <div class="list-item ${it.unread?'is-unread':''}" style="border-left:3px solid ${sevColor(it.severity)}">
            <div class="list-body">
              <div class="list-title" style="display:flex;align-items:center;gap:6px">
                ${it.unread?'<span style="width:8px;height:8px;background:var(--tg-btn);border-radius:50%;flex-shrink:0"></span>':''}
                ${esc(it.title)}
                ${it.is_paper ? badge("PAPER","orange") : ""}
              </div>
              <div class="list-sub" style="font-size:13px;color:var(--tg-text);margin-top:2px">${esc(it.market)}</div>
              <div class="list-sub" style="margin-top:4px">${esc(it.body)} · ${timeAgo(it.created_at)}</div>
            </div>
          </div>`).join("")}</div></div>`}
  `);
}, {tab: "notifs"});

async function updateNotifBadge(forceCount = null) {
  const el = document.getElementById("notif-badge");
  if (!el) return;
  let n = forceCount;
  if (n === null) {
    try { const r = await api("/notifications/unread-count"); n = r.unread || 0; }
    catch { n = 0; }
  }
  if (n > 0) {
    el.textContent = n > 99 ? "99+" : String(n);
    el.style.display = "inline-flex";
  } else {
    el.style.display = "none";
  }
}

/* Poll badge every 20s when app is visible */
let _badgeTimer = null;
function startBadgePoller() {
  if (_badgeTimer) clearInterval(_badgeTimer);
  updateNotifBadge();
  _badgeTimer = setInterval(() => {
    if (document.visibilityState === "visible") updateNotifBadge();
  }, 20000);
}

/* ═══════════════════════════════════════════════════ NOTIFICATIONS TG (sub-page de Settings) */
route(/^more\/notifs-tg$/, async () => {
  const s = await api("/settings");
  render(`
    <div class="page-title">🔔 Notifications Telegram</div>
    <div class="small" style="margin-bottom:14px">Configurez ce que vous recevez sur Telegram (DM ou groupe). La Mini App garde toujours l'historique complet dans l'onglet 🔔 Notifs.</div>

    <div class="card">
      <div class="card-title">📍 Destination</div>
      <div class="form-row">
        <label class="label">Où recevoir les notifs Telegram ?</label>
        <select class="input" data-key="notification_mode">
          <option value="dm" ${s.notification_mode==='dm'?'selected':''}>📱 Direct message (privé)</option>
          <option value="group" ${s.notification_mode==='group'?'selected':''}>👥 Groupe (topic dédié)</option>
          <option value="both" ${s.notification_mode==='both'?'selected':''}>📨 Les deux</option>
        </select>
        <div class="input-hint">Si vous choisissez "Groupe", le bot envoie les notifs dans les topics correspondants (Signals, Alerts, etc.) du groupe que vous avez configuré.</div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">🎚 Quels événements recevoir ?</div>
      <label class="toggle-row">
        <div>
          <div class="toggle-label">🟢 Trades BUY exécutés</div>
          <div class="toggle-sub">Notification à chaque ouverture de position (achat copié)</div>
        </div>
        <div class="toggle"><input type="checkbox" data-key="notify_on_buy" ${s.notify_on_buy?'checked':''}><span class="slider"></span></div>
      </label>
      <label class="toggle-row">
        <div>
          <div class="toggle-label">🔴 Trades SELL exécutés</div>
          <div class="toggle-sub">Notification à chaque vente copiée (sortie initiée par le master)</div>
        </div>
        <div class="toggle"><input type="checkbox" data-key="notify_on_sell" ${s.notify_on_sell?'checked':''}><span class="slider"></span></div>
      </label>
      <label class="toggle-row">
        <div>
          <div class="toggle-label">🛑🎯 Sorties auto (SL/TP/Trailing/Time/Scale)</div>
          <div class="toggle-sub">Notification quand le bot ferme une position automatiquement (Stop Loss, Take Profit, trailing stop, time exit, scale out)</div>
        </div>
        <div class="toggle"><input type="checkbox" data-key="notify_on_sl_tp" ${s.notify_on_sl_tp?'checked':''}><span class="slider"></span></div>
      </label>
    </div>

    <div class="alert info">
      <h4>💡 Astuce</h4>
      <p>Même si vous coupez certaines notifs Telegram, l'onglet <b>🔔 Notifs</b> de la Mini App garde TOUT l'historique. Vous pouvez consulter à tout moment ce que le bot a fait.</p>
    </div>

    <button class="btn btn-secondary" onclick="go('notifs')">📂 Voir l'historique complet</button>
  `);
  setBack("more");

  document.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    const send = async () => {
      const val = el.type === "checkbox" ? el.checked : el.value;
      try { await api("/settings", {method:"POST", body:{[key]: val}}); toast("✓ Sauvegardé"); }
      catch (e) { toast(e.message, "error"); }
    };
    el.addEventListener("change", send);
  });
}, {tab: "more", back: "more"});

/* ═══════════════════════════════════════════════════ BOOTSTRAP */
async function loadUser() { APP.user = await api("/me"); return APP.user; }

async function init() {
  if (tg) {
    tg.ready(); tg.expand(); tg.enableClosingConfirmation?.();
    if (tg.themeParams) {
      document.body.style.background = tg.themeParams.bg_color || "";
      document.body.style.color = tg.themeParams.text_color || "";
    }
  }
  if (!APP.initData) {
    document.getElementById("app").innerHTML = `
      <div class="empty" style="padding:60px 20px">
        <div class="empty-icon">📱</div>
        <div class="empty-title" style="color:var(--red)">Ouvrez depuis Telegram</div>
        <div class="empty-text">Cette page doit être ouverte via le bouton Mini App.</div>
      </div>`;
    return;
  }
  document.getElementById("app").innerHTML = `
    <div class="header">
      <button class="header-btn" id="header-more" onclick="go('more')" title="Réglages & Plus">⚙️</button>
      <div class="header-title">WENPOLYMARKET<div class="header-sub">Polymarket Copy &amp; Strategies</div></div>
    </div>
    <div id="content" class="page"></div>
    <div class="tab-bar">
      <a href="#home" data-tab="home"><span class="tab-icon">🏠</span><span>Accueil</span></a>
      <a href="#wallet" data-tab="wallet"><span class="tab-icon">💰</span><span>Wallet</span></a>
      <a href="#copy" data-tab="copy"><span class="tab-icon">👥</span><span>Copy</span></a>
      <a href="#strategies" data-tab="strategies"><span class="tab-icon">🎯</span><span>Stratégies</span></a>
      <a href="#notifs" data-tab="notifs">
        <span class="tab-icon">🔔<span class="tab-badge" id="notif-badge" style="display:none">0</span></span>
        <span>Notifs</span>
      </a>
    </div>`;
  try { await loadUser(); }
  catch (e) { showError("Impossible de charger le profil: " + e.message); return; }
  window.addEventListener("hashchange", dispatch);
  startBadgePoller();
  dispatch();
}

window.go = go; window.copy = copy; window.dispatch = dispatch; window.loadUser = loadUser;
init();
