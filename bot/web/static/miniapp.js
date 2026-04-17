/* WENPOLYMARKET Mini App — v2 SPA */

const tg = window.Telegram?.WebApp;
const APP = { initData: tg?.initData || "", user: null, cache: new Map(), mainBtnHandler: null, backHandler: null };

/* ── API ─────────────────────────────────────────── */
async function api(path, opts = {}) {
  const res = await fetch("/miniapp/api" + path, {
    method: opts.method || "GET",
    headers: {
      "Authorization": "tma " + APP.initData,
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
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
function invalidate(prefix) {
  for (const k of [...APP.cache.keys()]) if (k.startsWith(prefix)) APP.cache.delete(k);
}
function invalidateAll() { APP.cache.clear(); }

/* ── Utils ───────────────────────────────────────── */
const fmtUsd = x => "$" + Number(x || 0).toFixed(2);
const fmtPct = x => Number(x || 0).toFixed(1) + "%";
const fmtDelta = x => (x >= 0 ? "+" : "") + Number(x || 0).toFixed(2) + "%";
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

function copy(text) {
  navigator.clipboard?.writeText(text).then(() => toast("Copié"));
  haptic("light");
}

/* ── Toast / Modal ───────────────────────────────── */
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
        <div class="modal-sub">${esc(text)}</div>
        <button class="btn btn-${variant}" id="cm-ok">${esc(confirmText)}</button>
        <button class="btn btn-secondary" id="cm-cancel" style="margin-top:8px">Annuler</button>
      </div>`;
    document.body.appendChild(bd);
    bd.querySelector("#cm-ok").onclick = () => { bd.remove(); resolve(true); };
    bd.querySelector("#cm-cancel").onclick = () => { bd.remove(); resolve(false); };
    bd.addEventListener("click", e => { if (e.target === bd) { bd.remove(); resolve(false); } });
  });
}

/* Bottom sheet */
function sheet(contentHtml) {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "sheet-backdrop";
    bd.innerHTML = `<div class="sheet">${contentHtml}</div>`;
    document.body.appendChild(bd);
    bd.addEventListener("click", e => { if (e.target === bd) { bd.remove(); resolve(null); } });
    resolve({
      el: bd.querySelector(".sheet"),
      close: (v) => { bd.remove(); return v; },
    });
  });
}

/* ── Layout helpers ─────────────────────────────── */
function render(html) { document.getElementById("content").innerHTML = html; }

function setTab(name) {
  document.querySelectorAll(".tab-bar a").forEach(a => {
    a.classList.toggle("active", a.dataset.tab === name);
  });
}

function setBack(hash) {
  if (!tg?.BackButton) return;
  if (APP.backHandler) { try { tg.BackButton.offClick(APP.backHandler); } catch {} }
  if (hash) {
    APP.backHandler = () => { haptic("light"); go(hash); };
    tg.BackButton.onClick(APP.backHandler);
    tg.BackButton.show();
  } else {
    tg.BackButton.hide();
  }
}

function setMainBtn(text, onClick, color) {
  if (!tg?.MainButton) return;
  if (APP.mainBtnHandler) { try { tg.MainButton.offClick(APP.mainBtnHandler); } catch {} }
  APP.mainBtnHandler = () => { haptic("medium"); onClick(); };
  tg.MainButton.setText(text);
  if (color) tg.MainButton.color = color;
  tg.MainButton.onClick(APP.mainBtnHandler);
  tg.MainButton.show();
}

function clearMainBtn() {
  if (!tg?.MainButton) return;
  if (APP.mainBtnHandler) { try { tg.MainButton.offClick(APP.mainBtnHandler); } catch {} }
  APP.mainBtnHandler = null;
  tg.MainButton.hide();
}

/* ── Components (HTML builders) ──────────────────── */
const skeleton = (n=3) => `
  <div class="skeleton skeleton-hero"></div>
  <div class="stats" style="margin-bottom:12px">
    ${Array(4).fill(0).map(() => `<div class="skeleton skeleton-stat"></div>`).join("")}
  </div>
  ${Array(n).fill(0).map(() => `
    <div class="card">
      <div class="skeleton skeleton-line wide"></div>
      <div class="skeleton skeleton-line half"></div>
    </div>`).join("")}
`;

const hero = (value, label, delta) => `
  <div class="hero">
    <div class="hero-value ${pnlClass(parseFloat(value))}">${value}</div>
    <div class="hero-label">${esc(label)}</div>
    ${delta !== undefined && delta !== null
      ? `<div class="hero-delta ${delta < 0 ? 'neg' : ''}">${fmtDelta(delta)}</div>` : ""}
  </div>`;

const stat = (v, l, cls="") => `<div class="stat"><div class="stat-value ${cls}">${v}</div><div class="stat-label">${esc(l)}</div></div>`;

const statsGrid = (items, cols=2) => `
  <div class="stats ${cols===4?'cols-4':cols===3?'cols-3':''}">
    ${items.map(i => stat(i.value, i.label, i.cls || "")).join("")}
  </div>`;

const subNav = (items, active) => `
  <div class="sub-nav">
    ${items.map(i => `
      <a href="#${i.href}" class="sub-nav-item ${i.href === active ? "active" : ""}" data-subnav>
        ${esc(i.label)}${i.count != null ? ` <span class="sub-nav-count">${i.count}</span>` : ""}
      </a>`).join("")}
  </div>`;

const sectionTitle = (label, action) => `
  <div class="section-title">
    <h2>${esc(label)}</h2>
    ${action ? `<a class="card-action" onclick="${action.onclick}">${esc(action.label)} ›</a>` : ""}
  </div>`;

const emptyState = (icon, title, text, btn) => `
  <div class="empty">
    <div class="empty-icon">${icon}</div>
    <div class="empty-title">${esc(title)}</div>
    ${text ? `<div class="empty-text">${esc(text)}</div>` : ""}
    ${btn ? `<button class="btn btn-primary" style="max-width:240px;margin:0 auto" onclick="${btn.onclick}">${esc(btn.label)}</button>` : ""}
  </div>`;

const badge = (text, variant="blue") => `<span class="badge badge-${variant}">${esc(text)}</span>`;

/* ── Router ──────────────────────────────────────── */
const routes = [];
function route(pattern, handler, opts={}) { routes.push({pattern, handler, opts}); }
function go(hash) { location.hash = hash; }

const KNOWN_TABS = ["home", "copy", "strategies", "wallet", "more"];

async function dispatch() {
  let hash = location.hash.slice(1);
  // Ignore Telegram framework hash params (tgWebAppData=..., tgWebAppVersion=..., etc.)
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
      try {
        render(skeleton(2));
        await r.handler(m);
      } catch (e) {
        showError(e.message);
      }
      return;
    }
  }
  // No route matched a valid tab -> fall back to home
  history.replaceState(null, "", "#home");
  location.hash = "home";
}

function showError(msg) {
  render(`
    <div class="empty">
      <div class="empty-icon">⚠️</div>
      <div class="empty-title" style="color:var(--red)">Erreur</div>
      <div class="empty-text">${esc(msg)}</div>
      <button class="btn btn-secondary" style="max-width:200px;margin:0 auto" onclick="dispatch()">Réessayer</button>
    </div>`);
}

/* ═══════════════════════════════════════════════════
   SCREENS
═══════════════════════════════════════════════════ */

/* ── HOME / Accueil ─────────────────────────────── */
route(/^home$/, async () => {
  const me = APP.user;
  const [copyStats, stratStats, week, recent] = await Promise.all([
    cached("copy-stats", () => api("/copy/stats")),
    cached("strat-stats", () => api("/strategies/stats")),
    cached("pnl-week", () => api("/reports/pnl?period=week")),
    cached("recent", () => api("/copy/trades?limit=5")),
  ]);

  const totalPnl = (copyStats.total_pnl || 0) + (stratStats.total_pnl || 0);

  let balanceHtml;
  if (me.wallet_address) {
    try {
      const bal = await cached("wallet-bal", () => api("/wallet/balance"), 15000);
      balanceHtml = `
        <div class="card">
          <div class="card-header">
            <div class="tiny">Wallet Copy</div>
            <a class="card-action" onclick="go('wallet')">Gérer ›</a>
          </div>
          <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:10px">
            <div><span style="font-size:22px;font-weight:700">${fmtUsd(bal.usdc)}</span>
                 <span class="small" style="margin-left:4px">USDC</span></div>
            <div class="small">${bal.matic.toFixed(4)} MATIC</div>
          </div>
          <div class="addr-box mono" onclick="copy('${bal.address}')">${shortAddr(bal.address)} · copier</div>
          <div class="btn-row" style="margin-top:12px">
            <button class="btn btn-primary btn-sm" onclick="go('wallet/deposit')">📥 Déposer</button>
            <button class="btn btn-secondary btn-sm" onclick="go('wallet/withdraw')">📤 Retirer</button>
          </div>
        </div>`;
    } catch {
      balanceHtml = `<div class="card"><div class="small">Balance indisponible</div></div>`;
    }
  } else {
    balanceHtml = `
      <div class="alert info">
        <h4>👛 Configurez votre wallet</h4>
        <p>Créez ou importez un wallet Polygon pour commencer à copy-trader.</p>
        <button class="btn btn-primary btn-sm" style="margin-top:10px" onclick="go('wallet')">Configurer maintenant</button>
      </div>`;
  }

  render(`
    ${hero(fmtUsd(totalPnl), "PnL Total", week.trades > 0 ? null : undefined)}

    ${balanceHtml}

    <div class="quick-grid">
      <button class="quick-action" onclick="go('copy/traders')">
        <div class="quick-action-icon">👥</div>
        <div class="quick-action-label">Traders suivis</div>
      </button>
      <button class="quick-action" onclick="go('strategies')">
        <div class="quick-action-icon">🎯</div>
        <div class="quick-action-label">Stratégies</div>
      </button>
      <button class="quick-action" onclick="go('copy/positions')">
        <div class="quick-action-icon">📊</div>
        <div class="quick-action-label">Positions</div>
      </button>
      <button class="quick-action" onclick="go('more/reports')">
        <div class="quick-action-icon">📈</div>
        <div class="quick-action-label">Rapports</div>
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
                ${t.settlement_pnl !== null
                  ? `<span class="${pnlClass(t.settlement_pnl)}">${pnlSign(t.settlement_pnl)}</span>`
                  : `<span class="small">${fmtUsd(t.amount)}</span>`}
              </div>
            </div>`).join("")}</div></div>`}
    </div>
  `);
});

/* ── COPY ─────────────────────────────────────────── */
route(/^copy$/, async () => { go("copy/traders"); });

route(/^copy\/traders$/, async () => {
  const traders = await api("/copy/traders");
  const positions = await cached("copy-positions", () => api("/copy/positions"));
  const trades = await cached("copy-trades-20", () => api("/copy/trades?limit=20"));

  render(`
    <div class="page-title">Copy Trading</div>
    ${subNav([
      {label:"Traders", href:"copy/traders", count: traders.count},
      {label:"Positions", href:"copy/positions", count: positions.count},
      {label:"Historique", href:"copy/history", count: trades.count || null},
    ], "copy/traders")}

    ${traders.count === 0
      ? emptyState("👥", "Aucun trader suivi", "Ajoutez un wallet Polygon pour copier ses trades automatiquement.",
          {label:"+ Ajouter un trader", onclick:"go('copy/traders/add')"})
      : `
        <div class="card card-flush">
          <div class="list">
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
          </div>
        </div>
        <button class="btn btn-primary" style="margin-top:12px" onclick="go('copy/traders/add')">+ Ajouter un trader</button>`
    }
  `);
}, {tab: "copy"});

route(/^copy\/positions$/, async () => {
  const {positions, count} = await cached("copy-positions", () => api("/copy/positions"));
  const traders = await cached("copy-traders", () => api("/copy/traders"));
  render(`
    <div class="page-title">Copy Trading</div>
    ${subNav([
      {label:"Traders", href:"copy/traders", count: traders.count},
      {label:"Positions", href:"copy/positions", count: count},
      {label:"Historique", href:"copy/history"},
    ], "copy/positions")}

    ${count === 0
      ? emptyState("📭", "Aucune position ouverte", "Les positions actives apparaîtront ici dès qu'un trade sera copié.")
      : `<div class="card card-flush"><div class="list">${positions.map(p => `
          <div class="list-item">
            <div class="list-icon">💼</div>
            <div class="list-body">
              <div class="list-title">${esc(p.market_question)}</div>
              <div class="list-sub">${p.shares.toFixed(2)} shares @ ${p.price.toFixed(4)} · ${p.master_wallet}</div>
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
    <div class="page-title">Ajouter un trader</div>
    <div class="card">
      <div class="form-row">
        <label class="label">Adresse Polygon</label>
        <input class="input input-mono" id="addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
        <div class="input-hint">Collez l'adresse Ethereum/Polygon du trader à copier</div>
      </div>
    </div>
  `);
  setBack("copy/traders");
  setMainBtn("SUIVRE CE TRADER", async () => {
    const w = document.getElementById("addr").value.trim();
    if (!w) return toast("Adresse requise", "error");
    try {
      await api("/copy/traders/add", {method:"POST", body:{wallet: w}});
      invalidate("copy-");
      toast("Trader ajouté");
      go("copy/traders");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "copy"});

route(/^copy\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
  const wallet = m[1];
  const d = await api("/copy/traders/" + wallet + "/stats");
  render(`
    <div style="text-align:center;padding:16px 0 20px">
      <div class="avatar" style="width:64px;height:64px;font-size:22px;margin:0 auto 10px">${wallet.slice(2,4).toUpperCase()}</div>
      <div class="h2 mono">${shortAddr(wallet)}</div>
      <div class="small" style="margin-top:2px">${d.trade_count} trades copiés</div>
    </div>

    ${statsGrid([
      {value: fmtUsd(d.volume), label: "Volume"},
      {value: pnlSign(d.pnl), label: "PnL", cls: pnlClass(d.pnl)},
    ])}

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
                ${t.pnl !== null
                  ? `<span class="${pnlClass(t.pnl)}">${pnlSign(t.pnl)}</span>`
                  : `<span>${fmtUsd(t.amount)}</span>`}
              </div>
            </div>`).join("")}</div></div>`}
    </div>

    <div class="section">
      <div class="card">
        <div class="addr-box mono" onclick="copy('${wallet}')">${wallet}</div>
      </div>
      <button class="btn btn-danger" style="margin-top:10px" onclick="window._trUnfollow('${wallet}')">🗑 Ne plus suivre</button>
    </div>
  `);
  setBack("copy/traders");
}, {tab: "copy"});

window._trUnfollow = async function(wallet) {
  const ok = await confirmModal("Arrêter de suivre ?", shortAddr(wallet) + " — vos positions existantes ne seront pas affectées.", "Retirer", "danger");
  if (!ok) return;
  await api("/copy/traders/" + wallet, {method:"DELETE"});
  invalidate("copy-");
  toast("Trader retiré");
  go("copy/traders");
};

/* ── STRATEGIES ───────────────────────────────────── */
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
    walletBanner = `
      <div class="alert warning">
        <h4>⚠ Wallet stratégie manquant</h4>
        <p>Vous êtes abonné à ${activeSubs.length} stratégie(s) mais n'avez pas encore configuré de wallet dédié.</p>
        <button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="go('more/strategy-wallet')">Configurer</button>
      </div>`;
  }

  render(`
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
      {value: activeSubs.length, label: "Abonnements"},
    ], 4)}

    <div class="section">
      ${strategies.length === 0
        ? emptyState("🎯", "Aucune stratégie disponible", "Les stratégies publiques seront listées ici dès leur activation.")
        : strategies.map(s => `
          <div class="card" style="cursor:pointer" onclick="window._stratOpen('${s.id}')">
            <div class="card-header">
              <div class="h3">${esc(s.name)}</div>
              ${s.subscribed ? badge("Abonné", "green") : badge(s.status, "blue")}
            </div>
            ${s.description ? `<div class="small" style="margin-bottom:12px;line-height:1.5">${esc(s.description)}</div>` : ""}
            <div class="stats-inline">
              <div class="stat-mini">
                <div class="stat-value ${pnlClass(s.total_pnl)}">${pnlSign(s.total_pnl)}</div>
                <div class="stat-label">PnL</div>
              </div>
              <div class="stat-mini">
                <div class="stat-value">${fmtPct(s.win_rate)}</div>
                <div class="stat-label">Win rate</div>
              </div>
              <div class="stat-mini">
                <div class="stat-value">${s.total_trades}</div>
                <div class="stat-label">Trades</div>
              </div>
            </div>
          </div>`).join("")}
    </div>
  `);
});

route(/^strategies\/my$/, async () => {
  const [{strategies}, {subscriptions}] = await Promise.all([api("/strategies"), api("/strategies/subscriptions")]);
  const stats = await cached("strat-stats", () => api("/strategies/stats"));
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

    <div class="section">
      ${sectionTitle("Dernières exécutions")}
      <div class="card">
        <div class="btn-row">
          <div class="stat" style="padding:12px 8px">
            <div class="stat-value">${stats.wins}/${stats.resolved}</div>
            <div class="stat-label">W / L</div>
          </div>
          <div class="stat" style="padding:12px 8px">
            <div class="stat-value ${pnlClass(stats.total_pnl)}">${pnlSign(stats.total_pnl)}</div>
            <div class="stat-label">PnL cumulé</div>
          </div>
        </div>
        <button class="btn btn-secondary" style="margin-top:10px" onclick="go('strategies/history')">Historique détaillé ›</button>
      </div>
    </div>
  `);
}, {tab: "strategies"});

route(/^strategies\/history$/, async () => {
  const {trades} = await api("/strategies/trades?limit=50");
  render(`
    <div class="page-title">Historique stratégies</div>
    ${trades.length === 0
      ? emptyState("📜", "Aucun trade", "Les exécutions de stratégies apparaîtront ici.")
      : `<div class="card card-flush"><div class="list">${trades.map(t => `
          <div class="list-item">
            <div class="list-icon">${t.result==='WON'?'✅':t.result==='LOST'?'❌':'⏳'}</div>
            <div class="list-body">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${esc(t.strategy_id)} · ${t.shares.toFixed(1)} @ ${t.price.toFixed(4)} · ${timeAgo(t.created_at)}</div>
            </div>
            <div class="list-right">
              ${t.pnl !== null
                ? `<div class="${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>`
                : `<div>${fmtUsd(t.amount)}</div>`}
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
      const ok = await confirmModal("Désinscrire ?", `De "${s.name}". Les positions existantes resteront en vie.`, "Désinscrire", "danger");
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

/* ── WALLET ──────────────────────────────────────── */
route(/^wallet$/, async () => {
  const me = APP.user;
  if (!me.wallet_address) {
    render(`
      <div class="page-title">Wallet</div>
      ${emptyState("👛", "Aucun wallet", "Créez un nouveau wallet Polygon ou importez une clé privée existante pour commencer.")}
      <button class="btn btn-primary" onclick="go('wallet/create')">✨ Créer un wallet</button>
      <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet/import')">📥 Importer une clé</button>
    `);
    return;
  }
  const bal = await api("/wallet/balance").catch(() => ({usdc:0, matic:0, address:me.wallet_address}));
  render(`
    <div class="page-title">Wallet</div>

    <div class="hero">
      <div class="hero-value">${fmtUsd(bal.usdc)}</div>
      <div class="hero-label">USDC disponible</div>
      <div class="small" style="margin-top:10px">${bal.matic.toFixed(4)} MATIC · gas disponible</div>
    </div>

    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse Polygon</div>
      <div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div>
      <div class="input-hint" style="margin-top:6px">Appuyez pour copier</div>
    </div>

    <div class="btn-row">
      <button class="btn btn-primary" onclick="go('wallet/deposit')">📥 Déposer</button>
      <button class="btn btn-secondary" onclick="go('wallet/withdraw')">📤 Retirer</button>
    </div>

    <div class="section">
      ${sectionTitle("Avancé")}
      <div class="card card-flush"><div class="list">
        <div class="list-item" onclick="go('wallet/export')">
          <div class="list-icon">🔐</div>
          <div class="list-body">
            <div class="list-title">Exporter la clé privée</div>
            <div class="list-sub">Pour sauvegarder ou importer ailleurs</div>
          </div>
          <div class="list-chevron">›</div>
        </div>
        <div class="list-item" onclick="window._walletDelete()">
          <div class="list-icon" style="background:rgba(255,69,58,0.15)">🗑</div>
          <div class="list-body">
            <div class="list-title" style="color:var(--red)">Supprimer ce wallet</div>
            <div class="list-sub">Effacer la clé de la base</div>
          </div>
          <div class="list-chevron">›</div>
        </div>
      </div></div>
    </div>
  `);
});

window._walletDelete = async function() {
  const ok = await confirmModal("Supprimer ce wallet ?", "La clé privée sera effacée de notre base. Assurez-vous de l'avoir exportée AVANT si vous souhaitez la conserver.", "Supprimer", "danger");
  if (!ok) return;
  await api("/wallet", {method:"DELETE"});
  invalidateAll();
  toast("Wallet supprimé");
  await loadUser();
  go("wallet");
};

route(/^wallet\/create$/, async () => {
  render(`
    <div class="page-title">Créer un wallet</div>
    <div class="alert warning">
      <h4>⚠ Attention</h4>
      <p>Un nouveau wallet Polygon va être généré. Sa clé privée sera affichée <b>UNE SEULE FOIS</b> — sauvegardez-la.</p>
    </div>
    <button class="btn btn-primary" id="create-btn">✨ Générer mon wallet</button>
    <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet')">Annuler</button>
  `);
  setBack("wallet");
  document.getElementById("create-btn").onclick = async () => {
    try {
      const r = await api("/wallet/create", {method:"POST"});
      invalidateAll();
      await loadUser();
      render(`
        <div class="page-title">✅ Wallet créé</div>
        <div class="alert">
          <h4>⚠ Sauvegardez MAINTENANT</h4>
          <p>La clé privée ne sera plus affichée après cet écran. Copiez-la dans un gestionnaire de mots de passe ou un endroit sûr.</p>
        </div>
        <div class="card">
          <div class="tiny" style="margin-bottom:6px">Adresse</div>
          <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
          <div class="tiny" style="margin:14px 0 6px">Clé privée</div>
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)" onclick="copy('${r.private_key}')">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier la clé privée</button>
        </div>
        <button class="btn btn-secondary" style="margin-top:10px" onclick="go('wallet')">J'ai sauvegardé, continuer</button>
      `);
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "wallet", back: "wallet"});

route(/^wallet\/import$/, async () => {
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
  setBack("wallet");
  setMainBtn("IMPORTER", async () => {
    const pk = document.getElementById("pk-input").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try {
      const r = await api("/wallet/import", {method:"POST", body:{private_key: pk}});
      invalidateAll();
      await loadUser();
      toast("Wallet importé: " + shortAddr(r.address));
      go("wallet");
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet"});

route(/^wallet\/deposit$/, async () => {
  const me = APP.user;
  render(`
    <div class="page-title">Déposer</div>

    <div class="alert info">
      <h4>ℹ Instructions</h4>
      <p>
        • Réseau : <b>Polygon</b> uniquement (pas Ethereum, pas BSC)<br>
        • Token : <b>USDC.e</b> (bridge Polygon, pas USDC natif)<br>
        • Envoyez aussi un peu de <b>MATIC</b> (0.1 suffit) pour payer le gas<br>
        • Crédité après 1 confirmation (~3 sec)
      </p>
    </div>

    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Votre adresse de dépôt</div>
      <div class="addr-box mono" onclick="copy('${me.wallet_address}')">${me.wallet_address}</div>
      <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${me.wallet_address}')">📋 Copier l'adresse</button>
    </div>
  `);
  setBack("wallet");
}, {tab: "wallet", back: "wallet"});

route(/^wallet\/withdraw$/, async () => {
  const bal = await api("/wallet/balance");
  render(`
    <div class="page-title">Retirer</div>

    <div class="hero" style="padding:20px">
      <div class="hero-value">${fmtUsd(bal.usdc)}</div>
      <div class="hero-label">Disponible</div>
    </div>

    <div class="card">
      <div class="form-row">
        <label class="label">Adresse destination</label>
        <input class="input input-mono" id="to-addr" placeholder="0x..." autocomplete="off" autocapitalize="off" />
        <div class="input-hint">Adresse Polygon — vérifiez-la deux fois</div>
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
  setBack("wallet");
  setMainBtn("ENVOYER", async () => {
    const to = document.getElementById("to-addr").value.trim();
    const amt = parseFloat(document.getElementById("amount").value);
    if (!to.startsWith("0x") || to.length !== 42) return toast("Adresse invalide", "error");
    if (!amt || amt <= 0) return toast("Montant invalide", "error");
    if (amt > bal.usdc) return toast("Solde insuffisant", "error");
    const ok = await confirmModal("Confirmer le retrait", `Envoyer ${fmtUsd(amt)} USDC à ${shortAddr(to)} ?\n\nLes transactions blockchain sont irréversibles.`, "Envoyer");
    if (!ok) return;
    try {
      clearMainBtn();
      toast("Transaction en cours…");
      const r = await api("/wallet/withdraw", {method:"POST", body:{to_address: to, amount: amt}});
      invalidate("wallet");
      render(`
        <div class="empty" style="padding:40px 20px">
          <div class="empty-icon">✅</div>
          <div class="empty-title" style="color:var(--green)">Retrait envoyé</div>
          <div class="empty-text">La transaction a été soumise au réseau Polygon.</div>
        </div>
        <div class="card">
          <div class="tiny" style="margin-bottom:8px">Transaction hash</div>
          <div class="addr-box mono" onclick="copy('${r.tx_hash}')">${r.tx_hash}</div>
          <a class="btn btn-secondary" href="https://polygonscan.com/tx/${r.tx_hash}" target="_blank" style="margin-top:12px">Voir sur Polygonscan ↗</a>
        </div>
        <button class="btn btn-primary" onclick="go('wallet')">Retour au wallet</button>
      `);
    } catch (e) { toast(e.message, "error"); }
  });
}, {tab: "wallet", back: "wallet"});

route(/^wallet\/export$/, async () => {
  render(`
    <div class="page-title">Exporter la clé privée</div>
    <div class="alert">
      <h4>🔐 Zone dangereuse</h4>
      <p>Votre clé privée donne un contrôle <b>total</b> du wallet. Quiconque la possède peut vider vos fonds. Ne la partagez jamais, ne la collez pas en ligne.</p>
    </div>
    <div class="card">
      <label class="toggle-row">
        <div>
          <div class="toggle-label">Je comprends les risques</div>
          <div class="toggle-sub">Cette clé ne doit être vue que par moi</div>
        </div>
        <div class="toggle"><input type="checkbox" id="c1"><span class="slider"></span></div>
      </label>
      <label class="toggle-row">
        <div>
          <div class="toggle-label">Je ne suis pas en public</div>
          <div class="toggle-sub">Aucun enregistrement d'écran en cours</div>
        </div>
        <div class="toggle"><input type="checkbox" id="c2"><span class="slider"></span></div>
      </label>
    </div>
    <button class="btn btn-danger" id="exp-btn">Afficher la clé</button>
  `);
  setBack("wallet");
  document.getElementById("exp-btn").onclick = async () => {
    if (!document.getElementById("c1").checked || !document.getElementById("c2").checked) {
      return toast("Cochez les deux cases", "error");
    }
    try {
      const r = await api("/wallet/export-pk", {method:"POST", body:{confirm: true}});
      render(`
        <div class="page-title">🔐 Clé privée</div>
        <div class="alert"><h4>⚠ Copiez maintenant</h4><p>Retournez à l'écran wallet dès que vous l'avez sauvegardée.</p></div>
        <div class="card">
          <div class="addr-box mono" style="color:var(--red);background:rgba(255,69,58,0.08)">${r.private_key}</div>
          <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier la clé</button>
        </div>
        <button class="btn btn-secondary" onclick="go('wallet')">Terminé</button>
      `);
      setBack("wallet");
    } catch (e) { toast(e.message, "error"); }
  };
}, {tab: "wallet", back: "wallet"});

/* ── MORE / Plus ──────────────────────────────────── */
route(/^more$/, async () => {
  render(`
    <div class="page-title">Plus</div>
    <div class="card card-flush"><div class="list">
      <div class="list-item" onclick="go('more/settings')">
        <div class="list-icon">⚙️</div>
        <div class="list-body"><div class="list-title">Réglages</div><div class="list-sub">Sizing, risque, notifications…</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/reports')">
        <div class="list-icon">📈</div>
        <div class="list-body"><div class="list-title">Rapports</div><div class="list-sub">PnL par période et source</div></div>
        <div class="list-chevron">›</div>
      </div>
      <div class="list-item" onclick="go('more/strategy-wallet')">
        <div class="list-icon">🎯</div>
        <div class="list-body"><div class="list-title">Wallet stratégie</div><div class="list-sub">Wallet dédié aux stratégies</div></div>
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

    <div class="section" style="text-align:center;padding-top:20px">
      <div class="small">WENPOLYMARKET · v2</div>
    </div>
  `);
});

/* ── Settings ─────────────────────────────────────── */
route(/^more\/settings$/, async () => {
  const s = await api("/settings");
  const tgl = (key, label, sub, val) => `
    <label class="toggle-row">
      <div>
        <div class="toggle-label">${label}</div>
        ${sub ? `<div class="toggle-sub">${sub}</div>` : ""}
      </div>
      <div class="toggle"><input type="checkbox" data-key="${key}" ${val?"checked":""}><span class="slider"></span></div>
    </label>`;
  const num = (key, label, val, step=1, min=0, max=1000, hint) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <input class="input" type="number" data-key="${key}" value="${val ?? ""}" step="${step}" min="${min}" max="${max}">
      ${hint ? `<div class="input-hint">${hint}</div>` : ""}
    </div>`;
  const sel = (key, label, val, options) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <select class="input" data-key="${key}">
        ${options.map(o => `<option value="${o}" ${o===val?"selected":""}>${o}</option>`).join("")}
      </select>
    </div>`;

  render(`
    <div class="page-title">Réglages</div>

    <div class="card">
      <div class="card-title">Mode</div>
      ${tgl("paper_trading", "Paper trading", "Trades fictifs, pas d'USDC réel", s.paper_trading)}
      ${tgl("is_paused", "Pause copy trading", "Stoppe la copie automatique", s.is_paused)}
      ${tgl("strategy_is_paused", "Pause stratégies", "Stoppe l'exécution des signaux", s.strategy_is_paused)}
    </div>

    <div class="card">
      <div class="card-title">Taille des trades</div>
      ${sel("sizing_mode", "Mode", s.sizing_mode || "FIXED", ["FIXED","PROPORTIONAL","SMART"])}
      ${num("fixed_amount", "Montant fixe USDC", s.fixed_amount, 0.5, 0.1, 1000, "Si mode FIXED")}
      ${num("proportional_pct", "% du master", s.proportional_pct, 0.5, 0.1, 100, "Si mode PROPORTIONAL")}
      ${num("min_trade_usdc", "Min USDC", s.min_trade_usdc, 0.5, 0, 1000)}
      ${num("max_trade_usdc", "Max USDC", s.max_trade_usdc, 0.5, 0, 10000)}
      ${num("daily_limit_usdc", "Limite quotidienne USDC", s.daily_limit_usdc, 1, 0, 100000, "Cap journalier total")}
    </div>

    <div class="card">
      <div class="card-title">Stop Loss / Take Profit</div>
      ${tgl("stop_loss_enabled", "Stop Loss actif", null, s.stop_loss_enabled)}
      ${num("stop_loss_pct", "Stop Loss %", s.stop_loss_pct, 1, 1, 100)}
      ${tgl("take_profit_enabled", "Take Profit actif", null, s.take_profit_enabled)}
      ${num("take_profit_pct", "Take Profit %", s.take_profit_pct, 1, 1, 500)}
      ${tgl("trailing_stop_enabled", "Trailing stop", "SL qui suit le prix", s.trailing_stop_enabled)}
      ${num("trailing_stop_pct", "Trailing %", s.trailing_stop_pct, 1, 1, 100)}
    </div>

    <div class="card">
      <div class="card-title">Smart filter</div>
      ${tgl("smart_filter_enabled", "Filtre intelligent", "Scoring auto des signaux", s.smart_filter_enabled)}
      ${num("min_signal_score", "Score min", s.min_signal_score, 0.05, 0, 1, "Entre 0 et 1")}
      ${num("min_volume_24h", "Volume 24h min USDC", s.min_volume_24h, 100, 0, 1000000)}
      ${num("min_liquidity", "Liquidité min USDC", s.min_liquidity, 100, 0, 1000000)}
      ${num("max_spread_pct", "Spread max %", s.max_spread_pct, 0.5, 0, 50)}
    </div>

    <div class="card">
      <div class="card-title">Notifications</div>
      ${tgl("notify_on_buy", "Sur achats", null, s.notify_on_buy)}
      ${tgl("notify_on_sell", "Sur ventes", null, s.notify_on_sell)}
      ${tgl("notify_on_sl_tp", "SL / TP déclenchés", null, s.notify_on_sl_tp)}
    </div>

    <div class="card">
      <div class="card-title">Stratégies</div>
      ${num("strategy_trade_fee_rate", "Fee rate", s.strategy_trade_fee_rate, 0.01, 0.01, 0.20, "Entre 0.01 (1%) et 0.20 (20%)")}
      ${num("strategy_max_trades_per_day", "Trades max/jour", s.strategy_max_trades_per_day, 1, 1, 200)}
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
      try {
        await api("/settings", {method:"POST", body:{[key]: val}});
        toast("✓ Sauvegardé");
      } catch (e) { toast(e.message, "error"); }
    };
    if (el.type === "checkbox" || el.tagName === "SELECT") {
      el.addEventListener("change", send);
    } else {
      el.addEventListener("input", () => {
        clearTimeout(debounce[key]);
        debounce[key] = setTimeout(send, 600);
      });
    }
  });
}, {tab: "more", back: "more"});

/* ── Reports ──────────────────────────────────────── */
route(/^more\/reports$/, async () => {
  const [day, week, month, byTrader, byMarket] = await Promise.all([
    api("/reports/pnl?period=day"),
    api("/reports/pnl?period=week"),
    api("/reports/pnl?period=month"),
    api("/reports/by-trader"),
    api("/reports/by-market"),
  ]);

  const pnlCard = (title, r) => `
    <div class="card">
      <div class="card-header">
        <div class="h3">${title}</div>
        <span class="${pnlClass(r.pnl)}" style="font-weight:700;font-size:18px">${pnlSign(r.pnl)}</span>
      </div>
      <div class="stats-inline">
        <div class="stat-mini"><div class="stat-value">${r.trades}</div><div class="stat-label">Trades</div></div>
        <div class="stat-mini"><div class="stat-value">${fmtPct(r.win_rate)}</div><div class="stat-label">Win rate</div></div>
        <div class="stat-mini"><div class="stat-value ${pnlClass(r.best_trade)}">${fmtUsd(r.best_trade)}</div><div class="stat-label">Best</div></div>
      </div>
    </div>`;

  render(`
    <div class="page-title">Rapports</div>
    ${pnlCard("Aujourd'hui", day)}
    ${pnlCard("7 derniers jours", week)}
    ${pnlCard("30 derniers jours", month)}

    <div class="section">
      ${sectionTitle("Par trader", byTrader.traders.length ? null : null)}
      ${byTrader.traders.length === 0
        ? `<div class="card small" style="text-align:center;padding:24px">Aucune donnée</div>`
        : `<div class="card card-flush"><div class="list">${byTrader.traders.slice(0,10).map(t => `
            <div class="list-item">
              <div class="avatar" style="width:36px;height:36px;font-size:14px">${t.wallet_short.slice(2,4).toUpperCase()}</div>
              <div class="list-body">
                <div class="list-title mono">${t.wallet_short}</div>
                <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
              </div>
              <div class="list-right ${pnlClass(t.pnl)}" style="font-weight:600">${pnlSign(t.pnl)}</div>
            </div>`).join("")}</div></div>`}
    </div>

    <div class="section">
      ${sectionTitle("Par marché")}
      ${byMarket.markets.length === 0
        ? `<div class="card small" style="text-align:center;padding:24px">Aucune donnée</div>`
        : `<div class="card card-flush"><div class="list">${byMarket.markets.slice(0,10).map(m => `
            <div class="list-item">
              <div class="list-icon">📊</div>
              <div class="list-body">
                <div class="list-title">${esc(m.market_question)}</div>
                <div class="list-sub">${m.trade_count} trades · ${fmtUsd(m.volume)}</div>
              </div>
              <div class="list-right ${pnlClass(m.pnl)}" style="font-weight:600">${pnlSign(m.pnl)}</div>
            </div>`).join("")}</div></div>`}
    </div>
  `);
  setBack("more");
}, {tab: "more", back: "more"});

/* ── Strategy wallet ──────────────────────────────── */
route(/^more\/strategy-wallet$/, async () => {
  const me = APP.user;
  if (!me.strategy_wallet_address) {
    render(`
      <div class="page-title">Wallet stratégie</div>
      ${emptyState("🎯", "Aucun wallet configuré", "Les stratégies utilisent un wallet dédié, séparé de votre wallet de copy trading.")}
      <button class="btn btn-primary" id="sw-create">✨ Créer un wallet dédié</button>
      <button class="btn btn-secondary" style="margin-top:10px" id="sw-import">📥 Importer une clé</button>
    `);
    setBack("more");
    document.getElementById("sw-create").onclick = async () => {
      const ok = await confirmModal("Créer un wallet stratégie ?", "Un nouveau wallet Polygon sera généré. La clé sera affichée UNE SEULE FOIS.", "Créer");
      if (!ok) return;
      try {
        const r = await api("/strategy-wallet/create", {method:"POST"});
        invalidateAll();
        await loadUser();
        render(`
          <div class="page-title">✅ Wallet stratégie créé</div>
          <div class="alert"><h4>⚠ Sauvegardez MAINTENANT</h4><p>La clé ne sera plus affichée.</p></div>
          <div class="card">
            <div class="tiny" style="margin-bottom:6px">Adresse</div>
            <div class="addr-box mono" onclick="copy('${r.address}')">${r.address}</div>
            <div class="tiny" style="margin:14px 0 6px">Clé privée</div>
            <div class="addr-box mono" style="color:var(--red)" onclick="copy('${r.private_key}')">${r.private_key}</div>
            <button class="btn btn-primary" style="margin-top:12px" onclick="copy('${r.private_key}')">📋 Copier</button>
          </div>
          <button class="btn btn-secondary" style="margin-top:10px" onclick="go('more/strategy-wallet')">J'ai sauvegardé</button>
        `);
        setBack("more");
      } catch (e) { toast(e.message, "error"); }
    };
    document.getElementById("sw-import").onclick = async () => {
      const { el, close } = await sheet(`
        <h3>Importer une clé</h3>
        <div class="sheet-sub">Collez la clé privée du wallet à utiliser pour les stratégies.</div>
        <div class="form-row">
          <label class="label">Clé privée</label>
          <textarea class="input input-mono" id="sw-pk" rows="3" placeholder="0x..."></textarea>
        </div>
        <button class="btn btn-primary" id="sw-ok">Importer</button>
      `);
      el.querySelector("#sw-ok").onclick = async () => {
        const pk = el.querySelector("#sw-pk").value.trim();
        if (!pk) return toast("Clé requise", "error");
        try {
          await api("/strategy-wallet/import", {method:"POST", body:{private_key: pk}});
          invalidateAll();
          await loadUser();
          close();
          el.parentElement?.remove();
          toast("Importé");
          go("more/strategy-wallet");
        } catch (e) { toast(e.message, "error"); }
      };
    };
    return;
  }

  const bal = await api("/strategy-wallet/balance").catch(() => ({usdc:0, matic:0, address:me.strategy_wallet_address}));
  render(`
    <div class="page-title">Wallet stratégie</div>
    <div class="hero">
      <div class="hero-value">${fmtUsd(bal.usdc)}</div>
      <div class="hero-label">USDC · wallet stratégie</div>
      <div class="small" style="margin-top:8px">${bal.matic.toFixed(4)} MATIC</div>
    </div>
    <div class="card">
      <div class="tiny" style="margin-bottom:8px">Adresse</div>
      <div class="addr-box mono" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>
    <button class="btn btn-danger" id="sw-del">🗑 Supprimer ce wallet</button>
  `);
  setBack("more");
  document.getElementById("sw-del").onclick = async () => {
    const ok = await confirmModal("Supprimer le wallet stratégie ?", "La clé sera effacée. Exportez-la avant si besoin.", "Supprimer", "danger");
    if (!ok) return;
    await api("/strategy-wallet", {method:"DELETE"});
    invalidateAll();
    await loadUser();
    toast("Supprimé");
    go("more");
  };
}, {tab: "more", back: "more"});

/* ═══════════════════════════════════════════════════
   BOOTSTRAP
═══════════════════════════════════════════════════ */
async function loadUser() {
  APP.user = await api("/me");
  return APP.user;
}

async function init() {
  if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation?.();
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
        <div class="empty-text">Cette page doit être ouverte via le bouton Mini App dans le bot Telegram.</div>
      </div>`;
    return;
  }

  document.getElementById("app").innerHTML = `
    <div class="header">
      WENPOLYMARKET
      <div class="header-sub">Polymarket Copy &amp; Strategies</div>
    </div>
    <div id="content" class="page"></div>
    <div class="tab-bar">
      <a href="#home" data-tab="home"><span class="tab-icon">🏠</span><span>Accueil</span></a>
      <a href="#copy" data-tab="copy"><span class="tab-icon">👥</span><span>Copy</span></a>
      <a href="#strategies" data-tab="strategies"><span class="tab-icon">🎯</span><span>Stratégies</span></a>
      <a href="#wallet" data-tab="wallet"><span class="tab-icon">💰</span><span>Wallet</span></a>
      <a href="#more" data-tab="more"><span class="tab-icon">⋯</span><span>Plus</span></a>
    </div>`;

  try { await loadUser(); }
  catch (e) { showError("Impossible de charger le profil: " + e.message); return; }

  window.addEventListener("hashchange", dispatch);
  // Always dispatch — dispatch itself handles Telegram framework hashes + unknown routes
  dispatch();
}

window.go = go;
window.copy = copy;
window.dispatch = dispatch;
window.loadUser = loadUser;

init();
