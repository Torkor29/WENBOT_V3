/* ── WENPOLYMARKET Mini App — Single Page Application ── */

const APP = {
  user: null,
  initData: "",
  baseUrl: "",
};

// ── Init ──────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    APP.initData = tg.initData || "";
  }

  // Resolve base URL (same origin)
  APP.baseUrl = window.location.origin;

  // Router
  window.addEventListener("hashchange", route);
  route();
});

// ── API helper ───────────────────────────────────────────────

async function api(path) {
  const res = await fetch(`${APP.baseUrl}/miniapp/api${path}`, {
    headers: { Authorization: `tma ${APP.initData}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${APP.baseUrl}/miniapp/api${path}`, {
    method: "POST",
    headers: {
      Authorization: `tma ${APP.initData}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Router ───────────────────────────────────────────────────

function route() {
  const hash = (window.location.hash || "#home").slice(1);
  const page = hash.split("/")[0];

  // Update tab bar
  document.querySelectorAll(".tab-bar a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === page);
  });

  // Render page
  const app = document.getElementById("app");
  switch (page) {
    case "home":
      renderHome(app);
      break;
    case "copy":
      renderCopy(app);
      break;
    case "strategies":
      renderStrategies(app);
      break;
    case "settings":
      renderSettings(app);
      break;
    default:
      renderHome(app);
  }
}

// ── Helpers ──────────────────────────────────────────────────

function showLoading(container) {
  container.innerHTML = `
    <div class="loading">
      <div class="spinner"></div>
      <p>Chargement...</p>
    </div>`;
}

function showError(container, msg) {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">&#9888;</div>
      <p>${escHtml(msg)}</p>
      <br>
      <button class="btn btn-secondary btn-sm" onclick="route()">Rafraichir</button>
    </div>`;
}

function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function pnlClass(v) {
  return v > 0 ? "pnl-positive" : v < 0 ? "pnl-negative" : "";
}

function pnlSign(v) {
  return v > 0 ? `+${v.toFixed(2)}` : v.toFixed(2);
}

function shortAddr(a) {
  if (!a) return "";
  return `${a.slice(0, 6)}...${a.slice(-4)}`;
}

function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "< 1min";
  if (diff < 3600) return `${Math.floor(diff / 60)}min`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}j`;
}

// ── HOME ─────────────────────────────────────────────────────

async function renderHome(app) {
  showLoading(app);
  try {
    const [me, copyStats, stratStats] = await Promise.all([
      api("/me"),
      api("/copy/stats"),
      api("/strategies/stats"),
    ]);
    APP.user = me;

    const walletDisplay = me.wallet_address
      ? `<div class="wallet-addr">${escHtml(me.wallet_address)}</div>`
      : `<p style="color:var(--tg-hint)">Pas de wallet configur&eacute;</p>`;

    const mode = me.paper_trading
      ? '<span class="badge badge-orange">Paper Trading</span>'
      : '<span class="badge badge-green">Live</span>';

    const status = me.is_paused
      ? '<span class="badge badge-red">En pause</span>'
      : '<span class="badge badge-green">Actif</span>';

    app.innerHTML = `
      <div class="page active">
        <div class="wallet-header">
          <div class="wallet-icon">&#128640;</div>
          <div class="wallet-name">${escHtml(me.username || "Trader")}</div>
          <div style="margin-top:6px">${mode} ${status}</div>
        </div>

        ${walletDisplay}

        <div class="section-title">Copy Trading</div>
        <div class="stat-grid">
          <div class="stat-box">
            <div class="stat-value">${copyStats.total_trades}</div>
            <div class="stat-label">Trades</div>
          </div>
          <div class="stat-box">
            <div class="stat-value ${pnlClass(copyStats.total_pnl)}">${pnlSign(copyStats.total_pnl)}$</div>
            <div class="stat-label">PnL Total</div>
          </div>
          <div class="stat-box">
            <div class="stat-value">${copyStats.open_positions}</div>
            <div class="stat-label">Positions</div>
          </div>
          <div class="stat-box">
            <div class="stat-value">${copyStats.trades_today}</div>
            <div class="stat-label">Aujourd'hui</div>
          </div>
        </div>

        <div class="section-title">Strategies</div>
        <div class="stat-grid">
          <div class="stat-box">
            <div class="stat-value">${stratStats.active_subscriptions}</div>
            <div class="stat-label">Abonn&eacute;</div>
          </div>
          <div class="stat-box">
            <div class="stat-value ${pnlClass(stratStats.total_pnl)}">${pnlSign(stratStats.total_pnl)}$</div>
            <div class="stat-label">PnL Strat</div>
          </div>
          <div class="stat-box">
            <div class="stat-value">${stratStats.total_trades}</div>
            <div class="stat-label">Trades</div>
          </div>
          <div class="stat-box">
            <div class="stat-value">${stratStats.win_rate}%</div>
            <div class="stat-label">Win Rate</div>
          </div>
        </div>

        <div style="margin-top:16px">
          <button class="btn btn-primary" onclick="location.hash='copy'">
            &#128203; Copy Trading
          </button>
          <div style="height:10px"></div>
          <button class="btn btn-secondary" onclick="location.hash='strategies'">
            &#128200; Strategies
          </button>
        </div>
      </div>`;
  } catch (e) {
    showError(app, e.message);
  }
}

// ── COPY TRADING ─────────────────────────────────────────────

async function renderCopy(app) {
  showLoading(app);
  try {
    const [positions, trades, traders] = await Promise.all([
      api("/copy/positions"),
      api("/copy/trades?limit=15"),
      api("/copy/traders"),
    ]);

    // Positions section
    let posHtml = "";
    if (positions.positions.length === 0) {
      posHtml = `<div class="empty-state"><div class="empty-icon">&#128230;</div><p>Aucune position ouverte</p></div>`;
    } else {
      posHtml = positions.positions
        .map(
          (p) => `
        <div class="list-item">
          <div class="list-left">
            <div class="list-title">${escHtml(p.market_question)}</div>
            <div class="list-sub">${escHtml(p.master_wallet)} &middot; ${timeAgo(p.created_at)}</div>
          </div>
          <div class="list-right">
            <div style="font-weight:600">${p.amount.toFixed(2)}$</div>
            <div class="list-sub">${p.shares.toFixed(2)} shares @ ${p.price.toFixed(2)}</div>
          </div>
        </div>`
        )
        .join("");
    }

    // Traders section
    let tradersHtml = "";
    if (traders.traders.length === 0) {
      tradersHtml = `<p style="color:var(--tg-hint);padding:12px 0">Aucun trader suivi</p>`;
    } else {
      tradersHtml = traders.traders
        .map(
          (t) => `
        <div class="list-item">
          <div class="list-left">
            <div class="list-title" style="font-family:monospace">${escHtml(t.wallet_short)}</div>
            <div class="list-sub">${t.trade_count} trades</div>
          </div>
          <div class="list-right">
            <div style="font-weight:600">${t.volume.toFixed(2)}$</div>
            <div class="list-sub">volume</div>
          </div>
        </div>`
        )
        .join("");
    }

    // Recent trades
    let tradesHtml = "";
    if (trades.trades.length === 0) {
      tradesHtml = `<p style="color:var(--tg-hint);padding:12px 0">Aucun trade</p>`;
    } else {
      tradesHtml = trades.trades
        .map((t) => {
          const sideClass = t.side === "BUY" ? "badge-green" : "badge-red";
          const pnlHtml =
            t.settlement_pnl != null
              ? `<span class="${pnlClass(t.settlement_pnl)}">${pnlSign(t.settlement_pnl)}$</span>`
              : `<span class="badge badge-blue">${t.is_settled ? "Settled" : "Open"}</span>`;
          return `
        <div class="list-item">
          <div class="list-left">
            <div class="list-title">${escHtml(t.market_question)}</div>
            <div class="list-sub">
              <span class="badge ${sideClass}">${t.side}</span>
              &middot; ${t.amount.toFixed(2)}$ &middot; ${timeAgo(t.created_at)}
              ${t.is_paper ? ' &middot; <span class="badge badge-orange">Paper</span>' : ""}
            </div>
          </div>
          <div class="list-right">${pnlHtml}</div>
        </div>`;
        })
        .join("");
    }

    app.innerHTML = `
      <div class="page active">
        <div class="section-title">Positions ouvertes (${positions.count})</div>
        <div class="card">${posHtml}</div>

        <div class="section-title">Traders suivis (${traders.count})</div>
        <div class="card">${tradersHtml}</div>

        <div class="section-title">Historique</div>
        <div class="card">${tradesHtml}</div>
      </div>`;
  } catch (e) {
    showError(app, e.message);
  }
}

// ── STRATEGIES ───────────────────────────────────────────────

async function renderStrategies(app) {
  showLoading(app);
  try {
    const [strategies, subs, trades] = await Promise.all([
      api("/strategies"),
      api("/strategies/subscriptions"),
      api("/strategies/trades?limit=15"),
    ]);

    // Available strategies
    let stratHtml = "";
    if (strategies.strategies.length === 0) {
      stratHtml = `
        <div class="empty-state">
          <div class="empty-icon">&#128200;</div>
          <p>Aucune strat&eacute;gie disponible pour le moment</p>
        </div>`;
    } else {
      stratHtml = strategies.strategies
        .map((s) => {
          const subBadge = s.subscribed
            ? '<span class="badge badge-green">Abonn&eacute;</span>'
            : '<span class="badge badge-blue">Disponible</span>';
          const statusBadge =
            s.status === "active"
              ? '<span class="badge badge-green">Active</span>'
              : '<span class="badge badge-orange">Test</span>';
          return `
        <div class="strategy-card">
          <div class="strat-header">
            <div class="strat-name">${escHtml(s.name)}</div>
            <div>${subBadge}</div>
          </div>
          ${s.description ? `<div class="strat-desc">${escHtml(s.description)}</div>` : ""}
          <div class="strat-stats">
            ${statusBadge}
            <span>&#9989; ${s.win_rate}% WR</span>
            <span>&#128200; ${s.total_trades} trades</span>
            <span class="${pnlClass(s.total_pnl)}">${pnlSign(s.total_pnl)}$</span>
          </div>
        </div>`;
        })
        .join("");
    }

    // Active subscriptions
    let subsHtml = "";
    if (subs.subscriptions.length === 0) {
      subsHtml = `<p style="color:var(--tg-hint);padding:12px 0">Aucun abonnement</p>`;
    } else {
      subsHtml = subs.subscriptions
        .map((s) => {
          const status = s.is_active
            ? '<span class="badge badge-green">Actif</span>'
            : '<span class="badge badge-red">Inactif</span>';
          return `
        <div class="list-item">
          <div class="list-left">
            <div class="list-title">${escHtml(s.strategy_name)}</div>
            <div class="list-sub">${s.trade_size}$ par signal</div>
          </div>
          <div class="list-right">${status}</div>
        </div>`;
        })
        .join("");
    }

    // Recent strategy trades
    let tradesHtml = "";
    if (trades.trades.length === 0) {
      tradesHtml = `<p style="color:var(--tg-hint);padding:12px 0">Aucun trade strat&eacute;gie</p>`;
    } else {
      tradesHtml = trades.trades
        .map((t) => {
          const sideClass = t.side === "BUY" ? "badge-green" : "badge-red";
          let resultHtml = "";
          if (t.result === "WON")
            resultHtml = `<span class="badge badge-green">WON</span> <span class="pnl-positive">+${t.pnl?.toFixed(2) || 0}$</span>`;
          else if (t.result === "LOST")
            resultHtml = `<span class="badge badge-red">LOST</span> <span class="pnl-negative">${t.pnl?.toFixed(2) || 0}$</span>`;
          else resultHtml = `<span class="badge badge-blue">En cours</span>`;
          return `
        <div class="list-item">
          <div class="list-left">
            <div class="list-title">${escHtml(t.market_question)}</div>
            <div class="list-sub">
              <span class="badge ${sideClass}">${t.side}</span>
              &middot; ${t.amount.toFixed(2)}$ &middot; ${timeAgo(t.created_at)}
            </div>
          </div>
          <div class="list-right">${resultHtml}</div>
        </div>`;
        })
        .join("");
    }

    app.innerHTML = `
      <div class="page active">
        <div class="section-title">Strat&eacute;gies disponibles</div>
        ${stratHtml}

        <div class="section-title">Mes abonnements (${subs.subscriptions.length})</div>
        <div class="card">${subsHtml}</div>

        <div class="section-title">Historique strat&eacute;gies</div>
        <div class="card">${tradesHtml}</div>
      </div>`;
  } catch (e) {
    showError(app, e.message);
  }
}

// ── SETTINGS ─────────────────────────────────────────────────

async function renderSettings(app) {
  showLoading(app);
  try {
    const [me, settings] = await Promise.all([api("/me"), api("/settings")]);

    const walletHtml = me.wallet_address
      ? `<div class="wallet-addr">${escHtml(me.wallet_address)}</div>
         <p class="list-sub">${me.wallet_auto_created ? "Wallet cr&eacute;&eacute; par le bot" : "Wallet import&eacute;"}</p>`
      : `<p style="color:var(--tg-hint)">Aucun wallet — utilisez /start dans le bot</p>`;

    const stratWalletHtml = me.strategy_wallet_address
      ? `<div class="wallet-addr">${escHtml(me.strategy_wallet_address)}</div>`
      : `<p style="color:var(--tg-hint)">Non configur&eacute;</p>`;

    app.innerHTML = `
      <div class="page active">
        <div class="section-title">Wallet Copy Trading</div>
        <div class="card">${walletHtml}</div>

        <div class="section-title">Wallet Strat&eacute;gies</div>
        <div class="card">${stratWalletHtml}</div>

        <div class="section-title">Trading</div>
        <div class="card">
          <div class="toggle-row">
            <span class="toggle-label">Paper Trading</span>
            <label class="toggle">
              <input type="checkbox" ${settings.paper_trading ? "checked" : ""} onchange="toggleSetting('paper_trading', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
          <div class="toggle-row">
            <span class="toggle-label">Pause Copy Trading</span>
            <label class="toggle">
              <input type="checkbox" ${settings.is_paused ? "checked" : ""} onchange="toggleSetting('is_paused', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <div class="section-title">Montants</div>
        <div class="card">
          <div class="list-item">
            <span class="toggle-label">Montant fixe / trade</span>
            <span style="font-weight:600">${settings.fixed_amount}$</span>
          </div>
          <div class="list-item">
            <span class="toggle-label">Max par trade</span>
            <span style="font-weight:600">${settings.max_trade_usdc}$</span>
          </div>
          <div class="list-item">
            <span class="toggle-label">Limite journali&egrave;re</span>
            <span style="font-weight:600">${settings.daily_limit_usdc}$</span>
          </div>
        </div>

        <div class="section-title">Risk Management</div>
        <div class="card">
          <div class="toggle-row">
            <span class="toggle-label">Stop Loss (${settings.stop_loss_pct}%)</span>
            <label class="toggle">
              <input type="checkbox" ${settings.stop_loss_enabled ? "checked" : ""} onchange="toggleSetting('stop_loss_enabled', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
          <div class="toggle-row">
            <span class="toggle-label">Take Profit (${settings.take_profit_pct}%)</span>
            <label class="toggle">
              <input type="checkbox" ${settings.take_profit_enabled ? "checked" : ""} onchange="toggleSetting('take_profit_enabled', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
          <div class="toggle-row">
            <span class="toggle-label">Trailing Stop (${settings.trailing_stop_pct}%)</span>
            <label class="toggle">
              <input type="checkbox" ${settings.trailing_stop_enabled ? "checked" : ""} onchange="toggleSetting('trailing_stop_enabled', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
        </div>

        <div class="section-title">Analyse V3</div>
        <div class="card">
          <div class="toggle-row">
            <span class="toggle-label">Smart Filter</span>
            <label class="toggle">
              <input type="checkbox" ${settings.smart_filter_enabled ? "checked" : ""} onchange="toggleSetting('smart_filter_enabled', this.checked)">
              <span class="slider"></span>
            </label>
          </div>
          <div class="list-item">
            <span class="toggle-label">Score minimum</span>
            <span style="font-weight:600">${settings.min_signal_score}/100</span>
          </div>
        </div>

        <div class="section-title">Traders suivis (${settings.followed_wallets.length})</div>
        <div class="card">
          ${
            settings.followed_wallets.length === 0
              ? '<p style="color:var(--tg-hint)">Aucun trader suivi</p>'
              : settings.followed_wallets
                  .map(
                    (w) =>
                      `<div class="list-item"><span style="font-family:monospace;font-size:13px">${escHtml(shortAddr(w))}</span><span class="list-sub">${escHtml(w)}</span></div>`
                  )
                  .join("")
          }
        </div>

        <div style="margin-top:16px;text-align:center;color:var(--tg-hint);font-size:12px">
          Pour modifier les montants, ajouter des traders ou<br>
          g&eacute;rer vos wallets, utilisez le bot Telegram.
        </div>
      </div>`;
  } catch (e) {
    showError(app, e.message);
  }
}

// ── Settings toggle action ───────────────────────────────────

async function toggleSetting(key, value) {
  try {
    await apiPost("/settings", { [key]: value });
  } catch (e) {
    alert("Erreur: " + e.message);
    // Refresh to reset toggle state
    renderSettings(document.getElementById("app"));
  }
}
