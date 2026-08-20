const LABELS = {
  indeed: "Indeed",
  linkedin: "LinkedIn",
  zip_recruiter: "ZipRecruiter",
  greenhouse: "Greenhouse",
  ashby: "Ashby",
  lever: "Lever",
  workable: "Workable",
  workday: "Workday",
  smartrecruiters: "SmartRecruiters",
  recruitee: "Recruitee",
  bamboohr: "BambooHR",
  personio: "Personio",
  breezy: "Breezy",
  teamtailor: "Teamtailor",
  pinpoint: "Pinpoint",
  jazzhr: "JazzHR",
  manatal: "Manatal",
  polymer: "Polymer",
  icims: "iCIMS",
  paylocity: "Paylocity",
  paycom: "Paycom",
  successfactors: "SuccessFactors",
  ycombinator: "Y Combinator",
};

let allJobs = [];
let activeSource = "all";

const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const submitBtn = document.getElementById("submit");
const tbody = document.getElementById("tbody");
const table = document.getElementById("table");
const empty = document.getElementById("empty");
const filterInput = document.getElementById("filter");

function chip(id, value, checked) {
  const label = document.createElement("label");
  label.className = "chip";
  label.innerHTML = `<input type="checkbox" value="${value}" ${checked ? "checked" : ""} /> ${LABELS[value] || value}`;
  document.getElementById(id).appendChild(label);
}

function selected(id) {
  return [...document.querySelectorAll(`#${id} input:checked`)].map((el) => el.value);
}

function setStatus(text) {
  statusEl.textContent = text || "";
}

function renderJobs(jobs) {
  const query = filterInput.value.trim().toLowerCase();
  const filtered = jobs.filter((job) => {
    if (activeSource !== "all" && job.source !== activeSource) return false;
    if (!query) return true;
    const blob = `${job.title} ${job.company} ${job.location} ${job.source} ${job.date_posted} ${job.description}`.toLowerCase();
    return blob.includes(query);
  });

  tbody.innerHTML = "";
  table.hidden = filtered.length === 0;
  empty.hidden = filtered.length !== 0;
  if (filtered.length === 0) {
    empty.textContent = jobs.length ? "No jobs match this filter." : "No jobs yet. Run a search above.";
  }

  for (const job of filtered) {
    const tr = document.createElement("tr");
    tr.className = "job-row";
    const locations = job.locations || [];
    const locationText = locations.map((loc) => loc.label).join(" · ") || job.location || "—";
    const remote = job.is_remote && !/remote/i.test(locationText) ? " · remote" : "";
    tr.innerHTML = `
      <td>
        <div class="title">${escapeHtml(job.company || "")}</div>
        <span class="meta">${escapeHtml(job.title || "")}</span>
      </td>
      <td class="location-cell">${escapeHtml(locationText)}${remote}</td>
      <td class="posted">${escapeHtml(formatDate(job.date_posted))}</td>
      <td><span class="pill">${escapeHtml(job.source || "")}</span></td>
      <td>${job.apply_url || job.url ? `<a class="apply" href="${escapeAttr(job.apply_url || job.url)}" target="_blank" rel="noopener">Apply</a>` : ""}</td>
    `;
    tr.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      toggleJd(tr, job);
    });
    tbody.appendChild(tr);
  }
}

function renderCounts(jobs, counts) {
  document.getElementById("stat-total").textContent = String(jobs.length);
  document.getElementById("stat-sources").textContent = String(Object.keys(counts || {}).length);
  const wrap = document.getElementById("source-filters");
  wrap.innerHTML = "";
  const sources = ["all", ...Object.keys(counts || {}).sort()];
  for (const source of sources) {
    const btn = document.createElement("button");
    btn.type = "button";
    const n = source === "all" ? jobs.length : counts[source];
    btn.textContent = source === "all" ? `All ${n}` : `${source} ${n}`;
    if (source === activeSource) btn.classList.add("active");
    btn.addEventListener("click", () => {
      activeSource = source;
      renderCounts(allJobs, countsFrom(allJobs));
      renderJobs(allJobs);
    });
    wrap.appendChild(btn);
  }
}

function countsFrom(jobs) {
  const counts = {};
  for (const job of jobs) {
    counts[job.source] = (counts[job.source] || 0) + 1;
  }
  return counts;
}

function showJobs(jobs, counts) {
  allJobs = jobs || [];
  activeSource = "all";
  renderCounts(allJobs, counts || countsFrom(allJobs));
  renderJobs(allJobs);
}

function toggleJd(row, job) {
  const next = row.nextElementSibling;
  const alreadyOpen = next && next.classList.contains("jd-row");
  closeOpenJd();
  if (alreadyOpen) return;
  row.classList.add("is-open");
  const detail = document.createElement("tr");
  detail.className = "jd-row";
  const jd = (job.description || "").trim() || "No job description available for this listing.";
  const locationLinks = locationLinkHtml(job);
  detail.innerHTML = `
    <td colspan="5">
      <div class="jd-panel">
        <p class="jd-label">Job description</p>
        <div class="jd">${escapeHtml(jd)}</div>
        ${locationLinks}
      </div>
    </td>
  `;
  row.after(detail);
}

function locationLinkHtml(job) {
  const locations = job.locations || [];
  if (!locations.length) return "";
  const links = locations
    .map((loc) => {
      const label = escapeHtml(loc.label || "See posting");
      const href = loc.url ? escapeAttr(loc.url) : "";
      if (!href) return `<span>${label}</span>`;
      return `<a class="location-link" href="${href}" target="_blank" rel="noopener">${label}</a>`;
    })
    .join(" · ");
  return `<p class="jd-label">Locations</p><div class="jd-locations">${links}</div>`;
}

function closeOpenJd() {
  for (const open of tbody.querySelectorAll(".jd-row")) open.remove();
  for (const row of tbody.querySelectorAll(".job-row.is-open")) row.classList.remove("is-open");
}

function formatDate(value) {
  if (!value) return "—";
  const text = String(value).trim();
  if (/just now|moments? ago|\d+\s*(minutes?|hours?)\s+ago/i.test(text)) return text;

  let date = null;
  const hasClock = /T\d{2}:|\d{2}:\d{2}|^\d{10,13}$/.test(text);
  if (/^\d{10,13}$/.test(text)) {
    const ms = text.length > 10 ? Number(text) : Number(text) * 1000;
    date = new Date(ms);
  } else {
    const parsed = Date.parse(text);
    if (!Number.isNaN(parsed)) date = new Date(parsed);
  }
  if (date && !Number.isNaN(date.getTime()) && hasClock) {
    const hours = (Date.now() - date.getTime()) / 3600000;
    if (hours >= 0 && hours < 24) {
      if (hours < 1) {
        const minutes = Math.max(1, Math.round(hours * 60));
        return minutes < 2 ? "just now" : `${minutes} min ago`;
      }
      const whole = Math.max(1, Math.round(hours));
      return whole === 1 ? "1 hour ago" : `${whole} hours ago`;
    }
  }
  if (date && !Number.isNaN(date.getTime())) return date.toISOString().slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) return text.slice(0, 10);
  return text;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

async function poll(id, started) {
  const res = await fetch(`/api/search/${id}`);
  const data = await res.json();
  const elapsed = Math.round((Date.now() - started) / 1000);
  if (data.status === "running") {
    setStatus(`Fetching… ${elapsed}s`);
    setTimeout(() => poll(id, started), 1500);
    return;
  }
  submitBtn.disabled = false;
  if (data.status === "error") {
    setStatus(data.error || "Search failed");
    return;
  }
  setStatus(
    `${(data.jobs || []).length} jobs in ${elapsed}s · saved ${data.saved?.inserted || 0} new, ${data.saved?.updated || 0} updated`
  );
  showJobs(data.jobs, data.counts);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    query: document.getElementById("query").value.trim(),
    location: document.getElementById("location").value.trim() || "United States",
    boards: selected("board-chips"),
    ats: selected("ats-chips"),
    usa_only: document.getElementById("usa-only").checked,
    results_wanted: Number(document.getElementById("results").value || 100),
  };
  submitBtn.disabled = true;
  setStatus("Starting search…");
  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    submitBtn.disabled = false;
    setStatus(data.detail || "Could not start search");
    return;
  }
  poll(data.id, Date.now());
});

filterInput.addEventListener("input", () => renderJobs(allJobs));

async function boot() {
  const defaults = await fetch("/api/defaults").then((r) => r.json());
  document.getElementById("query").value = defaults.query;
  document.getElementById("location").value = defaults.location;
  document.getElementById("results").value = defaults.results_wanted || 100;
  document.getElementById("usa-only").checked = defaults.usa_only;
  for (const name of defaults.board_options) {
    chip("board-chips", name, defaults.boards.includes(name) && name !== "linkedin");
  }
  for (const name of defaults.ats_options) {
    chip("ats-chips", name, defaults.ats.includes(name) && name !== "workday");
  }
  const saved = await fetch("/api/jobs").then((r) => r.json());
  if (saved.jobs && saved.jobs.length) {
    setStatus(`Loaded ${saved.jobs.length} jobs from the last run`);
    showJobs(saved.jobs, saved.counts);
  }
}

boot();
