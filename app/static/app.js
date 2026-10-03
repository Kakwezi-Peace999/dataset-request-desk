/* Dataset Request Desk: a deliberately small single-page UI (no build step).
 * The server enforces every rule; this file only shows what the current role is allowed to try.
 * Everything that comes from the server is passed through esc() before it touches innerHTML (XSS defence).
 */
(() => {
  "use strict";

  const app = document.getElementById("app");
  const state = { token: localStorage.getItem("drd_token"), user: null, tab: "requests", selected: null, statusFilter: "" };

  const LABEL = { submitted: "Submitted", in_progress: "In progress", delivered: "Delivered", accepted: "Accepted", rejected: "Rejected" };
  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const when = (v) => (v ? new Date(v).toLocaleString() : "");
  const day = (v) => (v ? new Date(v + "T00:00:00").toLocaleDateString() : "");
  const badge = (s) => `<span class="badge ${esc(s)}">${esc(LABEL[s] || s)}</span>`;
  const isStaff = () => state.user && state.user.role !== "client";

  /* ---------- API ---------- */
  class ApiError extends Error { constructor(status, message) { super(message); this.status = status; } }

  function formatDetail(d) {
    if (!d) return "";
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
    if (d.problems) return `${d.message}: ` + d.problems.map((p) => `${p.episode_id} (${p.reason})`).join("; ");
    return JSON.stringify(d);
  }

  async function api(path, { method = "GET", body, form } = {}) {
    const headers = {};
    if (state.token) headers.Authorization = "Bearer " + state.token;
    let payload;
    if (form) payload = form;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    const res = await fetch(path, { method, headers, body: payload });
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty body */ }
    if (!res.ok) {
      if (res.status === 401 && state.user) logout(true);
      throw new ApiError(res.status, formatDetail(data && data.detail) || res.statusText);
    }
    return data;
  }

  let toastTimer;
  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.className = "show" + (isError ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => (el.className = ""), isError ? 6000 : 3000);
  }
  const fail = (e) => toast(e.message || "Something went wrong", true);

  /* ---------- session ---------- */
  function logout(expired = false) {
    state.token = null; state.user = null; state.selected = null; state.tab = "requests";
    localStorage.removeItem("drd_token");
    render();
    if (expired) toast("Your session ended. Please sign in again.", true);
  }

  async function boot() {
    if (state.token) {
      try { state.user = await api("/api/auth/me"); } catch (_) { state.token = null; localStorage.removeItem("drd_token"); }
    }
    render();
  }

  function render() {
    if (!state.user) return renderLogin();
    app.innerHTML = `
      <header class="topbar">
        <h1>Dataset Request Desk</h1>
        <span class="who">${esc(state.user.name)} (${esc(state.user.role)})</span>
        <button class="btn secondary" id="logout">Sign out</button>
      </header>
      <main class="container" id="main"></main>`;
    $("#logout").onclick = () => logout();
    isStaff() ? renderStaff() : renderClient();
  }

  function renderLogin() {
    app.innerHTML = `
      <main class="card login">
        <h1>Dataset Request Desk</h1>
        <p class="muted small">Sign in to request or fulfil robot data.</p>
        <form id="login">
          <label for="email">Email</label><input id="email" type="email" autocomplete="username" required>
          <label for="password">Password</label><input id="password" type="password" autocomplete="current-password" required>
          <p class="error" id="login-error" role="alert"></p>
          <button class="btn" type="submit">Sign in</button>
        </form>
      </main>`;
    $("#login").onsubmit = async (ev) => {
      ev.preventDefault();
      try {
        const r = await api("/api/auth/login", { method: "POST", body: { email: $("#email").value, password: $("#password").value } });
        state.token = r.access_token; state.user = r.user;
        localStorage.setItem("drd_token", state.token);
        render();
      } catch (e) { $("#login-error").textContent = e.message; }
    };
  }

  /* ---------- shared: request table + detail ---------- */
  function requestsTable(rows) {
    if (!rows.length) return `<p class="empty">No requests yet.</p>`;
    return `<div class="scroll"><table><thead><tr><th>#</th><th>Task</th>${isStaff() ? "<th>Client</th>" : ""}<th class="num">Episodes</th><th>Deadline</th><th>Status</th></tr></thead><tbody>` +
      rows.map((r) => `<tr class="clickable ${r.id === state.selected ? "selected" : ""}" data-id="${r.id}" tabindex="0">
        <td>${r.id}</td><td>${esc(r.task_name)}</td>${isStaff() ? `<td>${esc(r.client.organisation || r.client.name)}</td>` : ""}
        <td class="num">${r.assigned_count}/${r.episodes_requested}</td><td>${day(r.deadline)}</td><td>${badge(r.status)}</td></tr>`).join("") +
      `</tbody></table></div>`;
  }

  function bindRows(container, onOpen) {
    container.querySelectorAll("tr.clickable").forEach((tr) => {
      const open = () => onOpen(Number(tr.dataset.id));
      tr.onclick = open;
      tr.onkeydown = (e) => { if (e.key === "Enter") open(); };
    });
  }

  const ACTION_LABEL = (to, from) => ({
    in_progress: from === "rejected" ? "Start rework" : "Start work",
    delivered: "Mark as delivered", accepted: "Accept delivery", rejected: "Reject delivery",
  }[to]);

  function stepper(status) {
    const steps = ["submitted", "in_progress", "delivered", status === "rejected" ? "rejected" : "accepted"];
    const cur = steps.indexOf(status);
    return `<ol class="stepper" aria-label="Progress">` + steps.map((s, i) =>
      `<li class="${i < cur ? "done" : ""} ${i === cur ? "current " + s : ""}" ${i === cur ? 'aria-current="step"' : ""}>${esc(LABEL[s])}</li>`).join("") + `</ol>`;
  }

  async function renderDetail() {
    const box = $("#detail");
    if (!box) return;
    if (!state.selected) { box.innerHTML = `<div class="card"><p class="empty">Select a request to see its details.</p></div>`; return; }
    let r;
    try { r = await api(`/api/requests/${state.selected}`); } catch (e) { box.innerHTML = `<div class="card"><p class="error">${esc(e.message)}</p></div>`; return; }
    const pct = Math.min(100, Math.round((r.assigned_count / r.episodes_requested) * 100));
    const showEpisodes = isStaff() || ["delivered", "accepted", "rejected"].includes(r.status);
    box.innerHTML = `
      <div class="card">
        <h2>Request #${r.id}: ${esc(r.task_name)}</h2>
        ${stepper(r.status)}
        <dl class="kv">
          <dt>Client</dt><dd>${esc(r.client.name)}${r.client.organisation ? " (" + esc(r.client.organisation) + ")" : ""}</dd>
          <dt>Deadline</dt><dd>${day(r.deadline)}</dd>
          <dt>Episodes</dt><dd>${r.assigned_count} assigned of ${r.episodes_requested} requested
            <div class="progress" aria-hidden="true"><span style="width:${pct}%"></span></div></dd>
          <dt>Notes</dt><dd>${esc(r.notes) || '<span class="muted">none</span>'}</dd>
        </dl>
        ${r.allowed_transitions.length ? `
          <label for="comment">Comment (optional)</label><textarea id="comment" maxlength="1000"></textarea>
          <div class="actions">${r.allowed_transitions.map((to) =>
            `<button class="btn ${to === "rejected" ? "danger" : ""}" data-to="${to}">${esc(ACTION_LABEL(to, r.status))}</button>`).join("")}</div>` : ""}
      </div>
      ${showEpisodes ? `<div class="card" id="assigned"></div>` : ""}
      ${isStaff() && r.status === "in_progress" ? `<div class="card" id="picker"></div>` : ""}
      <div class="card"><h3>History</h3><ul class="history">${r.history.map((h) =>
        `<li>${badge(h.to_status)} by ${esc(h.actor)} <span class="muted small">${when(h.at)}</span>${h.comment ? `<div class="small">“${esc(h.comment)}”</div>` : ""}</li>`).join("")}</ul></div>`;

    box.querySelectorAll("[data-to]").forEach((btn) => {
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          await api(`/api/requests/${r.id}/transition`, { method: "POST", body: { to: btn.dataset.to, comment: ($("#comment") || {}).value || null } });
          toast("Status updated");
          await refreshAll();
        } catch (e) { fail(e); btn.disabled = false; }
      };
    });
    if (showEpisodes) renderAssigned(r);
    if (isStaff() && r.status === "in_progress") mountPicker($("#picker"), { requestId: r.id, task: r.task_name, onChange: refreshAll });
  }

  async function renderAssigned(r) {
    const el = $("#assigned");
    try {
      const eps = await api(`/api/requests/${r.id}/episodes`);
      const canEdit = isStaff() && r.status === "in_progress";
      el.innerHTML = `<h3>Assigned episodes (${eps.length})</h3>` + (eps.length ? `<div class="scroll"><table><thead><tr><th>Episode</th><th>Robot</th><th>Task</th><th>Quality</th><th class="num">Seconds</th>${canEdit ? "<th></th>" : ""}</tr></thead><tbody>` +
        eps.map((e) => `<tr><td>${esc(e.episode_id)}</td><td>${esc(e.robot_id)}</td><td>${esc(e.task_name)}</td><td>${badge(e.quality)}</td><td class="num">${e.duration_seconds}</td>${canEdit ? `<td><button class="link" data-remove="${esc(e.episode_id)}">Remove</button></td>` : ""}</tr>`).join("") + `</tbody></table></div>` : `<p class="empty">Nothing assigned yet.</p>`);
      el.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = async () => {
        try { await api(`/api/requests/${r.id}/assignments/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" }); toast("Episode removed"); await refreshAll(); } catch (e) { fail(e); }
      }));
    } catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p>`; }
  }

  async function refreshAll() {
    if (typeof state.reloadList === "function") await state.reloadList();
    await renderDetail();
  }

  /* ---------- episode picker / browser (staff) ---------- */
  async function mountPicker(el, { requestId = null, task = "", onChange = null } = {}) {
    const selectable = requestId !== null;
    const f = { task: "", quality: "", unassigned: selectable, offset: 0 };
    const picked = new Set();
    const PAGE = 20;
    let tasks = [];
    try { tasks = await api("/api/episodes/task-names"); } catch (e) { el.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
    if (tasks.includes(task)) f.task = task;

    el.innerHTML = `
      <h3>${selectable ? "Add episodes" : "Browse episodes"}</h3>
      <div class="row">
        <div><label for="f-task">Task</label><select id="f-task"><option value="">All tasks</option>${tasks.map((t) => `<option ${t === f.task ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>
        <div><label for="f-quality">Quality</label><select id="f-quality"><option value="">${selectable ? "Good or usable" : "Any"}</option><option>good</option><option>usable</option>${selectable ? "" : "<option>bad</option>"}</select></div>
        <div class="auto"><label class="inline"><input type="checkbox" id="f-free" ${f.unassigned ? "checked" : ""}> Unassigned only</label></div>
      </div>
      <div id="p-table"></div><div class="pager" id="p-pager"></div>
      ${selectable ? `<div class="actions"><button class="btn" id="p-assign" disabled>Assign selected</button></div>` : ""}`;

    async function load() {
      const q = new URLSearchParams({ limit: PAGE, offset: f.offset });
      if (f.task) q.set("task_name", f.task);
      if (f.quality) q.set("quality", f.quality);
      if (f.unassigned) q.set("unassigned_only", "true");
      let data;
      try { data = await api("/api/episodes?" + q); } catch (e) { $("#p-table", el).innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
      // When picking, 'bad' episodes can never be assigned, so hide them unless the person filtered explicitly.
      const rows = selectable && !f.quality ? data.items.filter((e) => e.quality !== "bad") : data.items;
      $("#p-table", el).innerHTML = rows.length ? `<div class="scroll"><table><thead><tr>${selectable ? "<th></th>" : ""}<th>Episode</th><th>Robot</th><th>Task</th><th>Quality</th><th class="num">Seconds</th><th>Recorded</th>${selectable ? "" : "<th>Request</th>"}</tr></thead><tbody>` +
        rows.map((e) => `<tr>${selectable ? `<td><input type="checkbox" data-pick="${esc(e.episode_id)}" aria-label="Select ${esc(e.episode_id)}" ${picked.has(e.episode_id) ? "checked" : ""} ${e.assigned_request_id ? "disabled" : ""}></td>` : ""}
          <td>${esc(e.episode_id)}</td><td>${esc(e.robot_id)}</td><td>${esc(e.task_name)}</td><td>${badge(e.quality)}</td><td class="num">${e.duration_seconds}</td><td>${when(e.recorded_at)}</td>
          ${selectable ? "" : `<td>${e.assigned_request_id ? "#" + e.assigned_request_id : '<span class="muted">free</span>'}</td>`}</tr>`).join("") + `</tbody></table></div>` : `<p class="empty">No episodes match these filters.</p>`;
      const from = data.total ? f.offset + 1 : 0, to = Math.min(f.offset + PAGE, data.total);
      $("#p-pager", el).innerHTML = `<span>${from}-${to} of ${data.total}</span><button class="btn secondary" id="p-prev" ${f.offset === 0 ? "disabled" : ""}>Previous</button><button class="btn secondary" id="p-next" ${to >= data.total ? "disabled" : ""}>Next</button>`;
      $("#p-prev", el).onclick = () => { f.offset = Math.max(0, f.offset - PAGE); load(); };
      $("#p-next", el).onclick = () => { f.offset += PAGE; load(); };
      el.querySelectorAll("[data-pick]").forEach((cb) => (cb.onchange = () => { cb.checked ? picked.add(cb.dataset.pick) : picked.delete(cb.dataset.pick); updateBtn(); }));
    }
    function updateBtn() { const b = $("#p-assign", el); if (b) { b.disabled = picked.size === 0; b.textContent = picked.size ? `Assign ${picked.size} selected` : "Assign selected"; } }

    $("#f-task", el).onchange = (e) => { f.task = e.target.value; f.offset = 0; load(); };
    $("#f-quality", el).onchange = (e) => { f.quality = e.target.value; f.offset = 0; load(); };
    $("#f-free", el).onchange = (e) => { f.unassigned = e.target.checked; f.offset = 0; load(); };
    if (selectable) {
      $("#p-assign", el).onclick = async () => {
        try {
          const r = await api(`/api/requests/${requestId}/assignments`, { method: "POST", body: { episode_ids: [...picked] } });
          toast(`Assigned ${r.assigned} episode(s)`);
          if (onChange) await onChange();
        } catch (e) { fail(e); load(); }
      };
    }
    load();
  }

  /* ---------- client UI ---------- */
  function renderClient() {
    const main = $("#main");
    const nextWeek = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
    main.innerHTML = `
      <div class="split">
        <div>
          <div class="card">
            <h2>New request</h2>
            <form id="new-request">
              <label for="task">What should the robot do?</label><input id="task" required maxlength="200" placeholder="e.g. pick cup">
              <div class="row">
                <div><label for="count">Episodes needed</label><input id="count" type="number" min="1" max="1000000" required value="100"></div>
                <div><label for="deadline">Needed by</label><input id="deadline" type="date" required value="${nextWeek}" min="${new Date().toISOString().slice(0, 10)}"></div>
              </div>
              <label for="notes">Notes (optional)</label><textarea id="notes" maxlength="5000"></textarea>
              <p class="error" id="nr-error" role="alert"></p>
              <button class="btn" type="submit">Submit request</button>
            </form>
          </div>
          <div class="card"><h2>My requests</h2><div id="list"></div></div>
        </div>
        <div id="detail"></div>
      </div>`;
    state.reloadList = async () => {
      try { const rows = await api("/api/requests"); $("#list").innerHTML = requestsTable(rows); bindRows($("#list"), selectRequest); } catch (e) { fail(e); }
    };
    $("#new-request").onsubmit = async (ev) => {
      ev.preventDefault();
      $("#nr-error").textContent = "";
      try {
        const r = await api("/api/requests", { method: "POST", body: { task_name: $("#task").value, episodes_requested: Number($("#count").value), deadline: $("#deadline").value, notes: $("#notes").value || null } });
        toast("Request submitted");
        ev.target.reset();
        state.selected = r.id;
        await refreshAll();
      } catch (e) { $("#nr-error").textContent = e.message; }
    };
    state.reloadList(); renderDetail();
  }

  async function selectRequest(id) { state.selected = id; await refreshAll(); }

  /* ---------- staff UI ---------- */
  function renderStaff() {
    const tabs = [["requests", "Requests"], ["episodes", "Episodes & import"], ["analytics", "Analytics"]];
    if (state.user.role === "admin") tabs.push(["users", "Users"]);
    $("#main").innerHTML = `<div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button role="tab" aria-selected="${k === state.tab}" data-tab="${k}">${l}</button>`).join("")}</div><div id="panel"></div>`;
    document.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { state.tab = b.dataset.tab; renderStaff(); }));
    ({ requests: staffRequests, episodes: staffEpisodes, analytics: staffAnalytics, users: staffUsers }[state.tab])($("#panel"));
  }

  function staffRequests(panel) {
    panel.innerHTML = `<div class="split"><div class="card">
      <div class="row"><div><label for="sf">Status</label><select id="sf"><option value="">All</option>${Object.entries(LABEL).map(([k, v]) => `<option value="${k}" ${k === state.statusFilter ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
      <div id="list"></div></div><div id="detail"></div></div>`;
    state.reloadList = async () => {
      try { const rows = await api("/api/requests" + (state.statusFilter ? "?status=" + state.statusFilter : "")); $("#list").innerHTML = requestsTable(rows); bindRows($("#list"), selectRequest); } catch (e) { fail(e); }
    };
    $("#sf").onchange = (e) => { state.statusFilter = e.target.value; state.reloadList(); };
    state.reloadList(); renderDetail();
  }

  function staffEpisodes(panel) {
    state.reloadList = null;
    panel.innerHTML = `
      <div class="card"><h2>Import episodes from CSV</h2>
        <p class="muted small">Safe to run more than once: episodes that already exist are skipped, and every skipped or rejected row is listed with its reason.</p>
        <form id="import"><div class="row"><div><label for="csv">CSV file</label><input id="csv" type="file" accept=".csv,text/csv" required></div><div class="auto"><button class="btn" type="submit">Import</button></div></div></form>
        <div id="report"></div></div>
      <div class="card" id="browse"></div>`;
    $("#import").onsubmit = async (ev) => {
      ev.preventDefault();
      const form = new FormData(); form.append("file", $("#csv").files[0]);
      $("#report").innerHTML = `<p class="muted">Importing…</p>`;
      try { renderReport(await api("/api/imports/episodes", { method: "POST", form })); mountPicker($("#browse")); } catch (e) { $("#report").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    mountPicker($("#browse"));
  }

  function renderReport(r) {
    const stat = (n, l) => `<div><strong>${n}</strong><div class="muted small">${l}</div></div>`;
    $("#report").innerHTML = `
      <h3>Import report</h3>
      <div class="row" style="margin-bottom:.8rem">${stat(r.total_rows, "rows read")}${stat(r.imported, "imported")}${stat(r.already_imported, "already existed")}${stat(r.duplicates_in_file, "duplicates in file")}${stat(r.conflicts, "conflicts")}${stat(r.rejected, "rejected")}</div>
      ${r.issues.length ? `<div class="scroll"><table><thead><tr><th>Line</th><th>Episode</th><th>Outcome</th><th>Reason</th></tr></thead><tbody>${r.issues.map((i) => `<tr><td>${i.line}</td><td>${esc(i.episode_id) || "-"}</td><td>${esc(i.outcome.replaceAll("_", " "))}</td><td>${esc(i.reason)}</td></tr>`).join("")}</tbody></table></div>${r.issues_truncated ? '<p class="muted small">Only the first issues are shown.</p>' : ""}` : '<p class="muted">No problems found.</p>'}`;
  }

  function fmtDuration(sec) {
    if (sec === null || sec === undefined) return "no delivered requests in range";
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return `${h ? h + " h " : ""}${m} min`;
  }

  function staffAnalytics(panel) {
    state.reloadList = null;
    panel.innerHTML = `<div class="card"><h2>Analytics</h2>
      <form id="an" class="row"><div><label for="from">From</label><input type="date" id="from"></div><div><label for="to">To</label><input type="date" id="to"></div><div class="auto"><button class="btn" type="submit">Run</button></div></form>
      <p class="muted small">Leave dates empty for all time. Days are UTC. Requests are counted by the day they were submitted.</p></div><div id="an-out"></div>`;
    const run = async (ev) => {
      if (ev) ev.preventDefault();
      const q = new URLSearchParams();
      if ($("#from").value) q.set("from", $("#from").value);
      if ($("#to").value) q.set("to", $("#to").value);
      try {
        const r = await api("/api/analytics?" + q);
        $("#an-out").innerHTML = `
          <div class="split"><div class="card"><h3>Requests by status (${r.requests.total} total)</h3><table><tbody>${Object.entries(r.requests.by_status).map(([s, n]) => `<tr><td>${badge(s)}</td><td class="num">${n}</td></tr>`).join("")}</tbody></table>
            <p>Median time from submitted to delivered: <strong>${fmtDuration(r.requests.median_seconds_submitted_to_delivered)}</strong>
            <span class="muted small">(${r.requests.delivered_sample_size} delivered)</span></p></div>
          <div class="card"><h3>Top tasks by good episodes</h3>${r.top_tasks_by_good_episodes.length ? `<table><tbody>${r.top_tasks_by_good_episodes.map((t) => `<tr><td>${esc(t.task_name)}</td><td class="num">${t.good_episodes}</td></tr>`).join("")}</tbody></table>` : '<p class="empty">No good episodes in range.</p>'}</div></div>
          <div class="card"><h3>Episodes recorded per day, per robot</h3>${r.episodes_per_day_per_robot.length ? `<div class="scroll" style="max-height:340px;overflow-y:auto"><table><thead><tr><th>Date</th><th>Robot</th><th class="num">Episodes</th></tr></thead><tbody>${r.episodes_per_day_per_robot.map((x) => `<tr><td>${esc(x.date)}</td><td>${esc(x.robot_id)}</td><td class="num">${x.count}</td></tr>`).join("")}</tbody></table></div>` : '<p class="empty">No episodes in range.</p>'}</div>`;
      } catch (e) { $("#an-out").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    };
    $("#an").onsubmit = run; run();
  }

  async function staffUsers(panel) {
    state.reloadList = null;
    panel.innerHTML = `<div class="split"><div class="card"><h2>Users</h2><div id="users"></div></div>
      <div class="card"><h2>Create user</h2><form id="nu">
        <label for="u-name">Name</label><input id="u-name" required maxlength="200">
        <label for="u-email">Email</label><input id="u-email" type="email" required>
        <label for="u-pass">Password (min 8 characters)</label><input id="u-pass" type="password" minlength="8" required autocomplete="new-password">
        <label for="u-role">Role</label><select id="u-role"><option>client</option><option>operator</option><option>admin</option></select>
        <label for="u-org">Organisation (clients)</label><input id="u-org" maxlength="200">
        <p class="error" id="u-error" role="alert"></p><button class="btn" type="submit">Create user</button></form></div></div>`;
    async function load() {
      try {
        const users = await api("/api/users");
        $("#users").innerHTML = `<div class="scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th></tr></thead><tbody>${users.map((u) => `<tr>
          <td>${esc(u.name)}</td><td>${esc(u.email)}</td>
          <td><select data-role="${u.id}" aria-label="Role for ${esc(u.name)}" ${u.id === state.user.id ? "disabled" : ""}>${["client", "operator", "admin"].map((r) => `<option ${r === u.role ? "selected" : ""}>${r}</option>`).join("")}</select></td>
          <td><input type="checkbox" data-active="${u.id}" aria-label="Active: ${esc(u.name)}" ${u.is_active ? "checked" : ""} ${u.id === state.user.id ? "disabled" : ""}></td></tr>`).join("")}</tbody></table></div>`;
        document.querySelectorAll("[data-role]").forEach((s) => (s.onchange = () => patch(s.dataset.role, { role: s.value })));
        document.querySelectorAll("[data-active]").forEach((c) => (c.onchange = () => patch(c.dataset.active, { is_active: c.checked })));
      } catch (e) { $("#users").innerHTML = `<p class="error">${esc(e.message)}</p>`; }
    }
    async function patch(id, body) { try { await api(`/api/users/${id}`, { method: "PATCH", body }); toast("User updated"); } catch (e) { fail(e); } load(); }
    $("#nu").onsubmit = async (ev) => {
      ev.preventDefault(); $("#u-error").textContent = "";
      try {
        await api("/api/users", { method: "POST", body: { name: $("#u-name").value, email: $("#u-email").value, password: $("#u-pass").value, role: $("#u-role").value, organisation: $("#u-org").value || null } });
        toast("User created"); ev.target.reset(); load();
      } catch (e) { $("#u-error").textContent = e.message; }
    };
    load();
  }

  boot();
})();
