const MAX_FAIL_TESTS = 3;
const STORAGE_KEY = "pepper-ems-pairing-records";

const state = {
  loggedIn: false,
  operator: "",
  shift: "A",
};

const els = {
  operatorInput: document.getElementById("operatorInput"),
  shiftSelect: document.getElementById("shiftSelect"),
  loginButton: document.getElementById("loginButton"),
  statusBanner: document.getElementById("statusBanner"),
  operatorSummary: document.getElementById("operatorSummary"),
  serialInput: document.getElementById("serialInput"),
  customerInput: document.getElementById("customerInput"),
  poInput: document.getElementById("poInput"),
  reasonInput: document.getElementById("reasonInput"),
  passButton: document.getElementById("passButton"),
  failButton: document.getElementById("failButton"),
  recordsTableBody: document.getElementById("recordsTableBody"),
  clearHistoryBtn: document.getElementById("clearHistoryBtn"),
};

function normalizeSerialBase(serial) {
  const value = (serial || "").trim();
  if (!value || !value.includes("_")) return value;

  const [base, _, suffix] = value.split(/_(.+)/);
  if (suffix && /^\d+$/.test(suffix)) {
    return base;
  }

  return value;
}

function buildFailSerialNum(serial, failCount) {
  const base = normalizeSerialBase(serial);
  return `${base}_${failCount + 1}`;
}

function isFailLimitReached(failCount) {
  return failCount >= MAX_FAIL_TESTS;
}

function getStoredRecords() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecords(records) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records));
}

function setStatus(message, type = "info") {
  els.statusBanner.textContent = message;
  els.statusBanner.className = `status-banner ${type}`;
}

function getFailCountForSerial(serial) {
  const records = getStoredRecords();
  const base = normalizeSerialBase(serial);

  return records.filter((record) => {
    if (record.status !== "FAIL") return false;
    const serialMatch = record.serial_num === serial || record.serial_num.startsWith(`${base}_`);
    return serialMatch;
  }).length;
}

function formatTime(dateString) {
  const date = new Date(dateString);
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function renderHistory() {
  const records = getStoredRecords().slice().reverse();
  els.recordsTableBody.innerHTML = "";

  if (!records.length) {
    els.recordsTableBody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align:center;color:#64748b;padding:22px;">No recorded activity yet.</td>
      </tr>
    `;
    return;
  }

  records.forEach((record) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatTime(record.timestamp)}</td>
      <td>${record.serial_num}</td>
      <td>${record.po_num || "-"}</td>
      <td>${record.customer_sn || "-"}</td>
      <td>${record.operator || "-"}</td>
      <td>${record.shift || "-"}</td>
      <td><span class="badge ${record.status === "PASS" ? "pass" : "fail"}">${record.status}</span></td>
    `;
    els.recordsTableBody.appendChild(row);
  });
}

function resetScan() {
  els.serialInput.value = "";
  els.customerInput.value = "";
  els.poInput.value = "";
  els.reasonInput.value = "";
  els.serialInput.focus();
}

function enableScanControls(enabled) {
  els.serialInput.disabled = !enabled;
  els.customerInput.disabled = !enabled;
  els.poInput.disabled = !enabled;
  els.reasonInput.disabled = !enabled;
  els.passButton.disabled = !enabled;
  els.failButton.disabled = !enabled;
}

async function handleLogin() {
  const operator = els.operatorInput.value.trim();
  if (!operator) {
    setStatus("Enter employee number.", "warning");
    els.operatorInput.focus();
    return;
  }

  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee: operator, shift: els.shiftSelect.value }),
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      setStatus(result.message || "Authorization failed.", "error");
      return;
    }

    state.loggedIn = true;
    state.operator = result.employee;
    state.shift = result.shift;

    els.operatorInput.disabled = true;
    els.shiftSelect.disabled = true;
    els.loginButton.disabled = true;
    els.loginButton.textContent = "Logged in";

    els.operatorSummary.textContent = `${state.operator} · Shift ${state.shift}`;
    enableScanControls(true);
    setStatus(`✓ Logged in: ${state.operator} | Shift ${state.shift}`, "success");
    els.serialInput.focus();
  } catch (error) {
    setStatus(`DB error: ${error.message}`, "error");
  }
}

async function handlePass() {
  if (!state.loggedIn) {
    setStatus("Login required before saving.", "warning");
    return;
  }

  const serialNum = els.serialInput.value.trim();
  const customerSn = els.customerInput.value.trim();
  const poNum = els.poInput.value.trim();

  if (!serialNum) {
    setStatus("Scan the serial number first.", "warning");
    els.serialInput.focus();
    return;
  }

  if (!poNum) {
    setStatus("Enter the PO number before saving.", "warning");
    els.poInput.focus();
    return;
  }

  try {
    const response = await fetch("/api/record/pass", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        serial_num: serialNum,
        po_num: poNum,
        customer_sn: customerSn,
        operator: state.operator,
        shift: state.shift,
      }),
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      setStatus(result.message || "Save failed.", "error");
      return;
    }

    const record = {
      id: Date.now(),
      serial_num: serialNum,
      po_num: poNum,
      customer_sn: customerSn,
      operator: state.operator,
      shift: state.shift,
      status: "PASS",
      timestamp: new Date().toISOString(),
    };

    const records = getStoredRecords();
    records.push(record);
    saveRecords(records);
    renderHistory();

    setStatus(result.message || `✓ Saved | Serial: ${serialNum}`, "success");
    resetScan();
  } catch (error) {
    setStatus(`DB error: ${error.message}`, "error");
  }
}

async function handleFail() {
  if (!state.loggedIn) {
    setStatus("Login required before saving fail.", "warning");
    return;
  }

  const serialNum = els.serialInput.value.trim();
  const poNum = els.poInput.value.trim();
  const reason = els.reasonInput.value.trim();

  if (!serialNum) {
    setStatus("Scan the serial number first.", "warning");
    els.serialInput.focus();
    return;
  }

  if (!poNum) {
    setStatus("Enter the PO number before saving the fail.", "warning");
    els.poInput.focus();
    return;
  }

  if (!reason) {
    setStatus("Enter a failure reason before saving.", "warning");
    els.reasonInput.focus();
    return;
  }

  try {
    const response = await fetch("/api/record/fail", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        serial_num: serialNum,
        po_num: poNum,
        customer_sn: els.customerInput.value.trim(),
        operator: state.operator,
        shift: state.shift,
        reason,
      }),
    });

    const result = await response.json();
    if (!response.ok || !result.ok) {
      setStatus(result.message || "Fail save failed.", result.max_reached ? "error" : "warning");
      if (result.max_reached) {
        resetScan();
      }
      return;
    }

    const failSerial = result.serial || serialNum;
    const record = {
      id: Date.now(),
      serial_num: failSerial,
      po_num: poNum,
      customer_sn: els.customerInput.value.trim(),
      operator: state.operator,
      shift: state.shift,
      status: "FAIL",
      timestamp: new Date().toISOString(),
      remarks: reason,
      test_rep: result.fail_count || 1,
    };

    const records = getStoredRecords();
    records.push(record);
    saveRecords(records);
    renderHistory();

    setStatus(result.message || `✓ Fail saved | Serial: ${failSerial}`, "success");
    resetScan();
  } catch (error) {
    setStatus(`DB error: ${error.message}`, "error");
  }
}

function clearHistory() {
  localStorage.removeItem(STORAGE_KEY);
  renderHistory();
  setStatus("History cleared.", "info");
}

function init() {
  enableScanControls(false);
  els.shiftSelect.value = "A";
  renderHistory();
  els.loginButton.addEventListener("click", handleLogin);
  els.passButton.addEventListener("click", handlePass);
  els.failButton.addEventListener("click", handleFail);
  els.clearHistoryBtn.addEventListener("click", clearHistory);
  els.operatorInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handleLogin();
  });
  els.serialInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handlePass();
  });
  els.customerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handlePass();
  });
  els.poInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handlePass();
  });
  els.reasonInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handleFail();
  });
}

init();
