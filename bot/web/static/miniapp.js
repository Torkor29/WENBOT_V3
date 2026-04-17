/* WENPOLYMARKET Mini App — v4 SPA */

const tg = window.Telegram?.WebApp;
const APP = { initData: tg?.initData || "", user: null, cache: new Map(), mainBtnHandler: null, backHandler: null };

/* ── API ─────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch("/miniapp/api" + path, {
    method: opts.method || "GET",
    headers: { "Authorization": "tma " + APP.initData, "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

/* ── Cache ───────────────────────────────────────── */
async function cached(key, fn, ttl = 20000) {
  const e = APP.cache.get(key);
  if (e && Date.now() - e.t < ttl) return e.v;
  const v = await fn();
  APP.cache.set(key, { v, t: Date.now() });
  return v;
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
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast("Copié")); haptic("light"); }

/* ── Toast / Modals ──────────────────────────────── */
function toast(msg, type="success") {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transform = "translate(-50%,-10px)"; t.style.transition = "opacity .2s, transform .2s"; }, 1800);
  setTimeout(() => t.remove(), 2100);
  hapticNotif(type === "error" ? "error" : "success");
}

function confirmModal(title, text, confirmText="Confirmer", variant="primary") {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "modal-backdrop";
    bd.innerHTML = `
      <div class="modal">
        <h3>${esc(title)}</h3>
        <div class="modal-sub">${esc(text).replace(/\n/g, "<br>")}</div>
        <button class="btn btn-${variant}" id="cm-ok">${esc(confirmText)}</button>
        <button class="btn btn-secondary" id="cm-cancel" style="margin-top:8px">Annuler</button>
      </div>`;
    document.body.appendChild(bd);
    bd.querySelector("#cm-ok").onclick = () => { bd.remove(); resolve(true); };
    bd.querySelector("#cm-cancel").onclick = () => { bd.remove(); resolve(false); };
    bd.addEventListener("click", e => { if (e.target === bd) { bd.remove(); resolve(false); } });
  });
}

/* ── Layout helpers ─────────────────────────────── */
function render(html) { document.getElementById("content").innerHTML = html; }
function setTab(name) {
  document.querySelectorAll(".tab-bar a").forEach(a => a.classList.toggle("active", a.dataset.tab === name));
}
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
  tg.MainButton.setText(text);
  tg.MainButton.onClick(APP.mainBtnHandler);
  tg.MainButton.show();
}
function clearMainBtn() {
  if (!tg?.MainButton) return;
  if (APP.mainBtnHandler) { try { tg.MainButton.offClick(APP.mainBtnHandler); } catch {} }
  APP.mainBtnHandler = null;
  tg.MainButton.hide();
}

/* ── Components ──────────────────────────────────── */
const skeleton = () => `
  <div class="skeleton skeleton-hero"></div>
  <div class="stats" style="margin-bottom:12px">${Array(4).fill(0).map(() => `<div class="skeleton skeleton-stat"></div>`).join("")}</div>
  ${Array(2).fill(0).map(() => `<div class="card"><div class="skeleton skeleton-line wide"></div><div class="skeleton skeleton-line half"></div></div>`).join("")}`;

const stat = (v, l, cls="") => `<div class="stat"><div class="stat-value ${cls}">${v}</div><div class="stat-label">${esc(l)}</div></div>`;
const statsGrid = (items, cols=2) => `<div class="stats ${cols===4?'cols-4':cols===3?'cols-3':''}">${items.map(i=>stat(i.value,i.label,i.cls||"")).join("")}</div>`;
const subNav = (items, active) => `<div class="sub-nav">${items.map(i => `<a href="#${i.href}" class="sub-nav-item ${i.href === active ? "active" : ""}">${esc(i.label)}${i.count != null ? ` <span class="sub-nav-count">${i.count}</span>` : ""}</a>`).join("")}</div>`;
const sectionTitle = (label, action) => `<div class="section-title"><h2>${esc(label)}</h2>${action ? `<a class="card-action" onclick="${action.onclick}">${esc(action.label)} ›</a>` : ""}</div>`;
const emptyState = (icon, title, text, btn) => `<div class="empty"><div class="empty-icon">${icon}</div><div class="empty-title">${esc(title)}</div>${text ? `<div class="empty-text">${esc(text)}</div>` : ""}${btn ? `<button class="btn btn-primary" style="max-width:240px;margin:0 auto" onclick="${btn.onclick}">${esc(btn.label)}</button>` : ""}</div>`;
const badge = (text, variant="blue") => `<span class="badge badge-${variant}">${esc(text)}</span>`;

/* Mode badge (Paper/Live) - big colored pill */
function modeBadge(user) {
  if (user.paper_trading) return `<div class="mode-banner paper"><span>📝</span><div><div class="mode-title">MODE PAPER</div><div class="mode-sub">Simulation — pas d'USDC réel · Solde fictif ${fmtUsd(user.paper_balance)}</div></div></div>`;
  return `<div class="mode-banner live"><span>💵</span><div><div class="mode-title">MODE LIVE</div><div class="mode-sub">Trades réels · USDC vrai sur Polygon</div></div></div>`;
}

function stateBadge(user, ctrl) {
  if (!user.is_active) return badge("⏹ ARRÊTÉ", "red");
  if (user.is_paused) return badge("⏸ PAUSE", "orange");
  return badge("● ACTIF", "green");
}

/* ── Router ──────────────────────────────────────── */
const routes = [];
function route(pattern, handler, opts={}) { routes.push({pattern, handler, opts}); }
function go(hash) { location.hash = hash; }

const KNOWN_TABS = ["home", "copy", "strategies", "discover", "more"];

async function dispatch() {
  let hash = location.hash.slice(1);
  if (!hash || /tgwebapp/i.test(hash) || !KNOWN_TABS.includes(hash.split("/")[0])) {
    hash = "home";
    history.replaceState(null, "", "#home");
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
      catch (e) { showError(e.message); }
      return;
    }
  }
  history.replaceState(null, "", "#home");
  location.hash = "home";
}

function showError(msg) {
  render(`<div class="empty"><div class="empty-icon">⚠️</div><div class="empty-title" style="color:var(--red)">Erreur</div><div class="empty-text">${esc(msg)}</div><button class="btn btn-secondary" style="max-width:200px;margin:0 auto" onclick="dispatch()">Réessayer</button></div>`);
}

/* ═══════════════════════════════════════════════════
   HOME — Paper/Live visible + controls + overview
═══════════════════════════════════════════════════ */
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

  // Control banner si non running
  let ctrlBanner = "";
  if (ctrl.state === "paused") {
    ctrlBanner = `<div class="alert warning"><h4>⏸ Copy trading en pause</h4><p>Les nouveaux signaux sont ignorés. Positions ouvertes actives.</p><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="window._ctrlResume()">▶ Reprendre</button></div>`;
  } else if (ctrl.state === "stopped") {
    ctrlBanner = `<div class="alert"><h4>⏹ Copy trading arrêté</h4><p>Aucune activité automatique.</p><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="window._ctrlResume()">✓ Réactiver</button></div>`;
  }

  // Wallet card
  let balanceCard = "";
  if (me.wallet_address) {
    try {
      const bal = await cached("wallet-bal", () => api("/wallet/balance"), 15000);
      balanceCard = `
        <div class="card">
          <div class="card-header">
            <div class="tiny">Wallet Copy · ${stateBadge(me, ctrl)}</div>
            <a class="card-action" onclick="go('wallet')">Gérer ›</a>
          </div>
          <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:10px">
            <div><span style="font-size:22px;font-weight:700">${fmtUsd(me.paper_trading ? me.paper_balance : bal.usdc)}</span>
                 <span class="small" style="margin-left:4px">${me.paper_trading ? 'USDC (paper)' : 'USDC'}</span></div>
            ${!me.paper_trading ? `<div class="small">${bal.matic.toFixed(4)} MATIC</div>` : ''}
          </div>
          <div class="addr-box mono" onclick="copy('${bal.address}')">${shortAddr(bal.address)} · copier</div>
          <div class="btn-row" style="margin-top:12px">
            <button class="btn btn-primary btn-sm" onclick="go('wallet/deposit')">📥 Déposer</button>
            <button class="btn btn-secondary btn-sm" onclick="go('wallet/withdraw')">📤 Retirer</button>
          </div>
        </div>`;
    } catch {
      balanceCard = `<div class="card"><div class="small">Balance indisponible</div></div>`;
    }
  } else {
    balanceCard = `<div class="alert info"><h4>👛 Configurez votre wallet</h4><p>Créez ou importez un wallet Polygon pour commencer.</p><button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="go('wallet')">Configurer</button></div>`;
  }

  // PnL hero
  const heroHtml = `
    <div class="hero">
      <div class="hero-value ${pnlClass(totalPnl)}">${pnlSign(totalPnl)}</div>
      <div class="hero-label">PnL total · ${me.paper_trading ? "paper" : "live"}</div>
    </div>`;

  // Quick control button
  const controlRow = ctrl.state === "running" ? `<button class="btn btn-secondary" onclick="window._ctrlPause()" style="margin-bottom:12px">⏸ Mettre en pause</button>` : "";

  render(`
    ${modeBadge(me)}
    ${ctrlBanner}
    ${heroHtml}
    ${balanceCard}
    ${controlRow}

    <div class="quick-grid">
      <button class="quick-action" onclick="go('copy/traders')">
        <div class="quick-action-icon">👥</div>
        <div class="quick-action-label">Traders · ${me.followed_wallets_count}</div>
      </button>
      <button class="quick-action" onclick="go('discover')">
        <div class="quick-action-icon">🔍</div>
        <div class="quick-action-label">Découvrir</div>
      </button>
      <button class="quick-action" onclick="go('copy/positions')">
        <div class="quick-action-icon">📊</div>
        <div class="quick-action-label">Positions · ${copyStats.open_positions}</div>
      </button>
      <button class="quick-action" onclick="go('more/analytics')">
        <div class="quick-action-icon">🧠</div>
        <div class="quick-action-label">Analytics</div>
      </button>
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
        ? `<div class="card"><div class="empty" style="padding:24px 0"><div class="empty-text">Aucun trade pour le moment</div></div></div>`
        : `<div class="card card-flush"><div class="list">${recent.trades.slice(0,5).map(t => `
            <div class="list-item">
              <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
              <div class="list-body">
                <div class="list-title">${esc(t.market_question)}</div>
                <div class="list-sub">${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
              </div>
              <div class="list-right">
                ${t.settlement_pnl !== null ? `<span class="${pnlClass(t.settlement_pnl)}">${pnlSign(t.settlement_pnl)}</span>` : `<span class="small">${fmtUsd(t.amount)}</span>`}
              </div>
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
window._ctrlStop = async function() {
  const ok = await confirmModal("Arrêter le copy trading ?", "Le bot cessera toute activité.", "Arrêter", "danger");
  if (!ok) return;
  await api("/controls/stop", {method:"POST"}); invalidate("ctrl"); toast("Arrêté"); dispatch();
};

window._toggleMode = async function(toPaper) {
  if (toPaper) {
    const ok = await confirmModal("Passer en Paper ?", "Les trades seront simulés avec un solde fictif. Aucun USDC réel ne sera utilisé.", "Passer en Paper");
    if (!ok) return;
    await api("/user/mode", {method:"POST", body:{paper_trading: true}});
    toast("Mode Paper activé"); invalidateAll(); await loadUser(); dispatch();
  } else {
    const ok1 = await confirmModal("⚠ Passer en LIVE ?",
      `ATTENTION — Les trades seront RÉELS sur Polygon avec votre USDC.\nLes transactions blockchain sont IRRÉVERSIBLES.\n\nVotre wallet actuel : ${shortAddr(APP.user.wallet_address || '')}\n\nConfirmer ?`,
      "Je confirme, passer en Live", "danger");
    if (!ok1) return;
    const ok2 = await confirmModal("Dernière confirmation",
      "Vous êtes sur le point de risquer vos fonds réels. Confirmez une dernière fois.",
      "OUI, activer le mode LIVE", "danger");
    if (!ok2) return;
    try {
      await api("/user/mode", {method:"POST", body:{paper_trading: false, confirm_live: true}});
      toast("⚠ Mode LIVE activé", "warning");
      invalidateAll(); await loadUser(); dispatch();
    } catch (e) { toast(e.message, "error"); }
  }
};

/* ═══════════════════════════════════════════════════
   COPY TRADING — sub-nav Traders/Positions/Historique
═══════════════════════════════════════════════════ */
route(/^copy$/, async () => { go("copy/traders"); });

route(/^copy\/traders$/, async () => {
  const [traders, positions, trades] = await Promise.all([
    api("/copy/traders"),
    cached("copy-positions", () => api("/copy/positions")),
    cached("copy-trades-20", () => api("/copy/trades?limit=20")),
  ]);
  render(`
    ${modeBadge(APP.user)}
    <div class="page-title">Copy Trading</div>
    ${subNav([
      {label:"Traders", href:"copy/traders", count: traders.count},
      {label:"Positions", href:"copy/positions", count: positions.count},
      {label:"Historique", href:"copy/history"},
    ], "copy/traders")}
    ${traders.count === 0
      ? emptyState("👥", "Aucun trader suivi", "Ajoutez un wallet ou découvrez les top traders du moment.",
          {label:"🔍 Découvrir", onclick:"go('discover')"})
      : `<div class="card card-flush"><div class="list">
          ${traders.traders.map(t => `
            <div class="list-item" onclick="go('copy/trader/${t.wallet}')">
              <div class="avatar">${t.wallet_short.slice(2,4).toUpperCase()}</div>
              <div class="list-body">
                <div class="list-title mono">${t.wallet_short}</div>
                <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
              </div>
              <div class="list-right">
                <div class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>
                <div class="list-chevron">›</div>
              </div>
            </div>`).join("")}
        </div></div>
        <div class="btn-row" style="margin-top:12px">
          <button class="btn btn-primary btn-sm" onclick="go('copy/traders/add')">+ Par adresse</button>
          <button class="btn btn-secondary btn-sm" onclick="go('discover')">🔍 Découvrir</button>
        </div>`
    }
  `);
}, {tab: "copy"});

route(/^copy\/positions$/, async () => {
  const [{positions, count}, traders] = await Promise.all([
    cached("copy-positions", () => api("/copy/positions")),
    cached("copy-traders", () => api("/copy/traders")),
  ]);
  render(`
    <div class="page-title">Copy Trading</div>
    ${subNav([
      {label:"Traders", href:"copy/traders", count: traders.count},
      {label:"Positions", href:"copy/positions", count: count},
      {label:"Historique", href:"copy/history"},
    ], "copy/positions")}
    ${count === 0
      ? emptyState("📭", "Aucune position ouverte", "Les positions apparaîtront ici dès qu'un trade sera copié.")
      : `<div class="card card-flush"><div class="list">${positions.map(p => `
          <div class="list-item">
            <div class="list-icon">💼</div>
            <div class="list-body">
              <div class="list-title">${esc(p.market_question)}</div>
              <div class="list-sub">${p.shares.toFixed(2)} @ ${p.price.toFixed(4)} · ${p.master_wallet}</div>
            </div>
            <div class="list-right">
              <div style="font-weight:600">${fmtUsd(p.amount)}</div>
              ${p.is_paper ? badge("PAPER", "orange") : ""}
            </div>
          </div>`).join("")}</div></div>`}
  `);
}, {tab: "copy"});

route(/^copy\/history$/, async () => {
  const {trades} = await api("/copy/trades?limit=50");
  const traders = await cached("copy-traders", () => api("/copy/traders"));
  const pos = await cached("copy-positions", () => api("/copy/positions"));
  render(`
    <div class="page-title">Copy Trading</div>
    ${subNav([
      {label:"Traders", href:"copy/traders", count: traders.count},
      {label:"Positions", href:"copy/positions", count: pos.count},
      {label:"Historique", href:"copy/history", count: trades.length},
    ], "copy/history")}
    ${trades.length === 0
      ? emptyState("📜", "Aucun trade", "Vos trades copiés apparaîtront ici.")
      : `<div class="card card-flush"><div class="list">${trades.map(t => `
          <div class="list-item">
            <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
            <div class="list-body">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${t.master_wallet} · ${timeAgo(t.created_at)}</div>
            </div>
            <div class="list-right">
              ${t.settlement_pnl !== null
                ? `<div class="${pnlClass(t.settlement_pnl)}" style="font-weight:600">${pnlSign(t.settlement_pnl)}</div>`
                : `<div>${fmtUsd(t.amount)}</div>`}
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
        <label class="label">Adresse Polygon</label>
        <input class="input input-mono" id="addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
        <div class="input-hint">Collez l'adresse du trader à copier — ou utilisez 🔍 Découvrir pour trouver les meilleurs</div>
      </div>
    </div>
    <button class="btn btn-secondary" onclick="go('discover')">🔍 Découvrir les top traders</button>
  `);
  setBack("copy/traders");
  setMainBtn("SUIVRE CE TRADER", async () => {
    const w = document.getElementById("addr").value.trim();
    if (!w) return toast("Adresse requise", "error");
    try { await api("/copy/traders/add", {method:"POST", body:{wallet: w}}); invalidate("copy-"); toast("Trader ajouté"); go("copy/traders"); }
    catch (e) { toast(e.message, "error"); }
  });
}, {tab: "copy"});

route(/^copy\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
  const wallet = m[1];
  const [d, filters] = await Promise.all([
    api("/copy/traders/" + wallet + "/stats"),
    cached("trader-filters", () => api("/settings/trader-filters"), 10000),
  ]);
  const excluded = (filters.trader_filters || {})[wallet.toLowerCase()]?.excluded_categories || [];
  render(`
    <div style="text-align:center;padding:16px 0 20px">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;margin:0 auto 10px">${wallet.slice(2,4).toUpperCase()}</div>
      <div class="h2 mono">${shortAddr(wallet)}</div>
      <div class="small" style="margin-top:2px">${d.trade_count} trades copiés</div>
    </div>
    ${statsGrid([
      {value: fmtUsd(d.volume), label: "Volume"},
      {value: pnlSign(d.pnl), label: "PnL", cls: pnlClass(d.pnl)},
      {value: d.wins + "/" + d.losses, label: "W / L"},
      {value: fmtPct(d.win_rate), label: "Win rate"},
    ], 4)}

    <div class="section">
      ${sectionTitle("Filtres pour ce trader")}
      <div class="card">
        <div class="small" style="margin-bottom:10px">Catégories exclues pour ce trader uniquement. Les trades dans ces catégories ne seront pas copiés.</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${excluded.length === 0 ? '<span class="small">Aucune exclusion</span>' : excluded.map(c => `<span class="badge badge-red">${esc(c)}</span>`).join("")}
        </div>
        <button class="btn btn-secondary btn-sm" style="margin-top:10px" onclick="window._editTraderFilters('${wallet}')">Modifier les filtres</button>
      </div>
    </div>

    <div class="section">
      ${sectionTitle("Derniers trades")}
      ${d.recent_trades.length === 0
        ? `<div class="card"><div class="small" style="text-align:center;padding:20px 0">Aucun trade</div></div>`
        : `<div class="card card-flush"><div class="list">${d.recent_trades.map(t => `
            <div class="list-item">
              <div class="list-icon">${t.side==='BUY'?'🟢':'🔴'}</div>
              <div class="list-body">
                <div class="list-title">${esc(t.market_question)}</div>
                <div class="list-sub">${badge(t.side, t.side==='BUY'?'green':'red')} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
              </div>
              <div class="list-right">
                ${t.pnl !== null ? `<span class="${pnlClass(t.pnl)}">${pnlSign(t.pnl)}</span>` : `<span>${fmtUsd(t.amount)}</span>`}
              </div>
            </div>`).join("")}</div></div>`}
    </div>

    <div class="section">
      <div class="card"><div class="addr-box mono" onclick="copy('${wallet}')">${wallet}</div></div>
      <button class="btn btn-danger" style="margin-top:10px" onclick="window._trUnfollow('${wallet}')">🗑 Ne plus suivre</button>
    </div>
  `);
  setBack("copy/traders");
}, {tab: "copy"});

window._trUnfollow = async function(wallet) {
  const ok = await confirmModal("Arrêter de suivre ?", shortAddr(wallet) + " — les positions existantes ne seront pas affectées.", "Retirer", "danger");
  if (!ok) return;
  await api("/copy/traders/" + wallet, {method:"DELETE"});
  invalidate("copy-"); toast("Trader retiré"); go("copy/traders");
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
      <div class="sheet-sub">Cochez les catégories à EXCLURE. Les trades dans ces catégories ne seront pas copiés.</div>
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
    try {
      await api("/settings/trader-filter", {method:"POST", body:{wallet, excluded_categories: picked}});
      invalidate("trader-filters"); toast("Filtres enregistrés"); bd.remove(); dispatch();
    } catch (e) { toast(e.message, "error"); }
  };
};

/* ═══════════════════════════════════════════════════
   DISCOVER — Top traders Polymarket
═══════════════════════════════════════════════════ */
route(/^discover$/, async () => { go("discover/month"); });

route(/^discover\/(day|week|month|all)$/, async (m) => {
  const period = m[1];
  const d = await cached("discover-" + period, () => api("/discover/top-traders?period=" + period), 60000);
  render(`
    <div class="page-title">🔍 Découvrir</div>
    <div class="small" style="margin-bottom:12px">Top traders Polymarket par profit. Ajoute en 1 clic ceux qui t'intéressent.</div>
    ${subNav([
      {label:"24h", href:"discover/day"},
      {label:"7j", href:"discover/week"},
      {label:"30j", href:"discover/month"},
      {label:"All-time", href:"discover/all"},
    ], "discover/" + period)}

    ${d.error ? `<div class="alert warning"><h4>⚠ Données indisponibles</h4><p>${esc(d.error)}</p></div>` : ""}
    ${d.traders.length === 0 && !d.error
      ? emptyState("🔍", "Aucun trader trouvé", "L'API Polymarket n'a pas retourné de résultats pour cette période.")
      : `<div class="card card-flush"><div class="list">${d.traders.map((t, i) => `
          <div class="list-item">
            <div class="avatar" style="background:${i<3?'linear-gradient(135deg,#ffd700,#ff8c00)':'linear-gradient(135deg,var(--tg-btn),var(--purple))'}">${i+1}</div>
            <div class="list-body" onclick="go('discover/trader/${t.wallet}')">
              <div class="list-title mono">${esc(t.username || t.wallet_short)}</div>
              <div class="list-sub">${fmtUsd(t.volume)} vol · ${t.trades_count || '?'} trades</div>
            </div>
            <div class="list-right" style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
              <div class="${pnlClass(t.pnl)}" style="font-weight:700">${pnlSign(t.pnl)}</div>
              ${t.followed
                ? badge("✓ Suivi", "green")
                : `<button class="btn btn-primary btn-sm" style="padding:4px 10px" onclick="window._follow('${t.wallet}', event)">+ Suivre</button>`}
            </div>
          </div>`).join("")}</div></div>`}
  `);
});

window._follow = async function(wallet, ev) {
  if (ev) ev.stopPropagation();
  try { await api("/copy/traders/add", {method:"POST", body:{wallet}}); invalidate("copy-"); invalidate("discover-"); toast("Ajouté ✓"); dispatch(); }
  catch (e) { toast(e.message, "error"); }
};

route(/^discover\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
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
      ? emptyState("📭", "Aucune position", "Ce trader n'a pas de position ouverte actuellement.")
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
  setBack("discover/month");
}, {tab: "discover"});

/* ═══════════════════════════════════════════════════
   STRATEGIES
═══════════════════════════════════════════════════ */
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
    walletBanner = `<div class="alert warning"><h4>⚠ Wallet stratégie manquant</h4><p>Vous êtes abonné à ${activeSubs.length} stratégie(s) sans wallet dédié.</p><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="go('more/strategy-wallet')">Configurer</button></div>`;
  }
  render(`
    ${modeBadge(APP.user)}
    <div class="page-title">Stratégies</div>
    ${subNav([
      {label:"Disponibles", href:"strategies", count: strategies.length},
      {label:"Mes abonnements", href:"strategies/my", count: activeSubs.length},
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
        ? emptyState("🎯", "Aucune stratégie disponible", "Les stratégies publiques seront listées ici.")
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
      {label:"Mes abonnements", href:"strategies/my", count: activeSubs.length},
    ], "strategies/my")}
    ${subscriptions.length === 0
      ? emptyState("📭", "Aucun abonnement", "Abonnez-vous à une stratégie pour commencer.", {label:"Voir les stratégies", onclick:"go('strategies')"})
      : `<div class="card card-flush"><div class="list">${subscriptions.map(s => `
          <div class="list-item" onclick="window._stratOpen('${s.strategy_id}')">
            <div class="list-icon">${s.is_active?'🎯':'⏸'}</div>
            <div class="list-body">
              <div class="list-title">${esc(s.strategy_name)}</div>
              <div class="list-sub">${fmtUsd(s.trade_size)} / trade · ${s.is_active ? "Actif" : "Pause"}</div>
            </div>
            <div class="list-chevron">›</div>
          </div>`).join("")}</div></div>`}
    <button class="btn btn-secondary" style="margin-top:12px" onclick="go('strategies/history')">📜 Historique</button>
  `);
}, {tab: "strategies"});

route(/^strategies\/history$/, async () => {
  const {trades} = await api("/strategies/trades?limit=50");
  render(`
    <div class="page-title">Historique stratégies</div>
    ${trades.length === 0
      ? emptyState("📜", "Aucun trade", "Les exécutions apparaîtront ici.")
      : `<div class="card card-flush"><div class="list">${trades.map(t => `
          <div class="list-item">
            <div class="list-icon">${t.result==='WON'?'✅':t.result==='LOST'?'❌':'⏳'}</div>
            <div class="list-body">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${esc(t.strategy_id)} · ${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
            </div>
            <div class="list-right">
              ${t.pnl !== null ? `<div class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>` : `<div>${fmtUsd(t.amount)}</div>`}
            </div>
          </div>`).join("")}</div></div>`}
  `);
  setBack("strategies/my");
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
        ? `<button class="btn btn-primary" id="save">💾 Mettre à jour</button>
           <button class="btn btn-danger" id="unsub" style="margin-top:8px">Désinscrire</button>`
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
      await api(`/strategies/${id}/unsubscribe`, {method:"POST"});
      toast("Désinscrit"); done();
    };
  } else {
    bd.querySelector("#sub").onclick = async () => {
      try { await api(`/strategies/${id}/subscribe`, {method:"POST", body:{trade_size: size()}}); toast("Souscrit ✓"); done(); }
      catch (e) { toast(e.message, "error"); }
    };
  }
};

/* ═══════════════════════════════════════════════════
   MORE — Hub: Wallet, Settings, Reports, Analytics
═══════════════════════════════════════════════════ */
route(/^more$/, async () => {
  const me = APP.user;
  render(`
    <div class="page-title">Plus</div>
    <div class="card card-flush"><div class="list">
      <div class="list-item" onclick="go('more/wallet')">
        <div class="list-icon">💰</div>
        <div class="list-body"><div class="list-title">Wallet</div><div class="list-sub">${me.wallet_address ? shortAddr(me.wallet_address) : "Non configuré"}</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/strategy-wallet')">
        <div class="list-icon">🎯</div>
        <div class="list-body"><div class="list-title">Wallet stratégie</div><div class="list-sub">${me.strategy_wallet_address ? shortAddr(me.strategy_wallet_address) : "Non configuré"}</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/settings')">
        <div class="list-icon">⚙️</div>
        <div class="list-body"><div class="list-title">Réglages</div><div class="list-sub">Capital, risque, smart analysis, notifs</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/analytics')">
        <div class="list-icon">🧠</div>
        <div class="list-body"><div class="list-title">Analytics</div><div class="list-sub">Traders · Portfolio · Signaux · Efficacité</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/reports')">
        <div class="list-icon">📈</div>
        <div class="list-body"><div class="list-title">Rapports</div><div class="list-sub">Export HTML / PDF par période</div></div>
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

    <div class="section" style="text-align:center;padding-top:20px"><div class="small">WENPOLYMARKET · v4</div></div>
  `);
});

/* ═══════════════════════════════════════════════════
   WALLET (copy)
═══════════════════════════════════════════════════ */
route(/^more\/wallet$/, async () => {
  const me = APP.user;
  if (!me.wallet_address) {
    render(`
      <div class="page-title">Wallet</div>
      ${emptyState("👛", "Aucun wallet", "Créez un wallet Polygon ou importez une clé privée existante.")}
      <button class="btn btn-primary" onclick="go('more/wallet/create')">✨ Créer un wallet</button>
      <button class="btn btn-secondary" style="margin-top:10px" onclick="go('more/wallet/import')">📥 Importer une clé</button>
    `);
    setBack("more");
    return;
  }
  const bal = await api("/wallet/balance").catch(() => ({usdc:0, matic:0, address:me.wallet_address}));
  render(`
    ${modeBadge(me)}
    <div class="page-title">Wallet</div>
    <div class="hero">
      <div class="hero-value">${fmtUsd(me.paper_trading ? me.paper_balance : bal.usdc)}</div>
      <div class="hero-label">${me.paper_trading ? "USDC fictif (paper)" : "USDC disponible"}</div>
      ${!me.paper_trading ? `<div class="small" style="margin-top:10px">${bal.matic.toFixed(4)} MATIC · gas</div>` : ""}
    </div>
    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse Polygon</div>
      <div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="go('more/wallet/deposit')">📥 Déposer</button>
      <button class="btn btn-secondary" onclick="go('more/wallet/withdraw')">📤 Retirer</button>
    </div>
    <div class="section">
      ${sectionTitle("Avancé")}
      <div class="card card-flush"><div class="list">
        <div class="list-item" onclick="go('more/wallet/export')">
          <div class="list-icon">🔐</div>
          <div class="list-body"><div class="list-title">Exporter la clé privée</div><div class="list-sub">Sauvegarde ou import ailleurs</div></div>
          <div class="list-chevron">›</div>
        </div>
        <div class="list-item" onclick="window._walletDelete()">
          <div class="list-icon" style="background:rgba(255,69,58,0.15)">🗑</div>
          <div class="list-body"><div class="list-title" style="color:var(--red)">Supprimer ce wallet</div></div>
          <div class="list-chevron">›</div>
        </div>
      </div></div>
    </div>
  `);
  setBack("more");
}, {tab: "more", back: "more"});

window._walletDelete = async function() {
  const ok = await confirmModal("Supprimer ce wallet ?", "La clé privée sera effacée. Exportez-la avant si besoin.", "Supprimer", "danger");
  if (!ok) return;
  await api("/wallet", {method:"DELETE"}); invalidateAll(); toast("Wallet supprimé"); await loadUser(); go("more/wallet");
};

route(/^more\/wallet\/create$/, async () => {
  render(`
    <div class="page-title">Créer un wallet</div>
    <div class="alert warning"><h4>⚠ Attention</h4><p>Un nouveau wallet Polygon va être généré. La clé privée sera affichée <b>UNE SEULE FOIS</b>.</p></div>
    <button class="btn btn-primary" id="create-btn">✨ Générer mon wallet</button>
  `);
  setBack("more/wallet");
  document.getElementById("create-btn").onclick = async () => {
    try {
      const r = await api("/wallet/create", {method:"POST"});
      invalidateAll(); await loadUser();
      render(`
        <div class="page-title">✅ Wallet créé</div>
        <div class="alert"><h4>⚠ Sauvegardez MAINTENANT</h4><p>La clé ne sera plus affichée après.</p></div>
        <div class="card">
          <div class="tiny" style="margin-bottom:6px">Adresse</div>
          <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
          <div class="tiny" style="margin:14px 0 6px">Clé privée</div>
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)" onclick="copy('${r.private_key}')">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier la clé</button>
        </div>
        <button class="btn btn-secondary" style="margin-top:10px" onclick="go('more/wallet')">J'ai sauvegardé</button>
      `);
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "more", back: "more/wallet"});

route(/^more\/wallet\/import$/, async () => {
  render(`
    <div class="page-title">Importer un wallet</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Clé privée</label>
        <textarea class="input input-mono" id="pk-input" rows="3" placeholder="0x..." autocomplete="off" autocapitalize="off" spellcheck="false"></textarea>
        <div class="input-hint">64 caractères hex, avec ou sans préfixe 0x</div>
      </div>
    </div>
  `);
  setBack("more/wallet");
  setMainBtn("IMPORTER", async () => {
    const pk = document.getElementById("pk-input").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try { const r = await api("/wallet/import", {method:"POST", body:{private_key: pk}}); invalidateAll(); await loadUser(); toast("Importé: " + shortAddr(r.address)); go("more/wallet"); }
    catch (e) { toast(e.message, "error"); }
  });
}, {tab: "more", back: "more/wallet"});

route(/^more\/wallet\/deposit$/, async () => {
  const me = APP.user;
  render(`
    <div class="page-title">Déposer</div>
    <div class="alert info">
      <h4>ℹ Instructions</h4>
      <p>• Réseau : <b>Polygon</b> uniquement<br>• Token : <b>USDC.e</b><br>• Ajoutez aussi du <b>MATIC</b> (0.1) pour le gas<br>• Crédit ~3 sec</p>
    </div>
    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse de dépôt</div>
      <div class="addr-box mono" onclick="copy('${me.wallet_address}')">${me.wallet_address}</div>
      <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${me.wallet_address}')">📋 Copier</button>
    </div>
  `);
  setBack("more/wallet");
}, {tab: "more", back: "more/wallet"});

route(/^more\/wallet\/withdraw$/, async () => {
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
  setBack("more/wallet");
  setMainBtn("ENVOYER", async () => {
    const to = document.getElementById("to-addr").value.trim();
    const amt = parseFloat(document.getElementById("amount").value);
    if (!to.startsWith("0x") || to.length !== 42) return toast("Adresse invalide", "error");
    if (!amt || amt <= 0) return toast("Montant invalide", "error");
    if (amt > bal.usdc) return toast("Solde insuffisant", "error");
    const ok = await confirmModal("Confirmer retrait", `Envoyer ${fmtUsd(amt)} USDC à ${shortAddr(to)} ?\nIrréversible.`, "Envoyer");
    if (!ok) return;
    try {
      clearMainBtn(); toast("Transaction en cours…");
      const r = await api("/wallet/withdraw", {method:"POST", body:{to_address: to, amount: amt}});
      invalidate("wallet");
      render(`
        <div class="empty" style="padding:40px 20px">
          <div class="empty-icon">✅</div>
          <div class="empty-title" style="color:var(--green)">Retrait envoyé</div>
        </div>
        <div class="card">
          <div class="tiny" style="margin-bottom:8px">Transaction hash</div>
          <div class="addr-box mono" onclick="copy('${r.tx_hash}')">${r.tx_hash}</div>
          <a class="btn btn-secondary" href="https://polygonscan.com/tx/${r.tx_hash}" target="_blank" style="margin-top:12px">Voir sur Polygonscan ↗</a>
        </div>
        <button class="btn btn-primary" onclick="go('more/wallet')">Retour</button>
      `);
      setBack("more/wallet");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "more", back: "more/wallet"});

route(/^more\/wallet\/export$/, async () => {
  render(`
    <div class="page-title">Exporter la clé privée</div>
    <div class="alert">
      <h4>🔐 Zone dangereuse</h4>
      <p>Contrôle <b>total</b> du wallet. Ne partagez JAMAIS.</p>
    </div>
    <div class="card">
      <label class="toggle-row">
        <div class="toggle-label">Je comprends les risques</div>
        <div class="toggle"><input type="checkbox" id="c1"><span class="slider"></span></div>
      </label>
      <label class="toggle-row">
        <div class="toggle-label">Je ne suis pas en public</div>
        <div class="toggle"><input type="checkbox" id="c2"><span class="slider"></span></div>
      </label>
    </div>
    <button class="btn btn-danger" id="exp-btn">Afficher la clé</button>
  `);
  setBack("more/wallet");
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
        <button class="btn btn-secondary" onclick="go('more/wallet')">Terminé</button>
      `);
      setBack("more/wallet");
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "more", back: "more/wallet"});

/* Strategy wallet */
route(/^more\/strategy-wallet$/, async () => {
  const me = APP.user;
  if (!me.strategy_wallet_address) {
    render(`
      <div class="page-title">Wallet stratégie</div>
      ${emptyState("🎯", "Aucun wallet", "Wallet dédié aux stratégies, séparé du copy trading.")}
      <button class="btn btn-primary" id="sw-create">✨ Créer</button>
      <button class="btn btn-secondary" style="margin-top:10px" onclick="go('more/strategy-wallet/import')">📥 Importer</button>
    `);
    setBack("more");
    document.getElementById("sw-create").onclick = async () => {
      const ok = await confirmModal("Créer un wallet stratégie ?", "La clé sera affichée UNE SEULE FOIS.", "Créer");
      if (!ok) return;
      try {
        const r = await api("/strategy-wallet/create", {method:"POST"});
        invalidateAll(); await loadUser();
        render(`
          <div class="page-title">✅ Wallet créé</div>
          <div class="alert"><h4>⚠ Sauvegardez MAINTENANT</h4></div>
          <div class="card">
            <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
            <div class="addr-box mono" style="color:var(--red);margin-top:12px" onclick="copy('${r.private_key}')">${r.private_key}</div>
            <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
          </div>
          <button class="btn btn-secondary" style="margin-top:10px" onclick="go('more/strategy-wallet')">OK</button>
        `);
        setBack("more");
      } catch (e) { toast(e.message, "error"); }
    };
    return;
  }
  const bal = await api("/strategy-wallet/balance").catch(() => ({usdc:0, matic:0, address:me.strategy_wallet_address}));
  render(`
    <div class="page-title">Wallet stratégie</div>
    <div class="hero"><div class="hero-value">${fmtUsd(bal.usdc)}</div><div class="hero-label">USDC</div><div class="small" style="margin-top:8px">${bal.matic.toFixed(4)} MATIC</div></div>
    <div class="card"><div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div></div>
    <button class="btn btn-danger" id="sw-del">🗑 Supprimer</button>
  `);
  setBack("more");
  document.getElementById("sw-del").onclick = async () => {
    const ok = await confirmModal("Supprimer ?", "La clé sera effacée.", "Supprimer", "danger");
    if (!ok) return;
    await api("/strategy-wallet", {method:"DELETE"}); invalidateAll(); await loadUser(); toast("Supprimé"); go("more");
  };
}, {tab: "more", back: "more"});

route(/^more\/strategy-wallet\/import$/, async () => {
  render(`
    <div class="page-title">Importer clé stratégie</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Clé privée</label>
        <textarea class="input input-mono" id="sw-pk" rows="3" placeholder="0x..."></textarea>
      </div>
    </div>
  `);
  setBack("more/strategy-wallet");
  setMainBtn("IMPORTER", async () => {
    const pk = document.getElementById("sw-pk").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try { await api("/strategy-wallet/import", {method:"POST", body:{private_key: pk}}); invalidateAll(); await loadUser(); toast("Importé"); go("more/strategy-wallet"); }
    catch (e) { toast(e.message, "error"); }
  });
}, {tab: "more", back: "more/strategy-wallet"});

/* ═══════════════════════════════════════════════════
   SETTINGS
═══════════════════════════════════════════════════ */
route(/^more\/settings$/, async () => {
  const s = await api("/settings");
  const me = APP.user;

  const tgl = (key, label, sub, val) => `
    <label class="toggle-row">
      <div><div class="toggle-label">${label}</div>${sub ? `<div class="toggle-sub">${sub}</div>` : ""}</div>
      <div class="toggle"><input type="checkbox" data-key="${key}" ${val?"checked":""}><span class="slider"></span></div>
    </label>`;
  const num = (key, label, val, step=1, min=0, max=1000, hint) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <input class="input" type="number" data-key="${key}" value="${val ?? ""}" step="${step}" min="${min}" max="${max}">
      ${hint ? `<div class="input-hint">${hint}</div>` : ""}
    </div>`;
  const sel = (key, label, val, options, hint) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <select class="input" data-key="${key}">
        ${options.map(o => { const v = typeof o==='object'?o.value:o; const t = typeof o==='object'?o.label:o; return `<option value="${v}" ${v===val?"selected":""}>${t}</option>`; }).join("")}
      </select>
      ${hint ? `<div class="input-hint">${hint}</div>` : ""}
    </div>`;

  render(`
    <div class="page-title">Réglages</div>

    <div class="card">
      <div class="card-title">🔌 Mode de trading</div>
      ${me.paper_trading
        ? `<div class="alert info" style="margin-bottom:10px"><p><b>Actuellement en mode PAPER</b> — solde fictif ${fmtUsd(me.paper_balance)}, aucun USDC réel utilisé.</p></div>
           <button class="btn btn-danger" onclick="window._toggleMode(false)">⚠ Passer en mode LIVE (réel)</button>`
        : `<div class="alert warning" style="margin-bottom:10px"><p><b>Actuellement en mode LIVE</b> — trades réels avec USDC sur Polygon.</p></div>
           <button class="btn btn-secondary" onclick="window._toggleMode(true)">📝 Repasser en mode Paper</button>`}
      <div style="height:10px"></div>
      ${tgl("is_paused", "En pause", "Stoppe temporairement la copie", s.is_paused)}
    </div>

    <div class="card">
      <div class="card-title">💰 Capital & taille des trades</div>
      ${num("allocated_capital", "Capital alloué USDC", s.allocated_capital, 10, 10, 100000, "Capital total dédié au copy")}
      ${sel("sizing_mode", "Mode de sizing", s.sizing_mode || "fixed",
        [{value:"fixed", label:"🟰 Fixe — même montant à chaque trade"},
         {value:"percent", label:"% du capital par trade"},
         {value:"proportional", label:"📏 Proportionnel au master"},
         {value:"kelly", label:"🧠 Kelly (avancé)"}])}
      ${num("fixed_amount", "Montant fixe USDC", s.fixed_amount, 0.5, 0.1, 1000, "Si mode FIXE")}
      ${num("percent_per_trade", "% par trade", s.percent_per_trade, 0.5, 0.1, 100, "Si mode PERCENT")}
      ${num("multiplier", "Multiplicateur", s.multiplier, 0.1, 0.1, 10)}
      ${num("min_trade_usdc", "Min USDC", s.min_trade_usdc, 0.5, 0, 1000)}
      ${num("max_trade_usdc", "Max USDC", s.max_trade_usdc, 0.5, 0, 10000)}
      ${num("daily_limit_usdc", "Limite quotidienne USDC", s.daily_limit_usdc, 1, 0, 100000)}
    </div>

    <div class="card">
      <div class="card-title">🧠 Smart Analysis V3</div>
      ${tgl("signal_scoring_enabled", "Scoring activé", "Score chaque signal 0-100", s.signal_scoring_enabled)}
      ${num("min_signal_score", "Score minimum (0-100)", s.min_signal_score, 5, 0, 100, "Seuls les signaux ≥ sont copiés")}
      ${tgl("smart_filter_enabled", "Smart filter", "Filtres avancés par type", s.smart_filter_enabled)}
      ${tgl("skip_coin_flip", "Ignorer les 50/50", null, s.skip_coin_flip)}
      ${num("min_conviction_pct", "Conviction minimum %", s.min_conviction_pct, 0.5, 0, 100)}
      ${num("max_price_drift_pct", "Drift prix max %", s.max_price_drift_pct, 0.5, 0, 50)}

      <div class="section-title" style="margin-top:16px"><h2>Profils rapides</h2></div>
      <div class="btn-row cols-3">
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('prudent')">🛡 Prudent</button>
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('balanced')">⚖️ Équilibré</button>
        <button class="btn btn-secondary btn-sm" onclick="window._applyProfile('aggressive')">⚡ Agressif</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">🛡 Stop Loss & Take Profit</div>
      ${tgl("stop_loss_enabled", "Stop Loss", null, s.stop_loss_enabled)}
      ${num("stop_loss_pct", "Stop Loss %", s.stop_loss_pct, 1, 1, 100)}
      ${tgl("take_profit_enabled", "Take Profit", null, s.take_profit_enabled)}
      ${num("take_profit_pct", "Take Profit %", s.take_profit_pct, 1, 1, 500)}
      ${tgl("trailing_stop_enabled", "Trailing stop", "SL qui suit le prix", s.trailing_stop_enabled)}
      ${num("trailing_stop_pct", "Trailing %", s.trailing_stop_pct, 1, 1, 100)}
      ${tgl("time_exit_enabled", "Time exit", "Close après X heures", s.time_exit_enabled)}
      ${num("time_exit_hours", "Heures", s.time_exit_hours, 1, 1, 720)}
      ${tgl("scale_out_enabled", "Scale out", "Prise de profit partielle", s.scale_out_enabled)}
      ${num("scale_out_pct", "% TP1", s.scale_out_pct, 5, 5, 95)}
    </div>

    <div class="card">
      <div class="card-title">📊 Risque portefeuille</div>
      ${num("max_positions", "Max positions ouvertes", s.max_positions, 1, 1, 100)}
      ${num("max_category_exposure_pct", "Max % / catégorie", s.max_category_exposure_pct, 5, 5, 100, "Ex: 30% max sur Crypto")}
      ${num("max_direction_bias_pct", "Max biais YES/NO %", s.max_direction_bias_pct, 5, 50, 100)}
      ${tgl("auto_pause_cold_traders", "Pause auto traders cold", "Si win rate bas", s.auto_pause_cold_traders)}
      ${num("cold_trader_threshold", "Seuil cold %", s.cold_trader_threshold, 1, 0, 100)}
      ${num("hot_streak_boost", "Boost hot streak", s.hot_streak_boost, 0.1, 1, 5)}
    </div>

    <div class="card">
      <div class="card-title">⛽ Gas & Timing</div>
      ${sel("gas_mode", "Vitesse gas", s.gas_mode || "fast",
        [{value:"normal", label:"🐢 Normal — 30 gwei (~2s)"},
         {value:"fast", label:"🚀 Fast — 50 gwei (~1.5s)"},
         {value:"ultra", label:"⚡ Ultra — 100 gwei (<1s)"},
         {value:"instant", label:"💎 Instant — 200 gwei"}])}
      ${num("copy_delay_seconds", "Délai avant copie (sec)", s.copy_delay_seconds, 1, 0, 600)}
      ${tgl("manual_confirmation", "Confirmation manuelle", "Demander avant gros trades", s.manual_confirmation)}
      ${num("confirmation_threshold_usdc", "Seuil USDC", s.confirmation_threshold_usdc, 1, 0, 10000)}
    </div>

    <div class="card">
      <div class="card-title">🔔 Notifications</div>
      ${sel("notification_mode", "Destination", s.notification_mode || "dm",
        [{value:"dm", label:"📱 Direct message"},
         {value:"group", label:"👥 Groupe (topic)"},
         {value:"both", label:"📨 Les deux"}])}
      ${tgl("notify_on_buy", "Sur achats", null, s.notify_on_buy)}
      ${tgl("notify_on_sell", "Sur ventes", null, s.notify_on_sell)}
      ${tgl("notify_on_sl_tp", "SL / TP déclenchés", null, s.notify_on_sl_tp)}
    </div>

    <div class="card">
      <div class="card-title">🎯 Stratégies</div>
      ${num("strategy_trade_fee_rate", "Fee rate", s.strategy_trade_fee_rate, 0.01, 0.01, 0.20, "1% à 20%")}
      ${num("strategy_max_trades_per_day", "Max trades/jour", s.strategy_max_trades_per_day, 1, 1, 200)}
      ${tgl("strategy_is_paused", "Stratégies en pause", null, s.strategy_is_paused)}
    </div>

    <div style="height:20px"></div>
  `);
  setBack("more");

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
    if (el.type === "checkbox" || el.tagName === "SELECT") el.addEventListener("change", send);
    else el.addEventListener("input", () => { clearTimeout(debounce[key]); debounce[key] = setTimeout(send, 600); });
  });
}, {tab: "more", back: "more"});

window._applyProfile = async function(profile) {
  const names = {prudent: "Prudent", balanced: "Équilibré", aggressive: "Agressif"};
  const ok = await confirmModal("Appliquer " + names[profile] + " ?", "Remplace tes paramètres de scoring par le preset.", "Appliquer");
  if (!ok) return;
  try { await api("/settings/scoring-profile", {method:"POST", body:{profile}}); toast("Profil appliqué ✓"); dispatch(); }
  catch (e) { toast(e.message, "error"); }
};

/* ═══════════════════════════════════════════════════
   ANALYTICS — 4 onglets
═══════════════════════════════════════════════════ */
route(/^more\/analytics$/, async () => { go("more/analytics/traders"); }, {tab: "more", back: "more"});

const analyticsNav = (active) => subNav([
  {label:"Traders", href:"more/analytics/traders"},
  {label:"Portfolio", href:"more/analytics/portfolio"},
  {label:"Signaux", href:"more/analytics/signals"},
  {label:"Efficacité", href:"more/analytics/filters"},
], active);

route(/^more\/analytics\/traders$/, async () => {
  const d = await api("/analytics/traders");
  const catBadge = (c) => c === "hot" ? badge("🔥 HOT", "green")
    : c === "cold" ? badge("❄️ COLD", "red")
    : c === "warm" ? badge("Actif", "blue")
    : badge("Nouveau", "muted");
  render(`
    <div class="page-title">Analytics · Traders</div>
    ${analyticsNav("more/analytics/traders")}
    ${d.traders.length === 0
      ? emptyState("👥", "Aucune donnée", "Ajoutez des traders pour voir leurs analytics.")
      : d.traders.map(t => `
          <div class="card">
            <div class="card-header">
              <div style="display:flex;align-items:center;gap:10px">
                <div class="avatar" style="width:36px;height:36px;font-size:14px">${t.wallet_short.slice(2,4).toUpperCase()}</div>
                <div>
                  <div class="mono" style="font-weight:600">${t.wallet_short}</div>
                  <div class="small">${t.total_trades_30d} trades · 30j</div>
                </div>
              </div>
              <div style="text-align:right">
                ${catBadge(t.category)}
                ${t.current_streak >= 3 ? `<div style="margin-top:4px">${badge((t.streak_type==='win'?'🔥 '+t.current_streak+'W':'❄️ '+t.current_streak+'L'), t.streak_type==='win'?'green':'red')}</div>` : ''}
              </div>
            </div>
            <div class="stats-inline">
              <div class="stat-mini"><div class="stat-value ${pnlClass(t.pnl_30d)}">${pnlSign(t.pnl_30d)}</div><div class="stat-label">PnL</div></div>
              <div class="stat-mini"><div class="stat-value">${fmtPct(t.win_rate)}</div><div class="stat-label">Win rate</div></div>
              <div class="stat-mini"><div class="stat-value">${t.wins}/${t.losses}</div><div class="stat-label">W/L</div></div>
            </div>
            ${t.strong_categories.length > 0 ? `
              <div class="small" style="margin-top:10px"><b>✅ Forts :</b> ${t.strong_categories.map(c => `${c.category} (${fmtPct(c.win_rate)})`).join(", ")}</div>` : ""}
            ${t.weak_categories.length > 0 ? `
              <div class="small" style="margin-top:4px"><b>❌ Faibles :</b> ${t.weak_categories.map(c => `${c.category} (${fmtPct(c.win_rate)})`).join(", ")}</div>` : ""}
          </div>`).join("")}
  `);
  setBack("more");
}, {tab: "more", back: "more"});

route(/^more\/analytics\/portfolio$/, async () => {
  const d = await api("/analytics/portfolio");
  render(`
    <div class="page-title">Analytics · Portfolio</div>
    ${analyticsNav("more/analytics/portfolio")}
    <div class="hero"><div class="hero-value">${fmtUsd(d.total_open_value)}</div><div class="hero-label">Valeur positions ouvertes</div></div>
    ${statsGrid([
      {value: d.open_count, label: "Positions"},
      {value: d.by_source.length, label: "Sources"},
    ])}
    ${d.by_source.length > 0 ? `
      <div class="section">${sectionTitle("Répartition par source")}
        <div class="card">
          ${d.by_source.slice(0,10).map(s => `
            <div style="margin-bottom:12px">
              <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
                <span class="mono">${s.source.length > 30 ? s.source.slice(0,10)+'…'+s.source.slice(-4) : s.source}</span>
                <span>${fmtUsd(s.value)} · ${s.pct}%</span>
              </div>
              <div class="progress"><div class="progress-fill" style="width:${s.pct}%"></div></div>
            </div>`).join("")}
        </div>
      </div>` : ""}
    ${d.positions.length > 0 ? `
      <div class="section">${sectionTitle("Positions (" + d.positions.length + ")")}
        <div class="card card-flush"><div class="list">${d.positions.map(p => `
          <div class="list-item">
            <div class="list-body">
              <div class="list-title">${esc(p.market_question)}</div>
              <div class="list-sub">${p.shares.toFixed(2)} @ ${p.price.toFixed(4)} · ${p.age_hours}h</div>
            </div>
            <div class="list-right">${fmtUsd(p.amount)}</div>
          </div>`).join("")}</div></div>
      </div>` : ""}
  `);
  setBack("more");
}, {tab: "more", back: "more"});

route(/^more\/analytics\/signals$/, async () => {
  const d = await api("/analytics/signals");
  const maxCount = Math.max(1, ...d.by_day.map(x => x.count));
  render(`
    <div class="page-title">Analytics · Signaux</div>
    ${analyticsNav("more/analytics/signals")}
    ${statsGrid([
      {value: d.total_7d, label: "Trades 7j"},
      {value: d.avg_per_day, label: "Moy / jour"},
    ])}
    <div class="section">${sectionTitle("Activité par jour")}
      <div class="card">
        ${d.by_day.length === 0
          ? `<div class="small" style="text-align:center;padding:20px 0">Aucune activité</div>`
          : d.by_day.map(x => `
              <div style="margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
                  <span>${x.date}</span><span>${x.count} trades</span>
                </div>
                <div class="progress"><div class="progress-fill" style="width:${(x.count/maxCount)*100}%;background:var(--tg-btn)"></div></div>
              </div>`).join("")}
      </div>
    </div>
  `);
  setBack("more");
}, {tab: "more", back: "more"});

route(/^more\/analytics\/filters$/, async () => {
  const d = await api("/analytics/filters");
  const crit = d.scoring_criteria || {};
  render(`
    <div class="page-title">Analytics · Efficacité filtres</div>
    ${analyticsNav("more/analytics/filters")}
    <div class="alert info">
      <h4>ℹ À quoi sert cette vue ?</h4>
      <p>Comprendre comment tes filtres actuels impactent le nombre de signaux exécutés. Si trop restrictif, tu rates des opportunités. Si trop permissif, tu perds en qualité.</p>
    </div>
    ${statsGrid([
      {value: d.smart_filter_enabled ? "✓" : "✗", label: "Smart filter"},
      {value: d.signal_scoring_enabled ? "✓" : "✗", label: "Scoring"},
      {value: d.min_signal_score + "/100", label: "Score min"},
      {value: d.trades_executed_30d, label: "Trades 30j"},
    ], 4)}
    ${Object.keys(crit).length > 0 ? `
      <div class="section">${sectionTitle("Poids des critères")}
        <div class="card">
          ${Object.entries(crit).map(([name, c]) => `
            <div style="margin-bottom:10px">
              <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:4px">
                <span>${c.on ? '✓' : '✗'} ${name}</span>
                <span>${c.w || 0}%</span>
              </div>
              <div class="progress"><div class="progress-fill" style="width:${c.w||0}%;background:${c.on?'var(--green)':'var(--tg-hint)'}"></div></div>
            </div>`).join("")}
        </div>
      </div>` : ""}
    <button class="btn btn-primary" onclick="go('more/settings')">⚙️ Ajuster les réglages</button>
  `);
  setBack("more");
}, {tab: "more", back: "more"});

/* ═══════════════════════════════════════════════════
   REPORTS + Export HTML
═══════════════════════════════════════════════════ */
route(/^more\/reports$/, async () => {
  const [day, week, month, byTrader, byMarket] = await Promise.all([
    api("/reports/pnl?period=day"),
    api("/reports/pnl?period=week"),
    api("/reports/pnl?period=month"),
    api("/reports/by-trader"),
    api("/reports/by-market"),
  ]);

  const pnlCard = (title, r, period) => `
    <div class="card">
      <div class="card-header">
        <div class="h3">${title}</div>
        <div style="display:flex;align-items:center;gap:8px">
          <span class="${pnlClass(r.pnl)}" style="font-weight:700;font-size:18px">${pnlSign(r.pnl)}</span>
          <button class="btn btn-ghost btn-icon" onclick="window._exportReport('${period}')" title="Exporter">⬇</button>
        </div>
      </div>
      <div class="stats-inline">
        <div class="stat-mini"><div class="stat-value">${r.trades}</div><div class="stat-label">Trades</div></div>
        <div class="stat-mini"><div class="stat-value">${fmtPct(r.win_rate)}</div><div class="stat-label">Win rate</div></div>
        <div class="stat-mini"><div class="stat-value ${pnlClass(r.best_trade)}">${fmtUsd(r.best_trade)}</div><div class="stat-label">Best</div></div>
      </div>
    </div>`;

  render(`
    <div class="page-title">Rapports</div>
    ${pnlCard("Aujourd'hui", day, "day")}
    ${pnlCard("7 derniers jours", week, "week")}
    ${pnlCard("30 derniers jours", month, "month")}

    <div class="card">
      <div class="card-title">📄 Exporter un rapport HTML / PDF</div>
      <div class="small" style="margin-bottom:12px">Rapport détaillé imprimable (Ctrl+P pour PDF).</div>
      <div class="btn-row cols-3">
        <button class="btn btn-secondary btn-sm" onclick="window._exportReport('day')">📅 Jour</button>
        <button class="btn btn-primary btn-sm" onclick="window._exportReport('week')">📅 7j</button>
        <button class="btn btn-secondary btn-sm" onclick="window._exportReport('month')">📅 30j</button>
      </div>
    </div>

    <div class="section">${sectionTitle("Par trader")}
      ${byTrader.traders.length === 0
        ? `<div class="card small" style="text-align:center;padding:24px">Aucune donnée</div>`
        : `<div class="card card-flush"><div class="list">${byTrader.traders.slice(0,10).map(t => `
            <div class="list-item">
              <div class="avatar" style="width:36px;height:36px;font-size:14px">${t.wallet_short.slice(2,4).toUpperCase()}</div>
              <div class="list-body"><div class="list-title mono">${t.wallet_short}</div><div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div></div>
              <div class="list-right ${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>
            </div>`).join("")}</div></div>`}
    </div>
    <div class="section">${sectionTitle("Par marché")}
      ${byMarket.markets.length === 0
        ? `<div class="card small" style="text-align:center;padding:24px">Aucune donnée</div>`
        : `<div class="card card-flush"><div class="list">${byMarket.markets.slice(0,10).map(m => `
            <div class="list-item">
              <div class="list-icon">📊</div>
              <div class="list-body"><div class="list-title">${esc(m.market_question)}</div><div class="list-sub">${m.trade_count} trades · ${fmtUsd(m.volume)}</div></div>
              <div class="list-right ${pnlClass(m.pnl)}" style="font-weight:600">${pnlSign(m.pnl)}</div>
            </div>`).join("")}</div></div>`}
    </div>
  `);
  setBack("more");
}, {tab: "more", back: "more"});

window._exportReport = function(period) {
  // Use ?auth= query param so the URL is self-contained
  const url = `/miniapp/api/reports/export.html?period=${period}&auth=${encodeURIComponent(APP.initData)}`;
  const fullUrl = new URL(url, location.origin).href;
  if (tg?.openLink) tg.openLink(fullUrl);
  else window.open(fullUrl, "_blank");
  toast("Rapport ouvert ↗");
};

/* ═══════════════════════════════════════════════════
   BOOTSTRAP
═══════════════════════════════════════════════════ */
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
        <div class="empty-text">Cette page doit être ouverte via le bouton Mini App dans le bot.</div>
      </div>`;
    return;
  }
  document.getElementById("app").innerHTML = `
    <div class="header">WENPOLYMARKET<div class="header-sub">Polymarket Copy &amp; Strategies</div></div>
    <div id="content" class="page"></div>
    <div class="tab-bar">
      <a href="#home" data-tab="home"><span class="tab-icon">🏠</span><span>Accueil</span></a>
      <a href="#copy" data-tab="copy"><span class="tab-icon">👥</span><span>Copy</span></a>
      <a href="#discover" data-tab="discover"><span class="tab-icon">🔍</span><span>Découvrir</span></a>
      <a href="#strategies" data-tab="strategies"><span class="tab-icon">🎯</span><span>Stratégies</span></a>
      <a href="#more" data-tab="more"><span class="tab-icon">⋯</span><span>Plus</span></a>
    </div>`;
  try { await loadUser(); }
  catch (e) { showError("Impossible de charger le profil: " + e.message); return; }
  window.addEventListener("hashchange", dispatch);
  dispatch();
}

window.go = go; window.copy = copy; window.dispatch = dispatch; window.loadUser = loadUser;
init();

