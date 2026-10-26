// SkillSim frontend. Every screen renders from API data; the browser never sees an API key.

const app = document.getElementById("app");
const state = { health: null, scenarios: null };

// ---------- helpers ----------

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const initials = (name) => name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const fmtInt = (n) => Math.round(Number(n || 0)).toLocaleString();
const fmtUsd = (n) => (n == null ? "n/a" : n >= 1 ? `$${n.toFixed(2)}` : n >= 0.01 ? `$${n.toFixed(4)}` : `$${Number(n).toFixed(5)}`);
const fmtDate = (iso) =>
  new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const mockTag = (source) => (source === "mock" ? `<span class="mock-tag">Mock response</span>` : "");

// A random ID for this browser. The server only shows a session to the browser that created it.
const CLIENT_ID = (() => {
  let id = localStorage.getItem("skillsimClient");
  if (!id) {
    id = Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("skillsimClient", id);
  }
  return id;
})();

async function api(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", "X-SkillSim-Client": CLIENT_ID },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
    const err = new Error(detail || `Request failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function getScenarios() {
  if (!state.scenarios) state.scenarios = await api("/scenarios");
  return state.scenarios;
}

const go = (hash) => (location.hash = hash);

async function startSession(scenarioId, retryOf = null) {
  const session = await api("/sessions", { method: "POST", body: { scenario_id: scenarioId, retry_of: retryOf } });
  go(`#/session/${session.id}`);
}

function setNav(key) {
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === key));
}

// ---------- screens ----------

function renderHome() {
  setNav(null);
  app.innerHTML = `
    <section class="hero">
      <div>
        <div class="eyebrow">Conversation practice</div>
        <h1>Practice the conversations that matter, before they happen.</h1>
        <p class="lead">SkillSim lets you rehearse hard workplace conversations with a realistic AI partner,
          then shows you exactly what worked and what to try next.</p>
        <div class="btn-row">
          <a class="btn btn-primary" href="#/scenarios">Choose a scenario</a>
          <a class="btn btn-secondary" href="#how">How it works</a>
        </div>
      </div>
      <div class="card hero-preview" aria-hidden="true">
        <div class="messages" style="background:transparent;padding:0">
          <div class="msg ai"><div class="avatar">MB</div>
            <div class="bubble">I'll be honest, I'm not happy. We told three thousand patients the portal goes live Monday.</div></div>
          <div class="msg user"><div class="avatar you">You</div>
            <div class="bubble">That's on us, and I'm sorry. Can I walk you through what happened and what we're changing?</div></div>
          <div class="msg ai"><div class="avatar">MB</div>
            <div class="bubble">Okay. What's actually different this time?</div></div>
        </div>
      </div>
    </section>
    <section id="how">
      <div class="section-head"><div class="eyebrow">How it works</div><h2>Three steps, about ten minutes</h2></div>
      <div class="steps">
        <div class="card card-pad step"><div class="num">1</div><h3>Pick a scenario</h3>
          <p class="muted">Feedback for a direct report, a salary negotiation, or an upset client.</p></div>
        <div class="card card-pad step"><div class="num">2</div><h3>Have the conversation</h3>
          <p class="muted">Chat with an AI partner who reacts the way a real person would.</p></div>
        <div class="card card-pad step"><div class="num">3</div><h3>Get feedback, then retry</h3>
          <p class="muted">See a skill-by-skill score and specific phrasing to try on your next attempt.</p></div>
      </div>
    </section>`;
  document.getElementById("app").querySelector('a[href="#how"]').addEventListener("click", (e) => {
    e.preventDefault();
    document.getElementById("how").scrollIntoView({ behavior: "smooth" });
  });
}

async function renderScenarios() {
  setNav("scenarios");
  const scenarios = await getScenarios();
  app.innerHTML = `
    <div class="section-head">
      <div class="eyebrow">Scenarios</div>
      <h1 style="font-size:2.2rem">Choose a conversation to practice</h1>
      <p class="muted">Each one takes under ten minutes and ends with personal feedback.</p>
    </div>
    <div class="grid-3">
      ${scenarios
        .map(
          (s) => `
        <article class="card scenario-card">
          <div class="cat">${esc(s.category)}</div>
          <h3>${esc(s.title)}</h3>
          <div class="meta"><span>${esc(s.difficulty)}</span><span>·</span><span>~${s.minutes} min</span></div>
          <p>${esc(s.summary)}</p>
          <div class="tags">${s.skills.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div>
          <a class="btn btn-secondary" href="#/scenarios/${esc(s.id)}">View scenario →</a>
        </article>`
        )
        .join("")}
    </div>`;
}

async function renderIntro(id) {
  setNav("scenarios");
  const s = await api(`/scenarios/${encodeURIComponent(id)}`);
  app.innerHTML = `
    <a class="back" href="#/scenarios">← All scenarios</a>
    <div class="intro">
      <div>
        <div class="eyebrow">${esc(s.category)} · ${esc(s.difficulty)} · ~${s.minutes} min</div>
        <h1 style="font-size:2.3rem">${esc(s.title)}</h1>
        <p class="context">${esc(s.context)}</p>
        <div class="roles">
          ${roleCard("Your role", s.user_role, true)}
          ${roleCard("You'll be talking to", s.ai_role, false)}
        </div>
        <div class="dynamics">
          <div><div class="role-label">Relationship</div><p class="muted small">${esc(s.relationship)}</p></div>
          <div><div class="role-label">Power dynamics</div><p class="muted small">${esc(s.power_dynamics)}</p></div>
        </div>
        <section class="decode-intro card card-pad">
          <div class="decode-head">
            <div><h3 style="margin:0">Decode this situation</h3>
              <p class="small muted" style="margin:4px 0 0">Unfamiliar phrases, power dynamics, what you can't know yet, and questions you could ask.</p></div>
            <button class="btn btn-secondary" id="decode-btn">Decode</button>
          </div>
          <div id="decode-body"></div>
        </section>
      </div>
      <aside class="sticky">
        <div class="objective">
          <div class="eyebrow">Your objective</div>
          <p style="margin:0">${esc(s.objective)}</p>
        </div>
        <div class="card card-pad">
          <h3>Tips</h3>
          <ul class="tips">${s.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
          <h3 style="margin-top:18px">You'll be scored on</h3>
          <div class="tags" style="margin-bottom:20px">${s.skills.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div>
          <button class="btn btn-primary" id="start" style="width:100%">Start conversation</button>
          <p class="small muted" id="start-err" style="margin:10px 0 0"></p>
        </div>
      </aside>
    </div>`;
  const decodeBtn = document.getElementById("decode-btn");
  decodeBtn.addEventListener("click", () => {
    decodeBtn.hidden = true;
    loadDecode(s.id, document.getElementById("decode-body"));
  });
  const btn = document.getElementById("start");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Starting…";
    try {
      await startSession(s.id);
    } catch (err) {
      document.getElementById("start-err").textContent = err.message;
      btn.disabled = false;
      btn.textContent = "Start conversation";
    }
  });
}

const decodeCache = {};

async function loadDecode(scenarioId, el) {
  el.innerHTML = decodeCache[scenarioId]
    ? ""
    : `<div class="decode-loading"><div class="typing"><span></span><span></span><span></span></div>
       <span class="small muted">Reading SkillSim's notes on this situation… (the first time takes about 10 seconds)</span></div>`;
  try {
    decodeCache[scenarioId] ||= await api(`/scenarios/${encodeURIComponent(scenarioId)}/decode`);
    el.innerHTML = decodeHtml(decodeCache[scenarioId], scenarioId);
  } catch (err) {
    el.innerHTML = `<div class="notice error">${esc(err.message)}</div>`;
  }
}

function decodeHtml(d, scenarioId) {
  const list = (items) => `<ul class="tips">${items.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`;
  return `
    <div class="decode">
      <div class="decode-block">
        <div class="eyebrow">Workplace language</div>
        ${d.phrases
          .map(
            (p) => `<div class="phrase"><div class="phrase-term">“${esc(p.phrase)}”</div>
              <div class="small">${p.possible_meanings.length > 1 ? "Could mean:" : "Usually means:"}</div>
              ${list(p.possible_meanings)}
              <div class="small muted"><strong>Depends on:</strong> ${esc(p.depends_on)}</div></div>`
          )
          .join("")}
      </div>
      <div class="decode-block"><div class="eyebrow">Power &amp; relationship dynamics</div>${list(d.dynamics)}</div>
      <div class="decode-block"><div class="eyebrow">What you can't know yet</div>${list(d.uncertainties)}</div>
      <div class="decode-block"><div class="eyebrow">Questions you could ask</div>
        <ul class="tips questions">${d.clarifying_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul></div>
      <p class="basis small">${mockTag(d.source)} ${esc(d.basis)}${
        state.health?.dev_tools ? ` · <a href="#/trace/decode-${esc(scenarioId)}">trace</a>` : ""}</p>
    </div>`;
}

function roleCard(label, role, isYou) {
  return `
    <div class="role">
      <div class="role-label">${esc(label)}</div>
      <div class="role-head" style="margin-top:10px">
        <div class="avatar ${isYou ? "you" : ""}">${isYou ? "You" : esc(initials(role.name))}</div>
        <div><strong>${esc(role.name)}</strong><div class="small muted">${esc(role.title)}</div></div>
      </div>
      <p class="small muted" style="margin:0">${esc(role.description)}</p>
    </div>`;
}

function messageHtml(m, scenario) {
  const isUser = m.role === "user";
  const av = isUser ? `<div class="avatar you">You</div>` : `<div class="avatar">${esc(initials(scenario.ai_role.name))}</div>`;
  const meta = isUser ? "" : `<div class="bubble-meta">${mockTag(m.source)}</div>`;
  return `<div class="msg ${isUser ? "user" : "ai"}">${av}<div><div class="bubble">${esc(m.text)}</div>${meta}</div></div>`;
}

async function renderChat(id) {
  setNav(null);
  let session = await api(`/sessions/${encodeURIComponent(id)}`);
  const scenario = await api(`/scenarios/${encodeURIComponent(session.scenario_id)}`);
  const { max_user_turns: maxTurns, max_message_chars: maxChars } = session.limits;
  const ended = session.status === "ended";
  const expired = session.status === "expired";

  app.innerHTML = `
    <div class="chat-layout">
      <aside class="card brief sticky">
        <div class="block"><div class="eyebrow">Scenario</div><h3>${esc(scenario.title)}</h3>
          <div class="small muted">Attempt ${session.attempt}</div></div>
        ${session.retry_challenge ? `<div class="block challenge-mini"><div class="eyebrow">Your challenge this attempt</div><p style="margin:0">${esc(session.retry_challenge)}</p></div>` : ""}
        <div class="block"><div class="eyebrow">Objective</div><p class="muted" style="margin:0">${esc(scenario.objective)}</p></div>
        <div class="block"><button class="btn btn-secondary" id="decode-open" style="width:100%">Decode this situation</button></div>
        <div class="block"><div class="eyebrow">Tips</div><ul class="tips small">${scenario.tips.map((t) => `<li>${esc(t)}</li>`).join("")}</ul></div>
        <div class="block small muted">Turns used: <strong class="turns" id="turns"></strong></div>
      </aside>
      <section class="card chat">
        <div class="chat-head">
          <div class="avatar">${esc(initials(scenario.ai_role.name))}</div>
          <div class="who"><strong>${esc(scenario.ai_role.name)}</strong><span class="small muted">${esc(scenario.ai_role.title)}</span></div>
          ${
            ended
              ? `<a class="btn btn-primary" href="#/session/${esc(session.id)}/feedback">View feedback</a>`
              : `<button class="btn btn-secondary" id="end">End <span class="long">&amp; get feedback</span></button>`
          }
        </div>
        <details class="mobile-brief"><summary>Objective</summary><p>${esc(scenario.objective)}</p>
          ${session.retry_challenge ? `<p><strong>Your challenge:</strong> ${esc(session.retry_challenge)}</p>` : ""}</details>
        <div class="messages" id="messages" aria-live="polite"></div>
        <div class="composer">
          ${
            ended
              ? `<div class="notice">This conversation has ended. <a href="#/session/${esc(session.id)}/feedback">See your feedback</a>.</div>`
              : `<form id="composer">
                  <textarea id="input" rows="1" maxlength="${maxChars}" placeholder="Type your response…" aria-label="Your response"></textarea>
                  <button class="btn btn-primary" id="send" type="submit">Send</button>
                </form>
                <div class="composer-foot"><span id="hint">Enter to send · Shift+Enter for a new line</span><span id="count">0/${maxChars}</span></div>`
          }
        </div>
      </section>
    </div>`;

  document.getElementById("decode-open").addEventListener("click", () => openDrawer(scenario));
  const list = document.getElementById("messages");
  const turnsEl = document.getElementById("turns");
  const draw = (pending = false) => {
    list.innerHTML =
      session.messages.map((m) => messageHtml(m, scenario)).join("") +
      (pending
        ? `<div class="msg ai"><div class="avatar">${esc(initials(scenario.ai_role.name))}</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div></div>`
        : "");
    list.scrollTop = list.scrollHeight;
    const used = session.messages.filter((m) => m.role === "user").length;
    turnsEl.textContent = `${used} / ${maxTurns}`;
    return used;
  };
  draw();
  if (ended) return;
  if (expired) {
    document.getElementById("input").disabled = document.getElementById("send").disabled = true;
    document.getElementById("hint").textContent = "This session timed out. End it to get feedback, or retry from the scenario page.";
  }

  const form = document.getElementById("composer");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const count = document.getElementById("count");
  const hint = document.getElementById("hint");
  const endBtn = document.getElementById("end");

  const autosize = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    count.textContent = `${input.value.length}/${maxChars}`;
  };
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.focus();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    send.disabled = input.disabled = true;
    session.messages.push({ role: "user", text });
    input.value = "";
    autosize();
    draw(true);
    try {
      session = await api(`/sessions/${session.id}/messages`, { method: "POST", body: { text } });
      hint.textContent = "Enter to send · Shift+Enter for a new line";
    } catch (err) {
      session.messages.pop();
      input.value = text;
      autosize();
      hint.innerHTML = `<span style="color:#9b2c2c">${esc(err.message)}</span>`;
      if (err.status === 410) session.status = "expired";
    }
    const used = draw();
    send.disabled = input.disabled = used >= maxTurns || session.status === "expired";
    if (used >= maxTurns) hint.textContent = "Turn limit reached. End the conversation to see your feedback.";
    else input.focus();
  });

  endBtn.addEventListener("click", async () => {
    endBtn.disabled = send.disabled = input.disabled = true;
    endBtn.textContent = "Scoring…";
    try {
      await api(`/sessions/${session.id}/end`, { method: "POST" });
      go(`#/session/${session.id}/feedback`);
    } catch (err) {
      hint.innerHTML = `<span style="color:#9b2c2c">${esc(err.message)}</span>`;
      endBtn.disabled = send.disabled = input.disabled = false;
      endBtn.innerHTML = `End <span class="long">&amp; get feedback</span>`;
    }
  });
}

function openDrawer(scenario) {
  document.querySelector(".drawer-wrap")?.remove();
  const wrap = document.createElement("div");
  wrap.className = "drawer-wrap";
  wrap.innerHTML = `<div class="drawer-backdrop"></div>
    <aside class="drawer" role="dialog" aria-label="Decode this situation">
      <div class="drawer-head"><h3 style="margin:0">Decode: ${esc(scenario.title)}</h3>
        <button class="btn btn-ghost" id="drawer-close" aria-label="Close">✕</button></div>
      <div id="drawer-body"></div></aside>`;
  document.body.appendChild(wrap);
  const close = () => wrap.remove();
  wrap.querySelector(".drawer-backdrop").addEventListener("click", close);
  wrap.querySelector("#drawer-close").addEventListener("click", close);
  window.addEventListener("hashchange", close, { once: true });
  loadDecode(scenario.id, wrap.querySelector("#drawer-body"));
}

async function renderFeedback(id) {
  setNav(null);
  const session = await api(`/sessions/${encodeURIComponent(id)}`);
  if (!session.feedback) return go(`#/session/${session.id}`);
  const scenario = await api(`/scenarios/${encodeURIComponent(session.scenario_id)}`);
  const fb = normalizeFeedback(session.feedback);
  const quote = (q) => (q ? `<blockquote class="you-said"><span>You said</span>“${esc(q)}”</blockquote>` : "");

  app.innerHTML = `
    <a class="back" href="#/scenarios">← All scenarios</a>
    <div class="card fb-top">
      <div class="ring" style="--val:${fb.overall}"><div><div><strong>${fb.overall}</strong><span>skill check</span></div></div></div>
      <div>
        <div class="eyebrow">${esc(scenario.title)} · Attempt ${session.attempt} ${mockTag(fb.source)}</div>
        <h2 class="fb-label">What happened</h2>
        <p class="what-happened">${esc(fb.what_happened)}</p>
        <p class="muted small">${fb.stats.user_turns} turns · ${fb.stats.questions_asked} questions asked</p>
        <div class="btn-row">
          <button class="btn btn-primary" id="retry">Retry with your challenge</button>
          ${session.retry_of ? `<a class="btn btn-secondary" href="#/compare/${esc(session.retry_of)}/${esc(session.id)}">Compare with previous attempt</a>` : ""}
          <a class="btn btn-ghost" href="#/scenarios">Try another scenario</a>
        </div>
      </div>
    </div>

    <div class="fb-grid">
      <div style="display:grid;gap:24px">
        <section class="card card-pad">
          <div class="fb-num">1</div><h3>What worked</h3>
          ${fb.effective.length
            ? fb.effective.map((e) => `<div class="fb-item"><p>${esc(e.behavior)}</p>${quote(e.quote)}</div>`).join("")
            : `<p class="muted">No clear examples to point to in this attempt. That's normal on a first try.</p>`}
        </section>
        <section class="card card-pad">
          <div class="fb-num">2</div><h3>One communication opportunity</h3>
          ${quote(fb.opportunity.moment_quote)}
          <p>${esc(fb.opportunity.description)}</p>
        </section>
        ${fb.interpretation.possibility ? `<section class="card card-pad">
          <div class="fb-num">3</div><h3>How it might have landed <span class="possibility-tag">A possibility, not a fact</span></h3>
          ${quote(fb.interpretation.quote)}
          <p>${esc(fb.interpretation.possibility)}</p>
        </section>` : ""}
      </div>
      <div style="display:grid;gap:24px;align-content:start">
        ${fb.alternative.response ? `<section class="card card-pad">
          <div class="fb-num">4</div><h3>One alternative</h3>
          <p class="quote">“${esc(fb.alternative.response)}”</p>
          <p class="small"><span class="tag">${esc(fb.alternative.style)}</span> ${esc(fb.alternative.why)}</p>
          <p class="small muted" style="margin:0">One option among many. Other styles, more direct or more reserved, can work too.</p>
        </section>` : ""}
        <section class="challenge">
          <div class="eyebrow">Your challenge for the retry</div>
          <p>${esc(fb.retry_challenge)}</p>
        </section>
        <section class="card card-pad">
          <h3>Skill check</h3>
          ${fb.skills
            .map(
              (k) => `<div class="skill">
                <div class="skill-row"><span>${esc(k.name)}</span><span>${k.score}/5</span></div>
                <div class="bar"><div style="width:${k.score * 20}%"></div></div>
                <div class="small muted" style="margin-top:6px">${esc(k.note)}</div>
              </div>`
            )
            .join("")}
        </section>
      </div>
    </div>
    <div class="card card-pad" style="margin-top:24px">
      <details class="transcript">
        <summary>View transcript (${session.messages.length} messages)</summary>
        <div class="messages">${session.messages.map((m) => messageHtml(m, scenario)).join("")}</div>
      </details>
    </div>`;

  const retry = document.getElementById("retry");
  retry.addEventListener("click", async () => {
    retry.disabled = true;
    retry.textContent = "Starting…";
    try {
      await startSession(session.scenario_id, session.id);
    } catch (err) {
      retry.disabled = false;
      retry.textContent = err.message;
    }
  });
}

// Sessions saved before the six-part feedback format still render.
function normalizeFeedback(old) {
  return {
    what_happened: old.headline || "",
    retry_challenge: (old.improvements || [])[0] || "",
    ...old,
    effective: old.effective || [],
    opportunity: old.opportunity || { moment_quote: "", description: (old.improvements || [])[1] || "" },
    interpretation: old.interpretation || { quote: "", possibility: "" },
    alternative: old.alternative || { response: old.try_saying || "", style: "", why: "" },
  };
}

async function renderCompare(firstId, secondId) {
  setNav("history");
  const [a, b] = await Promise.all([api(`/sessions/${encodeURIComponent(firstId)}`), api(`/sessions/${encodeURIComponent(secondId)}`)]);
  const scenario = await api(`/scenarios/${encodeURIComponent(a.scenario_id)}`);
  const turns = (s) => s.messages.filter((m) => m.role === "user").map((m) => m.text);
  const ta = turns(a), tb = turns(b);
  const rows = Array.from({ length: Math.max(ta.length, tb.length) }, (_, i) => `
    <div class="cmp-row">
      <div class="cmp-turn">Response ${i + 1}</div>
      <div class="cmp-cell">${ta[i] ? esc(ta[i]) : `<span class="muted">—</span>`}</div>
      <div class="cmp-cell">${tb[i] ? esc(tb[i]) : `<span class="muted">—</span>`}</div>
    </div>`).join("");
  const scoreOf = (s, name) => s.feedback?.skills.find((k) => k.name === name)?.score;
  const skillRows = scenario.skills.map((name) => {
    const x = scoreOf(a, name), y = scoreOf(b, name);
    const delta = x != null && y != null ? y - x : null;
    return `<tr><td>${esc(name)}</td><td class="num">${x ?? "—"}</td><td class="num">${y ?? "—"}</td>
      <td class="num ${delta > 0 ? "up" : delta < 0 ? "down" : ""}">${delta == null ? "" : delta > 0 ? `+${delta}` : delta}</td></tr>`;
  }).join("");

  app.innerHTML = `
    <a class="back" href="#/session/${esc(b.id)}/feedback">← Back to feedback</a>
    <div class="eyebrow">${esc(scenario.title)}</div>
    <h1 style="font-size:2rem">Attempt ${a.attempt} vs. attempt ${b.attempt}</h1>
    ${b.retry_challenge ? `<div class="challenge" style="margin-bottom:24px"><div class="eyebrow">The challenge you set for attempt ${b.attempt}</div><p>${esc(b.retry_challenge)}</p></div>` : ""}
    <div class="cmp-grid">
      <div class="card card-pad">
        <div class="cmp-head"><div></div><div><strong>Attempt ${a.attempt}</strong><span class="small muted"> · ${a.feedback ? a.feedback.overall : "not finished"}</span></div>
          <div><strong>Attempt ${b.attempt}</strong><span class="small muted"> · ${b.feedback ? b.feedback.overall : "not finished"}</span></div></div>
        ${rows}
      </div>
      <div class="card table-wrap">
        <table><thead><tr><th>Skill</th><th class="num">#${a.attempt}</th><th class="num">#${b.attempt}</th><th class="num">Change</th></tr></thead>
        <tbody>${skillRows}</tbody></table>
      </div>
    </div>
    <div class="grid-2" style="margin-top:24px">
      <div class="card card-pad"><div class="eyebrow">Attempt ${a.attempt}: what happened</div><p class="muted">${esc(a.feedback ? normalizeFeedback(a.feedback).what_happened : "No feedback yet.")}</p></div>
      <div class="card card-pad"><div class="eyebrow">Attempt ${b.attempt}: what happened</div><p class="muted">${esc(b.feedback ? normalizeFeedback(b.feedback).what_happened : "No feedback yet.")}</p></div>
    </div>`;
}

async function renderHistory(tab) {
  setNav("history");
  const tabs = `
    <div class="tabs" role="tablist">
      <a href="#/history" class="${tab === "history" ? "active" : ""}" role="tab">Session history</a>
      ${state.health?.dev_tools ? `<a href="#/metrics" class="${tab === "metrics" ? "active" : ""}" role="tab">Developer metrics</a>` : ""}
    </div>`;

  if (tab === "history") {
    const sessions = await api("/sessions");
    app.innerHTML = `
      <div class="page-head"><div><div class="eyebrow">History</div><h1 style="font-size:2.2rem">Your practice sessions</h1></div>
        ${sessions.length ? `<button class="btn btn-ghost" id="delete-history">Delete my history</button>` : ""}</div>
      <p class="small muted">Your conversations are stored on this server and shown only to this browser.</p>
      ${tabs}
      ${
        sessions.length
          ? `<div class="card table-wrap"><table>
              <thead><tr><th>Scenario</th><th>Attempt</th><th>Started</th><th class="num">Turns</th><th class="num">Score</th><th>Status</th><th></th></tr></thead>
              <tbody>${sessions
                .map((s) => {
                  const turns = s.messages.filter((m) => m.role === "user").length;
                  const link = s.feedback ? `#/session/${s.id}/feedback` : `#/session/${s.id}`;
                  return `<tr>
                    <td><strong>${esc(s.scenario_title)}</strong></td>
                    <td>#${s.attempt}${s.retry_of ? ` <a class="small" href="#/compare/${esc(s.retry_of)}/${esc(s.id)}">compare</a>` : ""}</td>
                    <td class="muted">${fmtDate(s.started_at)}</td>
                    <td class="num">${turns}</td>
                    <td class="num">${s.feedback ? s.feedback.overall : "—"}</td>
                    <td><span class="status ${s.status}">${{ ended: "Completed", expired: "Timed out", active: "In progress" }[s.status] || esc(s.status)}</span></td>
                    <td><a href="${link}">${s.feedback ? "Feedback" : "Resume"} →</a></td></tr>`;
                })
                .join("")}</tbody></table></div>`
          : `<div class="card empty"><h3>No sessions yet</h3><p>Your practice history will show up here.</p>
              <a class="btn btn-primary" href="#/scenarios">Start your first scenario</a></div>`
      }`;
    document.getElementById("delete-history")?.addEventListener("click", async () => {
      if (!confirm("Permanently delete all of your practice conversations and feedback?")) return;
      await api("/sessions", { method: "DELETE" });
      renderHistory("history");
    });
    return;
  }

  if (!state.health?.dev_tools) {
    app.innerHTML = `${tabs}<div class="card empty"><p>Developer tools are disabled on this server.</p></div>`;
    return;
  }
  const spm = Number(sessionStorage.getItem("spm")) || 8;
  const [d, m] = await Promise.all([api(`/dev/usage?sessions_per_month=${spm}`), api("/metrics")]);
  const M = d.measured, P = d.projected, sum = M.simulation_summary;
  const price = Object.entries(d.pricing.models)[0];
  const tok = (n) => (n == null ? `<span class="na">unavailable</span>` : fmtInt(n));
  const usd = (n) => (n == null ? `<span class="na">unavailable</span>` : fmtUsd(n));
  const agg = (label, a, extra = "") => `<tr><td><strong>${esc(label)}</strong>${extra}</td><td class="num">${a.requests}</td>
      <td class="num">${a.failed_requests || ""}</td><td class="num">${tok(a.input_tokens)}</td><td class="num">${tok(a.cached_input_tokens)}</td>
      <td class="num">${tok(a.output_tokens)}</td><td class="num">${a.tool_calls}</td><td class="num">${usd(a.cost_usd)}</td>
      <td class="num">${a.avg_latency_ms == null ? "—" : fmtInt(a.avg_latency_ms) + " ms"}</td>
      <td class="num">${a.gateway_cache_hits || ""}${a.gateway_cache_unknown ? ` <span class="na">(${a.gateway_cache_unknown} unknown)</span>` : ""}</td></tr>`;
  const aggHead = (first) => `<thead><tr><th>${first}</th><th class="num">Requests</th><th class="num">Failed</th><th class="num">Input</th>
      <th class="num">Cached input</th><th class="num">Output</th><th class="num">Tool calls</th><th class="num">Cost</th><th class="num">Avg latency</th><th class="num">Gateway cache hits</th></tr></thead>`;
  const mean = (x) => (x ? x.mean : null);
  const variants = Object.keys(M.by_variant);
  const change = (a, b) => (a && b != null ? `${b >= a ? "+" : ""}${((100 * (b - a)) / a).toFixed(1)}%` : "");

  app.innerHTML = `
    <div class="page-head">
      <div><div class="eyebrow">Developer</div><h1 style="font-size:2.2rem">Tokens &amp; cost</h1></div>
      <div class="btn-row">
        <a class="btn btn-secondary" href="/api/dev/export/simulations.csv">Simulations CSV</a>
        <a class="btn btn-secondary" href="/api/dev/export/requests.csv">Requests CSV</a>
      </div>
    </div>
    ${tabs}
    <div class="card card-pad pricing-card small">
      <strong>${esc(price[0])}</strong> · $${price[1].input} input · $${price[1].output} output · cached input:
      ${price[1].cached_input == null ? "<em>rate not published, billed at input rate (costs are an upper bound)</em>" : "$" + price[1].cached_input}
      · ${esc(d.pricing.units)}<br><span class="muted">Source: ${esc(price[1].source)} · as of ${esc(price[1].as_of)} · ${esc(price[1].verified)}</span>
    </div>

    <section class="dash-section">
      <h2 class="dash-title"><span class="badge measured">Measured</span> From API usage data, one row per request</h2>
      ${M.summary_basis ? `<p class="small muted">${esc(M.summary_basis)} Portkey's response cache can replay identical requests (status HIT) with their original usage numbers; those are shown but never averaged.</p>` : ""}
      ${sum.runs ? `<div class="stats">
        ${stat("Real full simulations", fmtInt(sum.runs), "conversation + feedback, live model")}
        ${stat("Cost per simulation", fmtUsd(sum.cost_usd.mean), `mean · median ${fmtUsd(sum.cost_usd.median)} · p90 ${fmtUsd(sum.cost_usd.p90)}`)}
        ${stat("Input tokens / simulation", fmtInt(sum.input_tokens.mean), sum.cached_input_tokens ? `${fmtInt(sum.cached_input_tokens.mean)} cached (mean)` : "cached: unavailable")}
        ${stat("Output tokens / simulation", fmtInt(sum.output_tokens.mean), `${sum.requests.mean.toFixed(1)} requests · ${sum.user_turns.mean.toFixed(1)} user turns (mean)`)}
      </div>` : `<div class="notice" style="margin-bottom:20px">No completed live simulations in the ledger yet.</div>`}

      <h3>Tokens by agent</h3>
      <div class="card table-wrap"><table>${aggHead("Agent")}<tbody>
        ${Object.entries(M.by_agent).map(([k, a]) => agg(k, a)).join("")}
        ${agg("All requests", M.all_requests)}</tbody></table></div>

      <h3>Tokens by operation</h3>
      <div class="card table-wrap"><table>${aggHead("Operation")}<tbody>
        ${Object.entries(M.by_operation).map(([k, a]) => agg(k, a)).join("")}</tbody></table></div>

      ${variants.length > 1 ? `<h3>Baseline vs. optimized context <span class="small muted">(per full simulation, mean of measured runs)</span></h3>
      <div class="card table-wrap"><table>
        <thead><tr><th>Variant</th><th class="num">Runs</th><th class="num">Requests</th><th class="num">Input</th><th class="num">Cached input</th>
          <th class="num">Output</th><th class="num">Cost</th><th class="num">Quality (of 5)</th></tr></thead>
        <tbody>${variants.map((v) => { const x = M.by_variant[v]; return `<tr><td><strong>${esc(v)}</strong></td><td class="num">${x.runs}</td>
          <td class="num">${mean(x.requests)?.toFixed(1)}</td><td class="num">${fmtInt(mean(x.input_tokens))}</td><td class="num">${tok(mean(x.cached_input_tokens))}</td>
          <td class="num">${fmtInt(mean(x.output_tokens))}</td><td class="num">${fmtUsd(mean(x.cost_usd))}</td><td class="num">${mean(x.quality_score)?.toFixed(2)}</td></tr>`; }).join("")}
        ${M.by_variant.baseline && M.by_variant.optimized ? (() => { const b = M.by_variant.baseline, o = M.by_variant.optimized; return `<tr class="delta-row"><td>Change</td><td></td>
          <td class="num">${change(mean(b.requests), mean(o.requests))}</td><td class="num">${change(mean(b.input_tokens), mean(o.input_tokens))}</td>
          <td class="num">${change(mean(b.cached_input_tokens), mean(o.cached_input_tokens))}</td><td class="num">${change(mean(b.output_tokens), mean(o.output_tokens))}</td>
          <td class="num">${change(mean(b.cost_usd), mean(o.cost_usd))}</td><td class="num">${change(mean(b.quality_score), mean(o.quality_score))}</td></tr>`; })() : ""}
        </tbody></table></div>
      <p class="small muted">Quality rubric (1 point each): ${Object.entries(d.quality_rubric).map(([k, v]) => `<strong>${esc(k.replace(/_/g, " "))}</strong>: ${esc(v)}`).join(" · ")}</p>` : ""}

      <h3>Full simulations <span class="small muted">(each row: every request in one session)</span></h3>
      <div class="card table-wrap"><table>
        <thead><tr><th>Session</th><th>Scenario</th><th>Variant</th><th class="num">Turns</th><th class="num">Requests</th><th class="num">Input</th>
          <th class="num">Cached</th><th class="num">Output</th><th class="num">Cost</th><th class="num">Quality</th><th class="num">Feedback score</th><th>In averages</th></tr></thead>
        <tbody>${M.simulations.map((x) => `<tr>
          <td><a href="#/trace/${esc(x.session_id)}"><code>${esc(x.session_id)}</code></a></td><td>${esc(x.scenario_id)}</td><td>${esc(x.variant)}${x.run_tag ? ` <span class="tag">${esc(x.run_tag)}</span>` : ""}</td>
          <td class="num">${x.user_turns}</td><td class="num">${x.requests}</td><td class="num">${tok(x.input_tokens)}</td><td class="num">${tok(x.cached_input_tokens)}</td>
          <td class="num">${tok(x.output_tokens)}</td><td class="num">${usd(x.cost_usd)}</td>
          <td class="num" title="${esc(Object.entries(x.quality.checks).filter(([, v]) => !v).map(([k]) => k).join(", ") || "all checks passed")}">${x.quality.score}/${x.quality.max}</td>
          <td class="num">${x.feedback_score ?? "—"}</td>
          <td class="small">${x.fresh ? "yes" : `<span class="na">no: ${x.gateway_cache_hits ? `${x.gateway_cache_hits} gateway cache hits` : "cache status not recorded"}</span>`}</td></tr>`).join("") || `<tr><td colspan="12" class="muted">None yet.</td></tr>`}</tbody></table></div>

      <h3>Decode This Situation <span class="small muted">(generated once per scenario, then cached)</span></h3>
      <div class="card table-wrap"><table>${aggHead("")}<tbody>${agg("All decode requests", M.decode)}</tbody></table></div>

      <h3>Latest requests</h3>
      <div class="card table-wrap"><table>
        <thead><tr><th>Time</th><th>Session</th><th>Agent</th><th>Operation</th><th class="num">Try</th><th class="num">Input</th><th class="num">Cached</th>
          <th class="num">Output</th><th class="num">Latency</th><th class="num">Cost</th><th>Gateway cache</th><th>Tool calls</th><th>Error</th></tr></thead>
        <tbody>${M.requests.slice(0, 60).map((r) => `<tr class="${r.error ? "row-error" : ""}">
          <td class="muted">${new Date(r.ts * 1000).toLocaleTimeString()}</td><td><code>${esc(r.session_id || r.scenario_id || "")}</code></td>
          <td>${esc(r.agent)}</td><td>${esc(r.operation)}</td><td class="num">${r.attempt}</td>
          <td class="num">${tok(r.input_tokens)}</td><td class="num">${tok(r.cached_input_tokens)}</td><td class="num">${tok(r.output_tokens)}</td>
          <td class="num">${fmtInt(r.latency_ms)} ms</td><td class="num">${usd(r.cost_usd)}</td>
          <td class="small">${r.gateway_cache ? esc(r.gateway_cache) : `<span class="na">unavailable</span>`}</td>
          <td class="small">${esc((r.tool_calls || []).join(", "))}</td><td class="small">${esc(r.error || "")}</td></tr>`).join("") || `<tr><td colspan="13" class="muted">No requests logged yet.</td></tr>`}</tbody></table></div>
    </section>

    <section class="dash-section projection">
      <h2 class="dash-title"><span class="badge projected">Projection</span> Measured averages × stated assumptions, not measurements</h2>
      ${P ? `
      <label class="small spm">Practice sessions per user per month
        <input type="number" id="spm" min="1" max="1000" step="1" value="${P.sessions_per_user_month}"></label>
      <div class="stats">
        ${stat("Per user / month", fmtUsd(P.per_user_month.mean), `high estimate ${fmtUsd(P.per_user_month.high)}`)}
        ${stat("100 users / month", fmtUsd(P.users_100.mean), `high estimate ${fmtUsd(P.users_100.high)}`)}
        ${stat("10,000 users / month", fmtUsd(P.users_10000.mean), `high estimate ${fmtUsd(P.users_10000.high)}`)}
        ${stat("Sessions / month at 10k users", fmtInt(10000 * P.sessions_per_user_month), "assumed")}
      </div>
      <div class="card card-pad"><h3>Assumptions</h3><ul class="tips">${P.assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div>`
      : `<div class="notice">Run at least one full live simulation to project costs.</div>`}
    </section>

    <div class="card card-pad budget">
      <div class="budget-head"><h3 style="margin:0">Today's spend guard</h3>
        <span class="small muted">${fmtInt(m.budgets.today.calls)} model calls today (UTC)</span></div>
      ${meter("Tokens", m.budgets.today.tokens, m.budgets.daily_token_budget, fmtInt)}
      ${meter("Cost", m.budgets.today.cost_usd, m.budgets.daily_cost_budget_usd, fmtUsd)}
      <p class="small muted" style="margin:8px 0 0">Each session is also capped at ${fmtInt(m.budgets.session_token_budget)} tokens. New model calls are refused once a cap is reached.</p>
    </div>`;
  document.getElementById("spm")?.addEventListener("change", (e) => {
    const v = Math.min(1000, Math.max(1, Number(e.target.value) || 8));
    sessionStorage.setItem("spm", v);
    renderHistory("metrics");
  });
}

function meter(label, used, cap, fmt) {
  const pct = cap ? Math.min(100, (100 * used) / cap) : 0;
  return `<div class="meter"><div class="skill-row small"><span>${label}</span><span>${fmt(used)} of ${fmt(cap)}</span></div>
    <div class="bar"><div style="width:${pct}%"></div></div></div>`;
}

async function renderTrace(id) {
  setNav("history");
  const t = id.startsWith("decode-")
    ? await api(`/dev/decode/${encodeURIComponent(id.slice(7))}/trace`)
    : await api(`/dev/sessions/${encodeURIComponent(id)}/trace`);
  const t0 = t.trace[0]?.ts || 0;
  const row = (e) => {
    const d = e.detail;
    let body;
    if (e.event === "model_call" && d.usage)
      body = `${d.operation ? `<span class="tag">${esc(d.operation)}</span> ` : ""}${fmtInt(d.usage.input_tokens)} in (${d.usage.cached_input_tokens == null ? "cached: unavailable" : fmtInt(d.usage.cached_input_tokens) + " cached"}) · ${fmtInt(d.usage.output_tokens)} out · ${fmtInt(d.latency_ms)} ms${d.attempt > 1 ? ` · attempt ${d.attempt}` : ""}`;
    else if (e.event === "tool_call") body = `<code>${esc(d.tool)}(${esc(JSON.stringify(d.args))})</code>`;
    else if (e.event === "tool_result") body = `<span class="trace-result">${esc(d.result)}</span>`;
    else body = `<code>${esc(JSON.stringify(d))}</code>`;
    return `<tr class="ev-${esc(e.event)}"><td class="num muted">+${((e.ts - t0) || 0).toFixed(1)}s</td>
      <td><span class="tag">${esc(e.agent)}</span></td><td><strong>${esc(e.event.replace(/_/g, " "))}</strong></td><td class="wrap-cell">${body}</td></tr>`;
  };
  app.innerHTML = `
    <a class="back" href="#/metrics">← Metrics</a>
    <div class="page-head"><div><div class="eyebrow">Developer trace</div>
      <h1 style="font-size:2rem">${esc(t.scenario_title)} #${t.attempt}</h1></div>
      <div class="small muted">Session <code>${esc(t.id)}</code> · ${esc(t.engine)} · ${esc(t.model || "")} · ${fmtInt(t.tokens_used)} tokens</div></div>
    <p class="muted small">Every model call, real tool call and result, retry, and guardrail event for this session, as logged by the server.</p>
    ${t.trace.length ? `<div class="card table-wrap"><table class="trace">
      <thead><tr><th class="num">Time</th><th>Agent</th><th>Event</th><th>Detail</th></tr></thead>
      <tbody>${t.trace.map(row).join("")}</tbody></table></div>`
      : `<div class="card empty"><p>No events logged for this session.</p></div>`}`;
}

function stat(label, value, sub, tag = "") {
  return `<div class="card stat"><div class="label">${esc(label)} ${tag}</div><div class="value">${value}</div><div class="sub">${esc(sub)}</div></div>`;
}

// ---------- router ----------

const routes = [
  [/^#?\/?$/, () => renderHome()],
  [/^#\/scenarios$/, () => renderScenarios()],
  [/^#\/scenarios\/([\w-]+)$/, (id) => renderIntro(id)],
  [/^#\/session\/(\w+)$/, (id) => renderChat(id)],
  [/^#\/session\/(\w+)\/feedback$/, (id) => renderFeedback(id)],
  [/^#\/history$/, () => renderHistory("history")],
  [/^#\/metrics$/, () => renderHistory("metrics")],
  [/^#\/trace\/([\w-]+)$/, (id) => renderTrace(id)],
  [/^#\/compare\/(\w+)\/(\w+)$/, (a, b) => renderCompare(a, b)],
];

async function router() {
  const hash = location.hash || "#/";
  window.scrollTo(0, 0);
  for (const [re, fn] of routes) {
    const match = hash.match(re);
    if (match) {
      app.innerHTML = `<div class="loading">Loading…</div>`;
      try {
        await fn(...match.slice(1));
      } catch (err) {
        app.innerHTML = `<div class="card empty"><h3>Something went wrong</h3><p>${esc(err.message)}</p><a class="btn btn-secondary" href="#/">Back to home</a></div>`;
      }
      return;
    }
  }
  app.innerHTML = `<div class="card empty"><h3>Page not found</h3><a class="btn btn-secondary" href="#/">Back to home</a></div>`;
}

async function init() {
  try {
    state.health = await api("/health");
    const pill = document.getElementById("engine-pill");
    if (state.health.engine === "mock") {
      pill.hidden = false;
    } else if (!state.health.ready) {
      pill.hidden = false;
      pill.className = "pill pill-error";
      pill.textContent = "AI not configured";
      pill.title = state.health.error || "";
    }
  } catch {
    /* the router will surface connection errors */
  }
  window.addEventListener("hashchange", router);
  router();
}

init();
