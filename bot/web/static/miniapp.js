/* Telegram Mini App — Full SPA */

const tg = window.Telegram?.WebApp;
const APP = { initData: tg?.initData || "", user: null };

// ── API wrapper ─────────────────────────────────────────────────
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

// ── Utils ───────────────────────────────────────────────────────
const fmtUsd = x => "$" + Number(x || 0).toFixed(2);
const fmtPct = x => Number(x || 0).toFixed(1) + "%";
const shortAddr = a => a ? a.slice(0,6) + "..." + a.slice(-4) : "";
const pnlClass = x => x > 0 ? "pnl-positive" : x < 0 ? "pnl-negative" : "";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const haptic = (t="light") => tg?.HapticFeedback?.impactOccurred?.(t);

function toast(msg, type="success") {
  const t = document.createElement("div");
  t.className = "toast";
  t.style.background = type === "error" ? "#ff3b30" : "#34c759";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2000);
  haptic(type === "error" ? "heavy" : "light");
}

function confirmModal(title, text, confirmText="Confirmer") {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "modal-backdrop";
    bd.innerHTML = `
      <div class="modal">
        <h3 style="margin-bottom:10px">${esc(title)}</h3>
        <p style="color:var(--tg-hint);margin-bottom:16px;line-height:1.4">${esc(text)}</p>
        <button class="btn btn-primary" id="cm-ok">${esc(confirmText)}</button>
        <button class="btn btn-secondary" id="cm-cancel" style="margin-top:8px">Annuler</button>
      </div>`;
    document.body.appendChild(bd);
    bd.querySelector("#cm-ok").onclick = () => { bd.remove(); resolve(true); };
    bd.querySelector("#cm-cancel").onclick = () => { bd.remove(); resolve(false); };
  });
}

function prompt2(title, fields) {
  return new Promise(resolve => {
    const bd = document.createElement("div");
    bd.className = "modal-backdrop";
    const inputs = fields.map(f => `
      <div class="form-row">
        <label class="label">${esc(f.label)}</label>
        <input class="input" name="${f.name}" type="${f.type||"text"}"
               placeholder="${esc(f.placeholder||"")}" value="${esc(f.value||"")}" />
      </div>`).join("");
    bd.innerHTML = `
      <div class="modal">
        <h3 style="margin-bottom:14px">${esc(title)}</h3>
        ${inputs}
        <button class="btn btn-primary" id="pm-ok">Valider</button>
        <button class="btn btn-secondary" id="pm-cancel" style="margin-top:8px">Annuler</button>
      </div>`;
    document.body.appendChild(bd);
    bd.querySelector("#pm-ok").onclick = () => {
      const data = {};
      fields.forEach(f => { data[f.name] = bd.querySelector(`[name="${f.name}"]`).value; });
      bd.remove();
      resolve(data);
    };
    bd.querySelector("#pm-cancel").onclick = () => { bd.remove(); resolve(null); };
  });
}

function copy(text) {
  navigator.clipboard?.writeText(text);
  toast("Copié");
}

// ── Router ──────────────────────────────────────────────────────
const routes = [];
function route(pattern, handler) { routes.push({pattern, handler}); }

async function dispatch() {
  const hash = location.hash.slice(1) || "home";
  for (const r of routes) {
    const m = hash.match(r.pattern);
    if (m) {
      setTab(hash.split("/")[0]);
      try {
        document.getElementById("content").innerHTML = `<div class="loading"><div class="spinner"></div>Chargement...</div>`;
        await r.handler(m);
      } catch (e) {
        showError(e.message);
      }
      return;
    }
  }
  document.getElementById("content").innerHTML = `<div class="empty-state"><div class="empty-icon">🔍</div><p>Route introuvable</p></div>`;
}

function setTab(name) {
  document.querySelectorAll(".tab-bar a").forEach(a => {
    a.classList.toggle("active", a.dataset.tab === name);
  });
}

function showError(msg) {
  document.getElementById("content").innerHTML = `
    <div style="padding:40px 20px;text-align:center;">
      <div style="font-size:48px;margin-bottom:12px;">⚠️</div>
      <h3 style="color:#ff3b30;margin-bottom:12px;">Erreur</h3>
      <p style="color:var(--tg-hint);margin-bottom:20px;">${esc(msg)}</p>
      <button class="btn btn-secondary" onclick="dispatch()">Réessayer</button>
    </div>`;
}

function go(hash) { location.hash = hash; }

// ── Screens ─────────────────────────────────────────────────────

// HOME
route(/^home$/, async () => {
  const me = APP.user;
  const [copyStats, stratStats] = await Promise.all([
    api("/copy/stats"),
    api("/strategies/stats"),
  ]);
  let balHtml = "";
  if (me.wallet_address) {
    try {
      const bal = await api("/wallet/balance");
      balHtml = `
        <div class="card">
          <div class="card-title">Wallet Copy</div>
          <div class="stat-grid">
            <div class="stat-box"><div class="stat-value">${fmtUsd(bal.usdc)}</div><div class="stat-label">USDC</div></div>
            <div class="stat-box"><div class="stat-value">${bal.matic.toFixed(4)}</div><div class="stat-label">MATIC</div></div>
          </div>
          <div class="wallet-addr" style="margin-top:12px">${shortAddr(bal.address)}</div>
        </div>`;
    } catch (e) { balHtml = `<div class="card"><p style="color:var(--tg-hint)">Balance indisponible</p></div>`; }
  } else {
    balHtml = `<div class="card"><p style="color:var(--tg-hint);margin-bottom:12px">Aucun wallet configuré</p>
      <button class="btn btn-primary" onclick="go('wallet')">Configurer mon wallet</button></div>`;
  }

  document.getElementById("content").innerHTML = `
    ${balHtml}
    <div class="section-title">Copy Trading</div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value ${pnlClass(copyStats.total_pnl)}">${fmtUsd(copyStats.total_pnl)}</div><div class="stat-label">PnL Total</div></div>
      <div class="stat-box"><div class="stat-value">${copyStats.open_positions}</div><div class="stat-label">Positions</div></div>
      <div class="stat-box"><div class="stat-value">${copyStats.total_trades}</div><div class="stat-label">Trades</div></div>
      <div class="stat-box"><div class="stat-value">${fmtUsd(copyStats.total_volume)}</div><div class="stat-label">Volume</div></div>
    </div>
    <div class="section-title">Stratégies</div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value ${pnlClass(stratStats.total_pnl)}">${fmtUsd(stratStats.total_pnl)}</div><div class="stat-label">PnL</div></div>
      <div class="stat-box"><div class="stat-value">${fmtPct(stratStats.win_rate)}</div><div class="stat-label">Win rate</div></div>
      <div class="stat-box"><div class="stat-value">${stratStats.active_subscriptions}</div><div class="stat-label">Abonné à</div></div>
      <div class="stat-box"><div class="stat-value">${stratStats.total_trades}</div><div class="stat-label">Trades</div></div>
    </div>
    <div style="margin-top:16px;display:grid;grid-template-columns:1fr 1fr;gap:12px">
      <button class="btn btn-secondary" onclick="go('copy')">👛 Copy</button>
      <button class="btn btn-secondary" onclick="go('strategies')">📊 Stratégies</button>
    </div>`;
});

// WALLET
route(/^wallet$/, async () => {
  const me = APP.user;
  if (!me.wallet_address) {
    document.getElementById("content").innerHTML = `
      <div class="card wallet-header">
        <div class="wallet-icon">👛</div>
        <div class="wallet-name">Aucun wallet</div>
        <p style="color:var(--tg-hint);margin-top:8px">Créez ou importez un wallet Polygon pour commencer</p>
      </div>
      <button class="btn btn-primary" onclick="go('wallet/create')">✨ Créer un wallet</button>
      <div style="height:10px"></div>
      <button class="btn btn-secondary" onclick="go('wallet/import')">📥 Importer une clé privée</button>`;
    return;
  }
  const bal = await api("/wallet/balance").catch(() => ({usdc:0, matic:0, address:me.wallet_address}));
  document.getElementById("content").innerHTML = `
    <div class="card wallet-header">
      <div class="wallet-icon">👛</div>
      <div class="wallet-name">Mon Wallet</div>
    </div>
    <div class="card">
      <div class="card-title">Adresse</div>
      <div class="wallet-addr" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value">${fmtUsd(bal.usdc)}</div><div class="stat-label">USDC</div></div>
      <div class="stat-box"><div class="stat-value">${bal.matic.toFixed(4)}</div><div class="stat-label">MATIC</div></div>
    </div>
    <div style="margin-top:16px;display:grid;gap:10px">
      <button class="btn btn-primary" onclick="go('wallet/deposit')">📥 Déposer</button>
      <button class="btn btn-secondary" onclick="go('wallet/withdraw')">📤 Retirer</button>
      <button class="btn btn-secondary" onclick="go('wallet/export')">🔐 Exporter clé privée</button>
      <button class="btn btn-danger" onclick="walletDelete()">🗑 Supprimer ce wallet</button>
    </div>`;
});

async function walletDelete() {
  const ok = await confirmModal("Supprimer le wallet", "La clé privée sera effacée de la base. Assurez-vous de l'avoir exportée si vous voulez la conserver.", "Supprimer");
  if (!ok) return;
  await api("/wallet", {method:"DELETE"});
  toast("Wallet supprimé");
  await loadUser();
  go("wallet");
}

route(/^wallet\/create$/, async () => {
  const ok = await confirmModal("Créer un nouveau wallet", "Un wallet Polygon sera généré. Sa clé privée sera affichée UNE SEULE FOIS — sauvegardez-la.", "Créer");
  if (!ok) { go("wallet"); return; }
  const res = await api("/wallet/create", {method:"POST"});
  await loadUser();
  document.getElementById("content").innerHTML = `
    <div class="danger-card">
      <h3>⚠ Sauvegardez MAINTENANT</h3>
      <p style="color:var(--tg-text)">Cette clé ne sera plus jamais affichée. Copiez-la dans un endroit sûr AVANT de continuer.</p>
    </div>
    <div class="card">
      <div class="card-title">Adresse</div>
      <div class="wallet-addr" onclick="copy('${res.address}')">${res.address}</div>
      <div class="card-title" style="margin-top:16px">Clé privée</div>
      <div class="wallet-addr" onclick="copy('${res.private_key}')">${res.private_key}</div>
    </div>
    <button class="btn btn-secondary" onclick="copy('${res.private_key}')">📋 Copier la clé</button>
    <div style="height:8px"></div>
    <button class="btn btn-primary" onclick="go('wallet')">J'ai sauvegardé, continuer</button>`;
});

route(/^wallet\/import$/, async () => {
  document.getElementById("content").innerHTML = `
    <div class="card">
      <div class="card-title">Importer une clé privée</div>
      <div class="form-row">
        <label class="label">Clé privée (64 hex, avec ou sans 0x)</label>
        <textarea class="input input-mono" id="pk-input" rows="3" placeholder="0x..."></textarea>
      </div>
      <button class="btn btn-primary" id="pk-btn">Importer</button>
    </div>`;
  document.getElementById("pk-btn").onclick = async () => {
    const pk = document.getElementById("pk-input").value.trim();
    if (!pk) return toast("Clé requise", "error");
    try {
      const r = await api("/wallet/import", {method:"POST", body:{private_key: pk}});
      toast("Wallet importé: " + shortAddr(r.address));
      await loadUser();
      go("wallet");
    } catch (e) { toast(e.message, "error"); }
  };
});

route(/^wallet\/deposit$/, async () => {
  const me = APP.user;
  document.getElementById("content").innerHTML = `
    <div class="card wallet-header">
      <div class="wallet-icon">📥</div>
      <div class="wallet-name">Déposer des USDC</div>
      <p style="color:var(--tg-hint);margin-top:8px">Envoyez des USDC (Polygon) à cette adresse</p>
    </div>
    <div class="card">
      <div class="card-title">Votre adresse Polygon</div>
      <div class="wallet-addr" onclick="copy('${me.wallet_address}')">${me.wallet_address}</div>
      <button class="btn btn-secondary" onclick="copy('${me.wallet_address}')" style="margin-top:10px">📋 Copier</button>
    </div>
    <div class="card">
      <div class="card-title">⚠ Instructions</div>
      <p style="color:var(--tg-text);font-size:14px;line-height:1.5">
        • Réseau : <b>Polygon</b> (pas Ethereum, pas BSC)<br>
        • Token : <b>USDC.e</b> (pont Polygon)<br>
        • Ajoutez aussi un peu de <b>MATIC</b> (0.1 suffit) pour payer le gaz<br>
        • Dépôt crédité après 1 confirmation (~3 sec)
      </p>
    </div>
    <button class="btn btn-secondary" onclick="go('wallet')">← Retour</button>`;
});

route(/^wallet\/withdraw$/, async () => {
  const bal = await api("/wallet/balance");
  document.getElementById("content").innerHTML = `
    <div class="card">
      <div class="card-title">Retirer des USDC</div>
      <div style="font-size:14px;color:var(--tg-hint);margin-bottom:14px">Disponible: <b>${fmtUsd(bal.usdc)}</b></div>
      <div class="form-row">
        <label class="label">Adresse destination (Polygon)</label>
        <input class="input input-mono" id="to-addr" placeholder="0x..." />
      </div>
      <div class="form-row">
        <label class="label">Montant USDC</label>
        <input class="input" id="amount" type="number" step="0.01" placeholder="0.00" />
        <button class="btn btn-secondary btn-sm" style="margin-top:6px" onclick="document.getElementById('amount').value=${bal.usdc}">MAX (${fmtUsd(bal.usdc)})</button>
      </div>
      <button class="btn btn-primary" id="wd-btn">Retirer</button>
    </div>`;
  document.getElementById("wd-btn").onclick = async () => {
    const to = document.getElementById("to-addr").value.trim();
    const amt = parseFloat(document.getElementById("amount").value);
    if (!to.startsWith("0x") || to.length !== 42) return toast("Adresse invalide", "error");
    if (!amt || amt <= 0) return toast("Montant invalide", "error");
    const ok = await confirmModal("Confirmer le retrait", `Envoyer ${fmtUsd(amt)} à ${shortAddr(to)} ?`, "Envoyer");
    if (!ok) return;
    try {
      const r = await api("/wallet/withdraw", {method:"POST", body:{to_address: to, amount: amt}});
      toast("Envoyé ✓");
      document.getElementById("content").innerHTML = `
        <div class="card wallet-header">
          <div class="wallet-icon">✅</div>
          <div class="wallet-name">Retrait envoyé</div>
        </div>
        <div class="card">
          <div class="card-title">Transaction</div>
          <div class="wallet-addr">${r.tx_hash}</div>
          <a href="https://polygonscan.com/tx/${r.tx_hash}" target="_blank" class="btn btn-secondary" style="margin-top:10px">Voir sur Polygonscan ↗</a>
        </div>
        <button class="btn btn-primary" onclick="go('wallet')">Retour au wallet</button>`;
    } catch (e) { toast(e.message, "error"); }
  };
});

route(/^wallet\/export$/, async () => {
  document.getElementById("content").innerHTML = `
    <div class="danger-card">
      <h3>🔐 Exporter la clé privée</h3>
      <p style="color:var(--tg-text);line-height:1.5">
        Votre clé privée donne un contrôle <b>total</b> de votre wallet.<br>
        Ne la partagez <b>JAMAIS</b>. Quiconque possède cette clé peut vider le wallet.
      </p>
    </div>
    <div class="card">
      <label class="toggle-row" style="cursor:pointer">
        <span class="toggle-label">Je comprends les risques</span>
        <div class="toggle"><input type="checkbox" id="c1"><span class="slider"></span></div>
      </label>
      <label class="toggle-row" style="cursor:pointer">
        <span class="toggle-label">Je ne suis pas en public / screen share</span>
        <div class="toggle"><input type="checkbox" id="c2"><span class="slider"></span></div>
      </label>
      <button class="btn btn-danger" id="exp-btn" style="margin-top:12px">Afficher la clé</button>
    </div>`;
  document.getElementById("exp-btn").onclick = async () => {
    if (!document.getElementById("c1").checked || !document.getElementById("c2").checked) {
      return toast("Cochez les deux cases", "error");
    }
    try {
      const r = await api("/wallet/export-pk", {method:"POST", body:{confirm: true}});
      document.getElementById("content").innerHTML = `
        <div class="danger-card">
          <h3>⚠ Clé privée</h3>
          <p>Copiez-la MAINTENANT puis fermez l'écran.</p>
        </div>
        <div class="card">
          <div class="wallet-addr input-mono">${r.private_key}</div>
          <button class="btn btn-secondary" onclick="copy('${r.private_key}')" style="margin-top:10px">📋 Copier</button>
        </div>
        <button class="btn btn-primary" onclick="go('wallet')">J'ai fini</button>`;
    } catch (e) { toast(e.message, "error"); }
  };
});

// COPY
route(/^copy$/, async () => {
  const [stats, traders, positions] = await Promise.all([
    api("/copy/stats"),
    api("/copy/traders"),
    api("/copy/positions"),
  ]);
  document.getElementById("content").innerHTML = `
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value ${pnlClass(stats.total_pnl)}">${fmtUsd(stats.total_pnl)}</div><div class="stat-label">PnL</div></div>
      <div class="stat-box"><div class="stat-value">${stats.open_positions}</div><div class="stat-label">Positions</div></div>
      <div class="stat-box"><div class="stat-value">${stats.trades_today}</div><div class="stat-label">Aujourd'hui</div></div>
      <div class="stat-box"><div class="stat-value">${fmtUsd(stats.total_volume)}</div><div class="stat-label">Volume</div></div>
    </div>
    <div class="section-title">Traders suivis (${traders.count})</div>
    <div class="card">
      ${traders.count === 0 ? `<div class="empty-state"><div class="empty-icon">👥</div><p>Aucun trader suivi</p></div>` :
        traders.traders.slice(0,5).map(t => `
          <div class="list-item" onclick="go('copy/trader/${t.wallet}')">
            <div class="list-left">
              <div class="list-title">${t.wallet_short}</div>
              <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
            </div>
            <div class="list-right"><span class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl)}</span></div>
          </div>`).join("")
      }
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:12px">
        <button class="btn btn-secondary btn-sm" onclick="go('copy/traders')">Tout voir</button>
        <button class="btn btn-primary btn-sm" onclick="go('copy/traders/add')">+ Ajouter</button>
      </div>
    </div>
    <div class="section-title">Positions ouvertes (${positions.count})</div>
    <div class="card">
      ${positions.count === 0 ? `<div class="empty-state"><div class="empty-icon">📭</div><p>Aucune position ouverte</p></div>` :
        positions.positions.slice(0,5).map(p => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(p.market_question)}</div>
              <div class="list-sub">${p.shares.toFixed(2)} @ ${p.price.toFixed(4)}</div>
            </div>
            <div class="list-right">${fmtUsd(p.amount)}</div>
          </div>`).join("")
      }
      <button class="btn btn-secondary btn-sm" onclick="go('copy/positions')" style="margin-top:12px">Tout voir</button>
    </div>
    <button class="btn btn-secondary" onclick="go('copy/history')" style="margin-top:12px">📜 Historique complet</button>`;
});

route(/^copy\/traders$/, async () => {
  const {traders, count} = await api("/copy/traders");
  document.getElementById("content").innerHTML = `
    <button class="btn btn-primary" onclick="go('copy/traders/add')">+ Ajouter un trader</button>
    <div class="section-title">Traders suivis (${count})</div>
    <div class="card">
      ${count === 0 ? `<div class="empty-state"><div class="empty-icon">👥</div><p>Aucun trader</p></div>` :
        traders.map(t => `
          <div class="list-item">
            <div class="list-left" onclick="go('copy/trader/${t.wallet}')">
              <div class="list-title">${t.wallet_short}</div>
              <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)} · <span class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl)}</span></div>
            </div>
            <div class="list-right">
              <button class="btn btn-danger btn-sm" onclick="traderRemove('${t.wallet}')">🗑</button>
            </div>
          </div>`).join("")
      }
    </div>`;
});

async function traderRemove(wallet) {
  const ok = await confirmModal("Arrêter de suivre", shortAddr(wallet) + " — confirmer ?", "Retirer");
  if (!ok) return;
  await api("/copy/traders/" + wallet, {method:"DELETE"});
  toast("Retiré");
  dispatch();
}

route(/^copy\/traders\/add$/, async () => {
  document.getElementById("content").innerHTML = `
    <div class="card">
      <div class="card-title">Ajouter un trader</div>
      <div class="form-row">
        <label class="label">Adresse Polygon du trader</label>
        <input class="input input-mono" id="addr-input" placeholder="0x..." />
      </div>
      <button class="btn btn-primary" id="add-btn">Suivre</button>
    </div>`;
  document.getElementById("add-btn").onclick = async () => {
    const w = document.getElementById("addr-input").value.trim();
    try {
      await api("/copy/traders/add", {method:"POST", body:{wallet: w}});
      toast("Ajouté ✓");
      go("copy/traders");
    } catch (e) { toast(e.message, "error"); }
  };
});

route(/^copy\/trader\/(0x[a-fA-F0-9]+)$/, async (m) => {
  const wallet = m[1];
  const d = await api("/copy/traders/" + wallet + "/stats");
  document.getElementById("content").innerHTML = `
    <div class="card wallet-header">
      <div class="wallet-icon">👤</div>
      <div class="wallet-name">${shortAddr(wallet)}</div>
    </div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value">${d.trade_count}</div><div class="stat-label">Trades</div></div>
      <div class="stat-box"><div class="stat-value">${fmtUsd(d.volume)}</div><div class="stat-label">Volume</div></div>
      <div class="stat-box"><div class="stat-value ${pnlClass(d.pnl)}">${fmtUsd(d.pnl)}</div><div class="stat-label">PnL</div></div>
      <div class="stat-box"><div class="stat-value">${d.recent_trades.length}</div><div class="stat-label">Récents</div></div>
    </div>
    <div class="section-title">Derniers trades copiés</div>
    <div class="card">
      ${d.recent_trades.length === 0 ? `<div class="empty-state"><p>Aucun trade</p></div>` :
        d.recent_trades.map(t => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub"><span class="badge ${t.side==='BUY'?'badge-green':'badge-red'}">${t.side}</span> @ ${t.price.toFixed(4)}</div>
            </div>
            <div class="list-right">
              ${t.pnl !== null ? `<span class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl)}</span>` : fmtUsd(t.amount)}
            </div>
          </div>`).join("")
      }
    </div>
    <button class="btn btn-danger" onclick="traderRemove('${wallet}')">🗑 Arrêter de suivre</button>`;
});

route(/^copy\/positions$/, async () => {
  const {positions, count} = await api("/copy/positions");
  document.getElementById("content").innerHTML = `
    <div class="section-title">Positions ouvertes (${count})</div>
    <div class="card">
      ${count === 0 ? `<div class="empty-state"><div class="empty-icon">📭</div><p>Aucune position</p></div>` :
        positions.map(p => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(p.market_question)}</div>
              <div class="list-sub">${p.shares.toFixed(2)} shares @ ${p.price.toFixed(4)} · ${p.master_wallet}</div>
            </div>
            <div class="list-right">
              <div>${fmtUsd(p.amount)}</div>
              ${p.is_paper ? '<span class="badge badge-orange">PAPER</span>' : ''}
            </div>
          </div>`).join("")
      }
    </div>`;
});

route(/^copy\/history$/, async () => {
  const {trades} = await api("/copy/trades?limit=50");
  document.getElementById("content").innerHTML = `
    <div class="section-title">Historique (${trades.length})</div>
    <div class="card">
      ${trades.length === 0 ? `<div class="empty-state"><p>Aucun trade</p></div>` :
        trades.map(t => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub"><span class="badge ${t.side==='BUY'?'badge-green':'badge-red'}">${t.side}</span> ${t.shares.toFixed(2)} @ ${t.price.toFixed(4)} · ${t.master_wallet}</div>
            </div>
            <div class="list-right">
              ${t.settlement_pnl !== null ? `<div class="${pnlClass(t.settlement_pnl)}">${fmtUsd(t.settlement_pnl)}</div>` : `<div>${fmtUsd(t.amount)}</div>`}
              ${t.is_paper ? '<span class="badge badge-orange">P</span>' : ''}
            </div>
          </div>`).join("")
      }
    </div>`;
});

// STRATEGIES
route(/^strategies$/, async () => {
  const [{strategies}, stats] = await Promise.all([api("/strategies"), api("/strategies/stats")]);
  const me = APP.user;
  const walletBlock = me.strategy_wallet_address ? "" : `
    <div class="card">
      <div class="card-title">Wallet stratégie</div>
      <p style="color:var(--tg-hint);font-size:14px;margin-bottom:10px">Les stratégies utilisent un wallet dédié, séparé du copy trading.</p>
      <button class="btn btn-primary btn-sm" onclick="go('strategies/wallet')">Configurer</button>
    </div>`;
  document.getElementById("content").innerHTML = `
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value ${pnlClass(stats.total_pnl)}">${fmtUsd(stats.total_pnl)}</div><div class="stat-label">PnL</div></div>
      <div class="stat-box"><div class="stat-value">${fmtPct(stats.win_rate)}</div><div class="stat-label">Win rate</div></div>
      <div class="stat-box"><div class="stat-value">${stats.active_subscriptions}</div><div class="stat-label">Abonné</div></div>
      <div class="stat-box"><div class="stat-value">${stats.total_trades}</div><div class="stat-label">Trades</div></div>
    </div>
    ${walletBlock}
    <div class="section-title">Stratégies disponibles (${strategies.length})</div>
    ${strategies.length === 0 ? `<div class="empty-state"><div class="empty-icon">📊</div><p>Aucune stratégie disponible pour le moment</p></div>` :
      strategies.map(s => `
        <div class="strategy-card" onclick="stratDetail('${s.id}')">
          <div class="strat-header">
            <div class="strat-name">${esc(s.name)}</div>
            ${s.subscribed ? '<span class="badge badge-green">Abonné</span>' : `<span class="badge badge-blue">${s.status}</span>`}
          </div>
          <div class="strat-desc">${esc(s.description || "")}</div>
          <div class="strat-stats">
            <span>📈 ${fmtPct(s.win_rate)}</span>
            <span>💰 <span class="${pnlClass(s.total_pnl)}">${fmtUsd(s.total_pnl)}</span></span>
            <span>🔄 ${s.total_trades}</span>
          </div>
        </div>`).join("")
    }
    <button class="btn btn-secondary" onclick="go('strategies/history')" style="margin-top:12px">📜 Historique stratégies</button>`;
});

async function stratDetail(id) {
  const {strategies} = await api("/strategies");
  const s = strategies.find(x => x.id === id);
  if (!s) return toast("Stratégie introuvable", "error");
  const bd = document.createElement("div");
  bd.className = "modal-backdrop";
  bd.innerHTML = `
    <div class="modal">
      <h3 style="margin-bottom:6px">${esc(s.name)}</h3>
      <p style="color:var(--tg-hint);font-size:13px;margin-bottom:14px">${esc(s.description||"")}</p>
      <div class="form-row">
        <label class="label">Taille par trade USDC (${s.min_trade_size} – ${s.max_trade_size})</label>
        <input class="input" id="ts-input" type="number" step="0.5" min="${s.min_trade_size}" max="${s.max_trade_size}" value="${s.my_trade_size || s.min_trade_size}">
      </div>
      ${s.subscribed ? `
        <button class="btn btn-primary" id="sub-save">💾 Mettre à jour</button>
        <button class="btn btn-danger" id="unsub" style="margin-top:8px">Désinscrire</button>
      ` : `
        <button class="btn btn-primary" id="sub-new">✓ Souscrire</button>
      `}
      <button class="btn btn-secondary" id="sub-cancel" style="margin-top:8px">Fermer</button>
    </div>`;
  document.body.appendChild(bd);
  const close = () => bd.remove();
  bd.querySelector("#sub-cancel").onclick = close;
  const getSize = () => parseFloat(bd.querySelector("#ts-input").value);
  if (s.subscribed) {
    bd.querySelector("#sub-save").onclick = async () => {
      try { await api(`/strategies/${id}/subscription`, {method:"PATCH", body:{trade_size: getSize()}}); toast("Mis à jour"); close(); dispatch(); }
      catch (e) { toast(e.message, "error"); }
    };
    bd.querySelector("#unsub").onclick = async () => {
      const ok = await confirmModal("Désinscrire", `De ${s.name} ?`, "Désinscrire");
      if (!ok) return;
      await api(`/strategies/${id}/unsubscribe`, {method:"POST"});
      toast("Désinscrit"); close(); dispatch();
    };
  } else {
    bd.querySelector("#sub-new").onclick = async () => {
      try { await api(`/strategies/${id}/subscribe`, {method:"POST", body:{trade_size: getSize()}}); toast("Souscrit ✓"); close(); dispatch(); }
      catch (e) { toast(e.message, "error"); }
    };
  }
}

route(/^strategies\/history$/, async () => {
  const {trades} = await api("/strategies/trades?limit=50");
  document.getElementById("content").innerHTML = `
    <div class="section-title">Trades stratégies (${trades.length})</div>
    <div class="card">
      ${trades.length === 0 ? `<div class="empty-state"><p>Aucun trade</p></div>` :
        trades.map(t => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(t.market_question)}</div>
              <div class="list-sub">${esc(t.strategy_id)} · ${t.shares.toFixed(2)} @ ${t.price.toFixed(4)}</div>
            </div>
            <div class="list-right">
              ${t.result ? `<span class="badge ${t.result==='WON'?'badge-green':'badge-red'}">${t.result}</span><br>` : ''}
              ${t.pnl !== null ? `<span class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl)}</span>` : fmtUsd(t.amount)}
            </div>
          </div>`).join("")
      }
    </div>`;
});

route(/^strategies\/wallet$/, async () => {
  const me = APP.user;
  if (!me.strategy_wallet_address) {
    document.getElementById("content").innerHTML = `
      <div class="card wallet-header">
        <div class="wallet-icon">🎯</div>
        <div class="wallet-name">Wallet Stratégie</div>
        <p style="color:var(--tg-hint);margin-top:8px">Wallet dédié aux stratégies, séparé du copy wallet</p>
      </div>
      <button class="btn btn-primary" id="sw-create">✨ Créer un wallet</button>
      <div style="height:10px"></div>
      <button class="btn btn-secondary" id="sw-import">📥 Importer une clé</button>`;
    document.getElementById("sw-create").onclick = async () => {
      const ok = await confirmModal("Créer wallet stratégie", "La PK sera affichée une fois.", "Créer");
      if (!ok) return;
      const r = await api("/strategy-wallet/create", {method:"POST"});
      await loadUser();
      document.getElementById("content").innerHTML = `
        <div class="danger-card"><h3>⚠ Sauvegardez</h3><p>Cette clé ne sera plus affichée.</p></div>
        <div class="card">
          <div class="card-title">Adresse</div><div class="wallet-addr">${r.address}</div>
          <div class="card-title" style="margin-top:12px">Clé privée</div><div class="wallet-addr">${r.private_key}</div>
          <button class="btn btn-secondary" onclick="copy('${r.private_key}')" style="margin-top:10px">📋 Copier</button>
        </div>
        <button class="btn btn-primary" onclick="go('strategies')">OK</button>`;
    };
    document.getElementById("sw-import").onclick = async () => {
      const d = await prompt2("Importer clé stratégie", [{name:"pk", label:"Clé privée", placeholder:"0x..."}]);
      if (!d) return;
      try { await api("/strategy-wallet/import", {method:"POST", body:{private_key: d.pk}}); await loadUser(); toast("Importé"); go("strategies/wallet"); }
      catch (e) { toast(e.message, "error"); }
    };
    return;
  }
  const bal = await api("/strategy-wallet/balance").catch(() => ({usdc:0, matic:0, address:me.strategy_wallet_address}));
  document.getElementById("content").innerHTML = `
    <div class="card wallet-header">
      <div class="wallet-icon">🎯</div>
      <div class="wallet-name">Wallet Stratégie</div>
    </div>
    <div class="card">
      <div class="card-title">Adresse</div>
      <div class="wallet-addr" onclick="copy('${bal.address}')">${bal.address}</div>
    </div>
    <div class="stat-grid">
      <div class="stat-box"><div class="stat-value">${fmtUsd(bal.usdc)}</div><div class="stat-label">USDC</div></div>
      <div class="stat-box"><div class="stat-value">${bal.matic.toFixed(4)}</div><div class="stat-label">MATIC</div></div>
    </div>
    <button class="btn btn-danger" id="sw-del" style="margin-top:16px">🗑 Supprimer</button>
    <button class="btn btn-secondary" onclick="go('strategies')" style="margin-top:8px">← Retour</button>`;
  document.getElementById("sw-del").onclick = async () => {
    const ok = await confirmModal("Supprimer wallet stratégie", "La clé sera effacée.", "Supprimer");
    if (!ok) return;
    await api("/strategy-wallet", {method:"DELETE"});
    await loadUser(); toast("Supprimé"); go("strategies");
  };
});

// SETTINGS
route(/^settings$/, async () => {
  const s = await api("/settings");
  const tgl = (key, label, val) => `
    <label class="toggle-row">
      <span class="toggle-label">${label}</span>
      <div class="toggle"><input type="checkbox" data-key="${key}" ${val?"checked":""}><span class="slider"></span></div>
    </label>`;
  const num = (key, label, val, step=1, min=0, max=1000) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <input class="input" type="number" data-key="${key}" value="${val ?? ""}" step="${step}" min="${min}" max="${max}">
    </div>`;
  const sel = (key, label, val, options) => `
    <div class="form-row">
      <label class="label">${label}</label>
      <select class="input" data-key="${key}">
        ${options.map(o => `<option value="${o}" ${o===val?"selected":""}>${o}</option>`).join("")}
      </select>
    </div>`;

  document.getElementById("content").innerHTML = `
    <div class="card">
      <div class="card-title">Mode</div>
      ${tgl("paper_trading", "Paper trading (fictif)", s.paper_trading)}
      ${tgl("is_paused", "Pause copy trading", s.is_paused)}
      ${tgl("strategy_is_paused", "Pause stratégies", s.strategy_is_paused)}
    </div>

    <div class="card">
      <div class="card-title">Sizing Copy</div>
      ${sel("sizing_mode", "Mode", s.sizing_mode || "FIXED", ["FIXED","PROPORTIONAL","SMART"])}
      ${num("fixed_amount", "Montant fixe USDC", s.fixed_amount, 0.5, 0.1, 1000)}
      ${num("proportional_pct", "% du master (PROPORTIONAL)", s.proportional_pct, 0.5, 0.1, 100)}
      ${num("min_trade_usdc", "Min USDC", s.min_trade_usdc, 0.5, 0, 1000)}
      ${num("max_trade_usdc", "Max USDC", s.max_trade_usdc, 0.5, 0, 10000)}
      ${num("daily_limit_usdc", "Limite quotidienne USDC", s.daily_limit_usdc, 1, 0, 100000)}
    </div>

    <div class="card">
      <div class="card-title">Stop Loss / Take Profit</div>
      ${tgl("stop_loss_enabled", "Stop Loss activé", s.stop_loss_enabled)}
      ${num("stop_loss_pct", "Stop Loss %", s.stop_loss_pct, 1, 1, 100)}
      ${tgl("take_profit_enabled", "Take Profit activé", s.take_profit_enabled)}
      ${num("take_profit_pct", "Take Profit %", s.take_profit_pct, 1, 1, 500)}
      ${tgl("trailing_stop_enabled", "Trailing stop", s.trailing_stop_enabled)}
      ${num("trailing_stop_pct", "Trailing %", s.trailing_stop_pct, 1, 1, 100)}
    </div>

    <div class="card">
      <div class="card-title">Smart Filter</div>
      ${tgl("smart_filter_enabled", "Filtre intelligent", s.smart_filter_enabled)}
      ${num("min_signal_score", "Score min (0-1)", s.min_signal_score, 0.05, 0, 1)}
      ${num("min_volume_24h", "Volume 24h min USDC", s.min_volume_24h, 100, 0, 1000000)}
      ${num("min_liquidity", "Liquidité min USDC", s.min_liquidity, 100, 0, 1000000)}
      ${num("max_spread_pct", "Spread max %", s.max_spread_pct, 0.5, 0, 50)}
    </div>

    <div class="card">
      <div class="card-title">Notifications</div>
      ${tgl("notify_on_buy", "Sur achats", s.notify_on_buy)}
      ${tgl("notify_on_sell", "Sur ventes", s.notify_on_sell)}
      ${tgl("notify_on_sl_tp", "SL / TP déclenchés", s.notify_on_sl_tp)}
    </div>

    <div class="card">
      <div class="card-title">Stratégies</div>
      ${num("strategy_trade_fee_rate", "Fee rate (0.01 - 0.20)", s.strategy_trade_fee_rate, 0.01, 0.01, 0.20)}
      ${num("strategy_max_trades_per_day", "Trades max/jour", s.strategy_max_trades_per_day, 1, 1, 200)}
    </div>`;

  const debounce = {};
  document.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    const sendUpdate = async () => {
      let val;
      if (el.type === "checkbox") val = el.checked;
      else if (el.type === "number") val = el.value === "" ? null : parseFloat(el.value);
      else val = el.value;
      if (val === null) return;
      try {
        await api("/settings", {method:"POST", body:{[key]: val}});
        toast("✓ " + key);
      } catch (e) { toast(e.message, "error"); }
    };
    if (el.type === "checkbox" || el.tagName === "SELECT") {
      el.addEventListener("change", sendUpdate);
    } else {
      el.addEventListener("input", () => {
        clearTimeout(debounce[key]);
        debounce[key] = setTimeout(sendUpdate, 500);
      });
    }
  });
});

// REPORTS
route(/^reports$/, async () => {
  const [day, week, month] = await Promise.all([
    api("/reports/pnl?period=day"),
    api("/reports/pnl?period=week"),
    api("/reports/pnl?period=month"),
  ]);
  const card = (title, r) => `
    <div class="card">
      <div class="card-title">${title}</div>
      <div class="stat-grid">
        <div class="stat-box"><div class="stat-value ${pnlClass(r.pnl)}">${fmtUsd(r.pnl)}</div><div class="stat-label">PnL</div></div>
        <div class="stat-box"><div class="stat-value">${r.trades}</div><div class="stat-label">Trades</div></div>
        <div class="stat-box"><div class="stat-value">${fmtPct(r.win_rate)}</div><div class="stat-label">Win rate</div></div>
        <div class="stat-box"><div class="stat-value ${pnlClass(r.best_trade)}">${fmtUsd(r.best_trade)}</div><div class="stat-label">Best</div></div>
      </div>
    </div>`;
  document.getElementById("content").innerHTML = `
    ${card("Aujourd'hui", day)}
    ${card("7 derniers jours", week)}
    ${card("30 derniers jours", month)}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
      <button class="btn btn-secondary" onclick="go('reports/by-trader')">Par trader</button>
      <button class="btn btn-secondary" onclick="go('reports/by-market')">Par marché</button>
    </div>`;
});

route(/^reports\/by-trader$/, async () => {
  const {traders} = await api("/reports/by-trader");
  document.getElementById("content").innerHTML = `
    <div class="section-title">PnL par trader (${traders.length})</div>
    <div class="card">
      ${traders.length === 0 ? `<div class="empty-state"><p>Aucune donnée</p></div>` :
        traders.map(t => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${t.wallet_short}</div>
              <div class="list-sub">${t.trade_count} trades · ${fmtUsd(t.volume)}</div>
            </div>
            <div class="list-right"><span class="${pnlClass(t.pnl)}">${fmtUsd(t.pnl)}</span></div>
          </div>`).join("")
      }
    </div>`;
});

route(/^reports\/by-market$/, async () => {
  const {markets} = await api("/reports/by-market");
  document.getElementById("content").innerHTML = `
    <div class="section-title">PnL par marché (${markets.length})</div>
    <div class="card">
      ${markets.length === 0 ? `<div class="empty-state"><p>Aucune donnée</p></div>` :
        markets.map(m => `
          <div class="list-item">
            <div class="list-left">
              <div class="list-title">${esc(m.market_question)}</div>
              <div class="list-sub">${m.trade_count} trades · ${fmtUsd(m.volume)}</div>
            </div>
            <div class="list-right"><span class="${pnlClass(m.pnl)}">${fmtUsd(m.pnl)}</span></div>
          </div>`).join("")
      }
    </div>`;
});

// ── Bootstrap ───────────────────────────────────────────────────
async function loadUser() {
  APP.user = await api("/me");
  return APP.user;
}

async function init() {
  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.themeParams) {
      document.body.style.background = tg.themeParams.bg_color || "";
      document.body.style.color = tg.themeParams.text_color || "";
    }
    tg.BackButton?.onClick(() => history.back());
  }

  if (!APP.initData) {
    document.getElementById("app").innerHTML = `
      <div style="padding:40px 20px;text-align:center;">
        <div style="font-size:48px;margin-bottom:12px">⚠️</div>
        <h2 style="color:#ff3b30;margin-bottom:16px">Ouvrez depuis Telegram</h2>
        <p style="color:var(--tg-hint)">Cette page doit être ouverte via le bouton Mini App dans le bot Telegram.</p>
      </div>`;
    return;
  }

  document.getElementById("app").innerHTML = `
    <div class="header">WENPOLYMARKET</div>
    <div id="content"></div>
    <div class="tab-bar">
      <a href="#home" data-tab="home"><span class="tab-icon">🏠</span><span>Home</span></a>
      <a href="#copy" data-tab="copy"><span class="tab-icon">👛</span><span>Copy</span></a>
      <a href="#strategies" data-tab="strategies"><span class="tab-icon">📊</span><span>Stratégies</span></a>
      <a href="#wallet" data-tab="wallet"><span class="tab-icon">💰</span><span>Wallet</span></a>
      <a href="#reports" data-tab="reports"><span class="tab-icon">📈</span><span>Rapports</span></a>
      <a href="#settings" data-tab="settings"><span class="tab-icon">⚙️</span><span>Réglages</span></a>
    </div>`;

  try { await loadUser(); }
  catch (e) {
    showError("Impossible de charger le profil: " + e.message);
    return;
  }

  window.addEventListener("hashchange", dispatch);
  if (!location.hash) location.hash = "home";
  else dispatch();
}

window.go = go;
window.copy = copy;
window.dispatch = dispatch;
window.walletDelete = walletDelete;
window.traderRemove = traderRemove;
window.stratDetail = stratDetail;
window.loadUser = loadUser;

init();
