// ==========================================================================
// Digital Wallet — frontend logic
// Talks to the Flask API (api.py). No build step, no frameworks.
//
// Auth: after login, the API returns a session token (backed by Redis).
// That token is sent as "Authorization: Bearer <token>" on every
// protected request - the backend uses it to know which wallet the
// logged-in user actually owns, instead of trusting a wallet_id we
// might send from here.
// ==========================================================================

const API = "/api";

// ---------------- State ----------------
let currentUser = JSON.parse(localStorage.getItem("wallet_user") || "null");
let authToken = localStorage.getItem("wallet_token") || null;

// ---------------- Elements ----------------
const authScreen = document.getElementById("auth-screen");
const dashboardScreen = document.getElementById("dashboard-screen");

const tabs = document.querySelectorAll(".tab");
const loginForm = document.getElementById("login-form");
const registerForm = document.getElementById("register-form");

const accountName = document.getElementById("account-name");
const accountWallet = document.getElementById("account-wallet");
const balanceValue = document.getElementById("balance-value");
const ledgerBody = document.getElementById("ledger-body");
const actionMessage = document.getElementById("action-message");

// ---------------- Helpers ----------------
function setMessage(el, text, type) {
  el.textContent = text || "";
  el.classList.remove("error", "success");
  if (type) el.classList.add(type);
}

function formatMoney(n) {
  return Number(n).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(ts) {
  // SQLite CURRENT_TIMESTAMP -> "YYYY-MM-DD HH:MM:SS" (UTC)
  const d = new Date(ts.replace(" ", "T") + "Z");
  if (isNaN(d)) return ts;
  return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function api(path, options = {}, auth = false) {
  const headers = { "Content-Type": "application/json" };
  if (auth && authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(API + path, { headers, ...options });
  const data = await res.json();

  if (res.status === 401 && auth) {
    // Session expired server-side - kick back to login
    logoutLocally();
    throw new Error(data.message || "Session expired. Please log in again.");
  }
  if (!res.ok) throw new Error(data.message || "Something went wrong.");
  return data;
}

// ---------------- Auth tab switching ----------------
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".auth-form").forEach((f) => f.classList.remove("active"));
    document.getElementById(`${tab.dataset.tab}-form`).classList.add("active");
  });
});

// ---------------- Register ----------------
registerForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = registerForm.querySelector(".form-message");
  const formData = new FormData(registerForm);
  const body = Object.fromEntries(formData.entries());

  try {
    const data = await api("/register", { method: "POST", body: JSON.stringify(body) });
    setMessage(msg, data.message, "success");
    registerForm.reset();
  } catch (err) {
    setMessage(msg, err.message, "error");
  }
});

// ---------------- Login ----------------
loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = loginForm.querySelector(".form-message");
  const formData = new FormData(loginForm);
  const body = Object.fromEntries(formData.entries());

  try {
    const data = await api("/login", { method: "POST", body: JSON.stringify(body) });
    currentUser = data.user;
    authToken = data.token;
    localStorage.setItem("wallet_user", JSON.stringify(currentUser));
    localStorage.setItem("wallet_token", authToken);
    loginForm.reset();
    setMessage(msg, "", null);
    showDashboard();
  } catch (err) {
    setMessage(msg, err.message, "error");
  }
});

// ---------------- Logout ----------------
function logoutLocally() {
  currentUser = null;
  authToken = null;
  localStorage.removeItem("wallet_user");
  localStorage.removeItem("wallet_token");
  showAuth();
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  try {
    await api("/logout", { method: "POST" }, true);
  } catch (_) {
    // even if the server call fails, still log out locally
  }
  logoutLocally();
});

// ---------------- Dashboard: action panel toggling ----------------
document.querySelectorAll(".action-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const action = btn.dataset.action;
    const panel = document.getElementById(`panel-${action}`);
    const isOpen = panel.classList.contains("open");

    document.querySelectorAll(".action-panel").forEach((p) => p.classList.remove("open"));
    document.querySelectorAll(".action-btn").forEach((b) => b.classList.remove("active"));

    if (!isOpen) {
      panel.classList.add("open");
      btn.classList.add("active");
      panel.querySelector("input")?.focus();
    }
    setMessage(actionMessage, "", null);
  });
});

// ---------------- Dashboard: deposit / withdraw / transfer ----------------
document.querySelectorAll('.action-panel form').forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const op = form.dataset.op;
    const formData = new FormData(form);
    const amount = formData.get("amount");

    let payload, endpoint;
    if (op === "deposit") {
      endpoint = "/deposit";
      payload = { amount };
    } else if (op === "withdraw") {
      endpoint = "/withdraw";
      payload = { amount };
    } else if (op === "transfer") {
      endpoint = "/transfer";
      payload = { to_wallet_id: formData.get("to_wallet_id"), amount };
    }

    try {
      const data = await api(endpoint, { method: "POST", body: JSON.stringify(payload) }, true);
      currentUser.balance = data.balance;
      localStorage.setItem("wallet_user", JSON.stringify(currentUser));
      balanceValue.textContent = formatMoney(data.balance);
      setMessage(actionMessage, `${capitalize(op)} successful.`, "success");
      form.reset();
      form.closest(".action-panel").classList.remove("open");
      document.querySelectorAll(".action-btn").forEach((b) => b.classList.remove("active"));
      loadHistory();
    } catch (err) {
      setMessage(actionMessage, err.message, "error");
    }
  });
});

function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

// ---------------- Ledger ----------------
async function loadHistory() {
  try {
    const data = await api("/history", {}, true);
    renderLedger(data.history);
  } catch (err) {
    ledgerBody.innerHTML = `<tr class="empty-row"><td colspan="4">Could not load history.</td></tr>`;
  }
}

function renderLedger(history) {
  if (!history.length) {
    ledgerBody.innerHTML = `<tr class="empty-row"><td colspan="4">No entries yet.</td></tr>`;
    return;
  }

  const isCredit = (type) => type === "DEPOSIT" || type === "TRANSFER_IN";

  ledgerBody.innerHTML = history
    .map((h, i) => {
      const credit = isCredit(h.txn_type);
      const sign = credit ? "+" : "-";
      const cls = credit ? "credit" : "debit";
      const statusCls = h.status === "SUCCESS" ? "success" : "failed";
      const newest = i === 0 ? "new-entry" : "";
      return `
        <tr class="${newest}">
          <td>${formatDate(h.timestamp)}</td>
          <td>${formatType(h.txn_type)}</td>
          <td class="num ${cls}">${sign}${formatMoney(h.amount)}</td>
          <td><span class="status-pill ${statusCls}">${h.status.toLowerCase()}</span></td>
        </tr>`;
    })
    .join("");
}

function formatType(type) {
  return { DEPOSIT: "Deposit", WITHDRAW: "Withdraw", TRANSFER_IN: "Transfer in", TRANSFER_OUT: "Transfer out" }[type] || type;
}

document.getElementById("refresh-btn").addEventListener("click", loadHistory);

// ---------------- Screen switching ----------------
function showDashboard() {
  authScreen.classList.add("hidden");
  dashboardScreen.classList.remove("hidden");
  accountName.textContent = currentUser.full_name;
  accountWallet.textContent = `Wallet #${currentUser.wallet_id}`;
  balanceValue.textContent = formatMoney(currentUser.balance);
  loadHistory();
}

function showAuth() {
  dashboardScreen.classList.add("hidden");
  authScreen.classList.remove("hidden");
}

// ---------------- Boot ----------------
if (currentUser && authToken) {
  showDashboard();
} else {
  showAuth();
}
