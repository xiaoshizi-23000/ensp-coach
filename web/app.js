const S = {
  labs: [], lab: null, stepId: null, progress: { done: [] },
  built: false, ai: false, hintLevel: 0, history: [], lastOutput: "", poll: null, busy: false,
  exam: { items: [] }, calibrated: false
};

const $ = (s) => document.querySelector(s);
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt != null) e.textContent = txt; return e; };
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function setTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("theme", t);
}
setTheme(localStorage.getItem("theme") || "apple");

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  };
  const r = await fetch(path, opt);
  return r.json();
}

function toast(t) {
  const n = $("#toast");
  n.textContent = t; n.classList.add("on");
  clearTimeout(n._t); n._t = setTimeout(() => n.classList.remove("on"), 2600);
}

function notice(html) {
  const n = $("#notice");
  if (!html) { n.classList.add("hidden"); n.innerHTML = ""; return; }
  n.innerHTML = html; n.classList.remove("hidden");
}

let clockTimer = null;

function pad2(n) { return String(n).padStart(2, "0"); }

function elapsed() {
  if (!S.labStart) return "";
  const s = Math.floor((Date.now() - S.labStart) / 1000);
  return `${pad2(Math.floor(s / 60))}:${pad2(s % 60)}`;
}

function syShort(s) {
  const t = String(s).replace(/（[^）]*）/g, "").replace(/\([^)]*\)/g, " ");
  const lv = (t.match(/HCIA|HCIP|HCIE/) || [""])[0];
  const num = (t.match(/\b\d+(\.\d+)?\b/) || [""])[0];
  return (lv + (num ? " " + num : "")) || String(s).slice(0, 12);
}

function renderMeta() {
  const box = $("#labMeta");
  if (!box || !S.lab) return;
  const done = (S.progress && S.progress.done) || [];
  const idx = S.lab.steps.findIndex((s) => s.id === S.stepId) + 1;
  box.innerHTML = "";
  (S.lab.tags || []).slice(0, 3).forEach((t) => box.appendChild(el("span", "chip hi", t)));
  if (S.lab.level) box.appendChild(el("span", "chip", S.lab.level));
  (S.lab.syllabus || []).slice(0, 2).forEach((s) => {
    const c = el("span", "chip sy", syShort(s));
    c.title = s;
    box.appendChild(c);
  });
  box.appendChild(el("span", "m", `第 ${idx || "-"}/${S.lab.steps.length} 步 · 已完成 ${done.length}`));
  const e = elapsed();
  if (e) box.appendChild(el("span", "m mono", "⏱ " + e));
}

function startClock() {
  if (clockTimer) clearInterval(clockTimer);
  clockTimer = setInterval(renderMeta, 1000);
  renderMeta();
}

function currentStep() {  if (!S.lab) return null;
  return S.lab.steps.find((s) => s.id === S.stepId) || null;
}

async function boot() {
  const r = await api("/api/labs");
  S.labs = r.labs || []; S.ai = !!r.ai; S.calibrated = !!r.calibrated;
  $("#aiDot").className = "dot " + (S.ai ? "on" : "off");
  $("#aiState").textContent = S.ai ? "DeepSeek 已连接" : "DeepSeek 未配置";
  renderLabs();
  loadExam();
  loadKbSide();
  if (S.labs.length) selectLab(S.labs[0].id);
}

async function loadKbSide() {
  const r = await api("/api/kb");
  if (!r.ok) return;
  S.kbCats = r.cats || [];
  const c = $("#kbCount");
  if (c) c.textContent = (r.items || []).length;
  renderKbSide();
}

function toggleSec(secSel, boxSel, key, force) {
  const sec = $(secSel), list = $(boxSel);
  if (!sec || !list) return;
  const closed = force !== undefined ? force : !sec.classList.contains("closed");
  sec.classList.toggle("closed", closed);
  list.classList.toggle("hidden", closed);
  localStorage.setItem(key, closed ? "1" : "");
}

function toggleLabs(force) {
  toggleSec("#secLabs", "#labList", "labsClosed", force);
}

function renderLabs() {
  const box = $("#labList");
  box.innerHTML = "";
  const cnt = $("#labCount");
  if (cnt) cnt.textContent = S.labs.length;
  S.labs.forEach((l) => {
    const d = el("div", "lab" + (S.lab && S.lab.id === l.id ? " on" : ""));
    const b = el("b", null, l.title);
    if (l.source === "ai") b.appendChild(el("span", "tag", "AI"));
    if (l.verified) b.appendChild(el("span", "tag ok", "已试跑"));
    d.appendChild(b);
    d.appendChild(el("span", null, l.subtitle));
    const m = el("div", "meta");
    m.appendChild(el("i", "lv " + l.level, l.level));
    m.appendChild(el("span", null, l.steps + " 步"));
    m.appendChild(el("span", null, "约 " + l.minutes + " 分钟"));
    d.appendChild(m);
    if (l.source === "ai") {
      const x = el("span", "del", "×");
      x.title = "删掉这个实验";
      x.onclick = (e) => delLab(l.id, e);
      d.appendChild(x);
    }
    d.onclick = () => selectLab(l.id);
    box.appendChild(d);
  });
  const cur = box.querySelector(".lab.on");
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

async function refreshLabs() {
  const r = await api("/api/labs");
  S.labs = r.labs || [];
  S.ai = !!r.ai;
  $("#aiDot").className = "dot " + (S.ai ? "on" : "off");
  $("#aiState").textContent = S.ai ? "DeepSeek 已连接" : "DeepSeek 未配置";
  renderLabs();
}

async function delLab(id, ev) {
  ev.stopPropagation();
  if (!confirm("删掉这个实验？生成的拓扑和进度会一起清掉。")) return;
  const r = await api("/api/lab/" + id + "/delete", {});
  if (!r.ok) return toast(r.error || "删除失败");
  const wasCurrent = S.lab && S.lab.id === id;
  S.lab = null;
  await refreshLabs();
  if (wasCurrent && S.labs.length) selectLab(S.labs[0].id);
  toast("已删除");
}

async function selectLab(id) {
  stopPoll();
  const r = await api("/api/lab/" + id);
  if (!r.ok) return toast(r.error || "加载失败");
  S.lab = r.lab;
  S.progress = r.progress || { done: [] };
  S.built = false;
  const first = S.lab.steps.find((s) => !S.progress.done.includes(s.id)) || S.lab.steps[0];
  S.stepId = first.id;
  S.hintLevel = 0;
  S.lastOutput = "";
  S.injected = false;
  S.labStart = Date.now();
  startClock();
  notice(null);
  $("#labTitle").textContent = S.lab.title;
  $("#labSub").textContent = S.lab.subtitle;
  localStorage.setItem("lab", id);
  $("#empty").classList.add("hidden");
  $("#stepCard").classList.remove("hidden");
  renderLabs(); renderStepper(); showStep(S.stepId);
  refreshStatus();
}

function renderStepper() {
  const box = $("#stepper");
  box.innerHTML = "";
  if (!S.lab) return;
  S.lab.steps.forEach((s, i) => {
    const d = el("div", "st");
    const done = S.progress.done.includes(s.id);
    if (done) d.classList.add("done");
    if (s.id === S.stepId) d.classList.add("on");
    d.appendChild(el("i", null, done ? "" : String(i + 1).padStart(2, "0")));
    d.appendChild(el("b", null, s.title));
    d.onclick = () => showStep(s.id);
    box.appendChild(d);
  });
  const p = S.lab.steps.length ? S.progress.done.length / S.lab.steps.length : 0;
  $("#bar").style.width = Math.round(p * 100) + "%";
}

function showStep(id) {
  S.stepId = id; S.hintLevel = 0;
  const s = currentStep();
  if (!s) return;
  const idx = S.lab.steps.findIndex((x) => x.id === id);
  $("#stepNo").textContent = String(idx + 1).padStart(2, "0");
  $("#stepTitle").textContent = s.title;
  $("#stepBrief").textContent = s.brief;
  $("#stepWhy").textContent = s.why || "";
  $("#hintBox").classList.add("hidden");
  $("#output").classList.add("hidden");
  $("#output").innerHTML = "";
  const sym = $("#symptom");
  if (sym) {
    if (S.lab.mode === "troubleshoot" && S.lab.symptom) {
      sym.textContent = S.lab.symptom;
      sym.classList.remove("hidden");
    } else {
      sym.classList.add("hidden");
    }
  }
  renderStepper();
  renderMeta();
}

function renderDevices(st) {
  const box = $("#devices");
  box.innerHTML = "";
  if (!st || !st.devices || !st.devices.length) {
    if (S.lab) {
      S.lab.devices.forEach((d) => {
        const n = el("div", "dev");
        n.appendChild(el("i", "d"));
        n.appendChild(el("span", null, d.name));
        n.appendChild(el("small", null, d.model));
        box.appendChild(n);
      });
    }
    return;
  }
  st.devices.forEach((d) => {
    const n = el("div", "dev" + (d.up ? " up" : ""));
    n.appendChild(el("i", "d"));
    n.appendChild(el("span", null, d.name));
    n.appendChild(el("small", null, d.port ? "console " + d.port : "无命令行"));
    box.appendChild(n);
  });
}

async function refreshStatus() {
  if (!S.lab) return;
  const st = await api("/api/lab/" + S.lab.id + "/status");
  S.built = !!st.built;
  renderDevices(st);
  if (st.built && st.total && st.up === st.total) notice(null);
  return st;
}

function startPoll() {
  stopPoll();
  let tick = 0;
  S.poll = setInterval(async () => {
    const st = await refreshStatus();
    tick++;
    if (st && st.total && st.up === st.total) {
      stopPoll();
      if (S.lab && S.lab.mode === "troubleshoot" && !S.injected) {
        api(`/api/lab/${S.lab.id}/inject`, {}).then((r) => {
          S.injected = true;
          toast(r.ok ? "环境已布置好，按现象开始排查" : (r.error || "故障注入没成功"));
        });
      } else {
        toast("设备都起来了，开始第一步吧");
      }
    }
    if (tick > 60) stopPoll();
  }, 4000);
}

function stopPoll() { if (S.poll) { clearInterval(S.poll); S.poll = null; } }

async function doBuild() {
  if (!S.lab || S.busy) return;
  S.busy = true; $("#btnBuild").disabled = true;
  toast("正在生成拓扑…");
  const r = await api("/api/lab/" + S.lab.id + "/build", {});
  S.busy = false; $("#btnBuild").disabled = false;
  if (!r.ok) return toast(r.error || "生成失败");
  if (r.opened) {
    if (S.calibrated) {
      notice("拓扑已经生成，正在自动去点「启动」。如果设备没起来，回 eNSP 手动点一下，再点下面的「校准启动按钮」重新记一次位置。");
    } else {
      notice("拓扑已经生成，eNSP 正在打开。在 eNSP 里点工具栏的 <b>启动</b>（或全选设备后右键启动），设备起来后上面的灯会变绿。<br>嫌每次都要点，就先用一次「校准启动按钮」，之后自动点。");
    }
  } else {
    const p = String(r.topo).replace(/</g, "&lt;");
    notice(`拓扑已生成：<code>${p}</code><br>eNSP 没有自动打开，用 eNSP 的 <b>文件 → 打开</b> 选它就行。右键这个 .topo 关联一次 eNSP，以后就能自动打开了。`);
  }
  renderDevices({ devices: r.devices });
  if (S.calibrated) {
    setTimeout(() => {
      api(`/api/lab/${S.lab.id}/start`, { click: true, wait: false }).then((s) => {
        if (!s.ok) toast(s.error || "自动点启动没成功，手动点一下");
      });
    }, 3500);
  }
  startPoll();
}

function renderCheck(r) {
  const box = $("#output");
  box.innerHTML = "";
  box.classList.remove("hidden");
  (r.results || []).forEach((x) => {
    const row = el("div", "res " + (x.pass ? "pass" : "fail"));
    row.appendChild(el("i", "ic", x.pass ? "✓" : "✗"));
    const body = el("div");
    const t = el("div");
    t.appendChild(el("b", null, x.dev));
    t.appendChild(el("code", null, x.cmd));
    body.appendChild(t);
    if (x.message) body.appendChild(el("div", "why", x.message));
    if (x.output) body.appendChild(el("pre", "raw", x.output));
    row.appendChild(body);
    box.appendChild(row);
  });
  if (r.error) box.appendChild(el("div", "why", r.error));
  S.lastOutput = (r.results || []).map((x) => `【${x.dev}】${x.cmd}\n${x.output || x.message || ""}`).join("\n\n");
}

function renderDiff(d, prepend) {
  if (!d || !d.ok) return;
  const wrap = el("div", "diff-box");
  (d.reports || []).forEach((rep) => {
    if (!rep.ok) {
      wrap.appendChild(el("div", "diff-dev", rep.dev + "：" + (rep.error || "读不到")));
      return;
    }
    wrap.appendChild(el("div", "diff-dev", `${rep.dev}　对上 ${rep.hit}/${rep.total} 条`));
    if (!rep.missing.length && !rep.extra.length) {
      wrap.appendChild(el("div", "diff-ok", "和标准配置一致"));
    }
    (rep.missing || []).slice(0, 8).forEach((m) => wrap.appendChild(el("div", "diff-miss", "缺　" + m)));
    if ((rep.missing || []).length > 8) {
      wrap.appendChild(el("div", "diff-miss", `……还有 ${rep.missing.length - 8} 条`));
    }
    (rep.extra || []).slice(0, 5).forEach((m) => wrap.appendChild(el("div", "diff-extra", "多　" + m)));
  });
  const box = $("#output");
  box.classList.remove("hidden");
  if (prepend) box.insertBefore(wrap, box.firstChild);
  else box.appendChild(wrap);
}

async function doDiff() {
  const s = currentStep();
  if (!s || S.busy) return;
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/diff`, {});
  const box = $("#output");
  box.classList.remove("hidden");
  box.innerHTML = "";
  if (!r.ok) {
    box.appendChild(el("div", "why", r.error || "比对失败"));
    return;
  }
  renderDiff(r);
}

async function doCheck() {
  const s = currentStep(); if (!s || S.busy) return;
  S.busy = true; $("#btnCheck").disabled = true;
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/check`, {});
  S.busy = false; $("#btnCheck").disabled = false;
  if (r.error) { toast(r.error); return; }
  renderCheck(r);
  if (!r.ok) {
    api(`/api/lab/${S.lab.id}/step/${s.id}/diff`, {}).then((d) => renderDiff(d, true)).catch(() => {});
  }
  if (r.ok) {
    if (!S.progress.done.includes(s.id)) S.progress.done.push(s.id);
    renderStepper();
    renderMeta();
    const next = S.lab.steps.find((x) => !S.progress.done.includes(x.id));
    const bar = el("div", "next-bar");
    const left = el("div");
    left.appendChild(el("div", "ok-line", "这一步的检查点全部通过"));
    if (next) left.appendChild(el("div", "next-hint", "下一步：" + next.title));
    bar.appendChild(left);
    if (next) {
      const b = el("button", "btn primary", "进入下一步 →");
      b.onclick = () => showStep(next.id);
      bar.appendChild(b);
    } else {
      const b = el("button", "btn primary", "做完了，去交卷");
      b.onclick = doGrade;
      bar.appendChild(b);
    }
    $("#output").appendChild(bar);
    toast("这一步过了，点右边的按钮进下一步");
  }
}

async function doHint() {
  const s = currentStep(); if (!s) return;
  S.hintLevel = Math.min(3, S.hintLevel + 1);
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/hint`, { level: S.hintLevel });
  const box = $("#hintBox");
  box.classList.remove("hidden");
  box.innerHTML = "";
  box.appendChild(el("span", "lv", ["提示 1 · 方向", "提示 2 · 思路", "提示 3 · 完整命令"][r.level - 1] || ""));
  box.appendChild(document.createTextNode(r.hint || "这一步没有更多提示了。"));
  if (S.hintLevel >= 3) $("#btnHint").textContent = "没有更多提示";
}

async function doDiagnose() {
  const s = currentStep();
  if (!s || S.busy) return;
  const btn = $("#btnDiag");
  const old = btn.textContent;
  S.busy = true; btn.disabled = true; btn.textContent = "正在读设备配置…";
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/diagnose`, {});
  S.busy = false; btn.disabled = false; btn.textContent = old;
  const box = $("#output");
  box.classList.remove("hidden");
  box.innerHTML = "";
  if (!r.ok) {
    box.appendChild(el("div", "why", r.error || "诊断失败"));
    return;
  }
  box.appendChild(el("div", "why", "读到了 " + (r.read || []).join("、") + " 的当前配置"));
  box.appendChild(el("div", "diag", r.content));
}

async function doAnswer() {
  const s = currentStep(); if (!s) return;
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/answer`, {});
  const box = $("#output");
  box.classList.remove("hidden");
  box.innerHTML = "";
  const head = el("div", "why", "答案在这，建议先自己敲一遍再看。抄进去也点「检查」，检查是通过配置回读判断的，不是看你抄没抄。");
  box.appendChild(head);
  Object.entries(r.answer || {}).forEach(([dev, cmds]) => {
    const row = el("div", "ans-block");
    const hd = el("div", "ans-head");
    hd.appendChild(el("b", null, dev));
    const cp = el("button", "mini", "复制");
    cp.onclick = async () => {
      try {
        await navigator.clipboard.writeText(cmds.join("\n"));
        toast(dev + " 的命令已复制，粘到设备窗口里就行");
      } catch (e) {
        toast("复制失败，手动选中吧");
      }
    };
    hd.appendChild(cp);
    row.appendChild(hd);
    row.appendChild(el("pre", "ans", cmds.join("\n")));
    box.appendChild(row);
  });
}

async function exportReport() {
  if (!S.lab) return;
  const done = (S.progress && S.progress.done) || [];
  let topo = "";
  try {
    topo = await (await fetch(`/api/lab/${S.lab.id}/mermaid`)).text();
  } catch (e) {}
  const lines = [
    `# ${S.lab.title}`,
    "",
    S.lab.subtitle || "",
    "",
    `- 难度：${S.lab.level || "-"}`,
    `- 知识点：${(S.lab.tags || []).join(" / ") || "-"}`,
    `- 进度：${done.length}/${S.lab.steps.length} 步`,
    `- 用时：${elapsed() || "-"}`,
    `- 导出时间：${new Date().toLocaleString("zh-CN")}`,
    "",
    "## 拓扑",
    "",
    "```mermaid",
    topo.trim(),
    "```",
    "",
    "## 步骤",
    "",
  ];
  S.lab.steps.forEach((s, i) => {
    lines.push(`### ${i + 1}. ${s.title} ${done.includes(s.id) ? "（已完成）" : ""}`);
    lines.push("");
    lines.push(s.brief || "");
    if (s.why) { lines.push(""); lines.push(`> ${s.why}`); }
    lines.push("");
  });
  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${S.lab.title}-实验报告.md`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  toast("实验报告已下载");
}

async function doApply() {  const s = currentStep(); if (!s || S.busy) return;
  if (!confirm("让 AI 看着设备当前状态来配这一步（没配 Key 时按标准配置刷入）。确定？")) return;
  S.busy = true; $("#btnApply").disabled = true;
  const r = await api(`/api/lab/${S.lab.id}/step/${s.id}/apply`, { mode: "ai" });
  S.busy = false; $("#btnApply").disabled = false;
  if (r.error) return toast(r.error);
  const box = $("#output");
  box.classList.remove("hidden");
  box.innerHTML = "";
  box.appendChild(el("div", "why", r.ai ? "AI 根据设备当前状态生成了这些命令并已执行：" : "已按标准配置刷入："));
  (r.report || []).forEach((x) => {
    const row = el("div", "res " + (x.ok ? "pass" : "fail"));
    row.appendChild(el("i", "ic", x.ok ? "✓" : "✗"));
    const bd = el("div");
    bd.appendChild(el("b", null, x.dev));
    (x.cmds || []).slice(0, 12).forEach((c) => bd.appendChild(el("code", null, c)));
    if (x.message) bd.appendChild(el("div", "why", x.message));
    row.appendChild(bd);
    box.appendChild(row);
  });
  if (r.diff) renderDiff(r.diff);
  const bad = (r.report || []).filter((x) => !x.ok);
  if (bad.length) toast(bad.map((b) => b.dev + "：" + b.message).join("；").slice(0, 120));
  else toast("已经刷进去了，正在检查");
  setTimeout(doCheck, 1800);
}

function pushMsg(role, text) {
  const box = $("#chat");
  const m = el("div", "msg " + role, text);
  box.appendChild(m);
  box.scrollTop = box.scrollHeight;
  return m;
}

async function send(text) {
  const q = (text || $("#input").value || "").trim();
  if (!q) return;
  if (!S.ai) { await setupKey(); if (!S.ai) return; }
  $("#input").value = "";
  pushMsg("me", q);
  const wait = pushMsg("bot", "…");
  const r = await api("/api/chat", {
    lab_id: S.lab ? S.lab.id : "",
    step_id: S.stepId,
    question: q,
    last_output: S.lastOutput,
    history: S.history.slice(-6)
  });
  if (r.ok) {
    wait.textContent = r.content;
    S.history.push({ role: "user", content: q }, { role: "assistant", content: r.content });
  } else {
    wait.className = "msg err";
    wait.textContent = r.error || "调用失败";
  }
}

let pendingLabId = null;

function openGen() {
  $("#genModal").classList.remove("hidden");
  $("#genForm").classList.remove("hidden");
  $("#genLoading").classList.add("hidden");
  $("#genResult").classList.add("hidden");
  $("#genError").classList.add("hidden");
  setTimeout(() => $("#genBrief").focus(), 50);
}

function closeGen() {
  $("#genModal").classList.add("hidden");
  if (runTimer) { clearInterval(runTimer); runTimer = null; }
}

async function setupKey() {
  const k = window.prompt("把 DeepSeek 的 API Key 粘进来（sk- 开头），只存在这台机器的 config.json 里：");
  if (!k) return;
  const r = await api("/api/config", { api_key: k.trim() });
  if (!r.ok) return toast(r.error || "保存失败");
  await refreshLabs();
  toast("Key 已保存，可以生成实验了");
}

async function doGenerate() {
  if (!S.ai) { await setupKey(); if (!S.ai) return; }
  const brief = ($("#genBrief").value || "").trim();
  if (brief.length < 4) return toast("再多说两句，说清要练什么");
  $("#genForm").classList.add("hidden");
  $("#genError").classList.add("hidden");
  $("#genResult").classList.add("hidden");
  $("#genLoading").classList.remove("hidden");
  const stages = ["读你的需求…", "挑设备、算接口…", "拆步骤、写检查点…", "校验拓扑和命令…"];
  let i = 0;
  $("#genStep").textContent = stages[0];
  const timer = setInterval(() => { i = (i + 1) % stages.length; $("#genStep").textContent = stages[i]; }, 4000);
  const r = await api("/api/lab/generate", { brief });
  clearInterval(timer);
  $("#genLoading").classList.add("hidden");
  if (!r.ok) {
    $("#genForm").classList.remove("hidden");
    $("#genError").classList.remove("hidden");
    $("#genError").textContent = r.error || "生成失败，换个说法再试";
    return;
  }
  pendingLabId = r.id;
  renderGenResult(r.lab);
}

function renderGenResult(lab) {
  const box = $("#genResult");
  box.innerHTML = "";
  box.appendChild(el("div", "gr-title", lab.title));
  box.appendChild(el("div", "gr-sub", `${lab.subtitle} · ${lab.level} · ${lab.steps.length} 步`));

  box.appendChild(el("div", "gr-sec", "设备"));
  const dv = el("div", "gr-devs");
  (lab.devices || []).forEach((d) => {
    const s = el("span", "gr-dev");
    s.innerHTML = `<b>${esc(d.name)}</b> ${esc(d.model)}`;
    dv.appendChild(s);
  });
  box.appendChild(dv);

  box.appendChild(el("div", "gr-sec", "步骤"));
  (lab.steps || []).forEach((s, i) => {
    const row = el("div", "gr-step");
    row.appendChild(el("i", null, String(i + 1)));
    const c = el("div");
    c.appendChild(el("span", null, s.title));
    c.appendChild(el("small", null, s.brief));
    row.appendChild(c);
    box.appendChild(row);
  });

  const acts = el("div", "modal-actions");
  const again = el("button", "btn ghost", "换个说法");
  again.onclick = () => { box.classList.add("hidden"); $("#genForm").classList.remove("hidden"); };
  const run = el("button", "btn", "先试跑一遍");
  run.onclick = doAutoplay;
  const go = el("button", "btn primary", "开始做这个");
  go.onclick = async () => {
    closeGen();
    await refreshLabs();
    selectLab(pendingLabId);
  };
  acts.appendChild(again);
  acts.appendChild(run);
  acts.appendChild(go);
  box.appendChild(acts);
  box.classList.remove("hidden");
}

let runTimer = null;

async function doAutoplay() {
  $("#genResult").classList.add("hidden");
  $("#genError").classList.add("hidden");
  $("#genRun").classList.remove("hidden");
  $("#runError").classList.add("hidden");
  $("#runGo").classList.add("hidden");
  $("#runLog").innerHTML = "";
  $("#runStage").textContent = "正在生成拓扑并打开 eNSP…";
  $("#runCount").textContent = "";
  await api(`/api/lab/${pendingLabId}/autoplay`, {});
  pollRun();
  if (runTimer) clearInterval(runTimer);
  runTimer = setInterval(pollRun, 2000);
}

async function pollRun() {
  const r = await api(`/api/lab/${pendingLabId}/autoplay/status`, {});
  if (!r.ok || r.state === "idle") return;
  const stageText = { running: "准备中", wait: "等设备启动", run: "正在逐步试跑", done: "试跑完成", failed: "试跑失败" };
  $("#runStage").textContent = stageText[r.state] || r.state;
  if (r.total) $("#runCount").textContent = `${r.ready || 0}/${r.total} 台在线`;
  const box = $("#runLog");
  box.innerHTML = "";
  (r.log || []).forEach((l) => box.appendChild(el("div", null, l)));
  box.scrollTop = box.scrollHeight;
  if (r.state === "done" || r.state === "failed") {
    if (runTimer) { clearInterval(runTimer); runTimer = null; }
    if (r.state === "failed") {
      $("#runError").classList.remove("hidden");
      $("#runError").textContent = r.error || "试跑没通过";
    } else {
      $("#runGo").classList.remove("hidden");
      refreshLabs();
    }
  }
}

async function loadExam() {
  const ex = await api("/api/exam");
  S.exam = ex;
  renderExam(ex);
}

function renderExam(ex) {
  const box = $("#examBox");
  box.innerHTML = "";
  if (!ex.items || !ex.items.length) {
    const b = el("button", "gen-btn", "组一份试卷");
    b.onclick = openExamModal;
    box.appendChild(b);
    return;
  }
  ex.items.forEach((it) => {
    const row = el("div", "exam-row");
    row.appendChild(el("span", null, it.title));
    row.appendChild(el("b", it.score == null ? "na" : "", it.score == null ? "未做" : it.score + " 分"));
    row.onclick = () => selectLab(it.id);
    box.appendChild(row);
  });
  const tot = el("div", "exam-total");
  tot.innerHTML = `总分 <b>${ex.score}</b> / ${ex.full} · 完成 ${ex.done}/${ex.count}`;
  box.appendChild(tot);
  const b = el("button", "mini", "重新组卷");
  b.style.marginTop = "8px";
  b.onclick = openExamModal;
  box.appendChild(b);
}

async function openExamModal() {
  const ex = await api("/api/exam");
  const cur = new Set((ex.items || []).map((i) => i.id));
  const box = $("#examPick");
  box.innerHTML = "";
  S.labs.forEach((l) => {
    const lb = el("label");
    const cb = el("input");
    cb.type = "checkbox";
    cb.value = l.id;
    cb.checked = cur.has(l.id);
    const d = el("div");
    d.appendChild(el("b", null, l.title));
    d.appendChild(el("small", null, `${l.subtitle} · ${l.steps} 步`));
    lb.appendChild(cb);
    lb.appendChild(d);
    box.appendChild(lb);
  });
  $("#examModal").classList.remove("hidden");
}

async function saveExam() {
  const ids = Array.from(document.querySelectorAll("#examPick input:checked")).map((x) => x.value);
  const ex = await api("/api/exam", { lab_ids: ids });
  S.exam = ex;
  renderExam(ex);
  $("#examModal").classList.add("hidden");
  toast(ids.length ? `试卷收好了，共 ${ids.length} 题` : "试卷清空了");
}

async function doGrade() {
  if (!S.lab) return;
  if (!confirm("交卷会把当前所有检查点重跑一遍，按完成情况和扣分算总分。继续？")) return;
  toast("正在判分…");
  const r = await api(`/api/lab/${S.lab.id}/grade`, {});
  if (!r.ok) return toast(r.error || "判分失败");
  showGrade(r);
  loadExam();
}

function showGrade(r) {
  $("#gradeTitle").textContent = S.lab.title + " · 成绩单";
  $("#gradeSub").textContent = new Date(r.at * 1000).toLocaleString("zh-CN") + " 判分";
  const body = $("#gradeBody");
  body.innerHTML = "";
  const head = el("div", "g-score");
  head.appendChild(el("div", "n" + (r.score < 60 ? " bad" : ""), String(r.score)));
  head.appendChild(el("div", "u", "/ 100"));
  head.appendChild(el("div", "lv", ({ A: "优秀", B: "良好", C: "及格", D: "不及格" }[r.grade] || "") + " · " + r.grade));
  body.appendChild(head);

  r.rows.forEach((row, i) => {
    const d = el("div", "g-row");
    d.appendChild(el("div", "idx", String(i + 1)));
    const t = el("div", "t");
    t.appendChild(document.createTextNode(row.title + (row.penalty ? `（提示/答案扣 ${row.penalty}%）` : "")));
    if (!row.pass) t.appendChild(el("small", null, "没过：" + (row.fails || []).join("；")));
    d.appendChild(t);
    d.appendChild(el("div", "s" + (row.score ? "" : " zero"), row.score + " / " + row.full));
    body.appendChild(d);
  });

  const acts = $("#gradeActs");
  acts.innerHTML = "";
  const back = el("button", "btn ghost", "回去接着做");
  back.onclick = () => $("#gradeModal").classList.add("hidden");
  acts.appendChild(back);
  const nextItem = ((S.exam && S.exam.items) || []).find((i) => i.score == null && i.id !== S.lab.id);
  if (nextItem) {
    const next = el("button", "btn primary", "下一题：" + nextItem.title);
    next.onclick = () => {
      $("#gradeModal").classList.add("hidden");
      selectLab(nextItem.id);
    };
    acts.appendChild(next);
  }
  $("#gradeModal").classList.remove("hidden");
}

let kbCat = "";
let kbTimer = null;
let kbLoaded = false;

function mdToHtml(md) {
  const e = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  let t = e(String(md || ""));
  t = t.replace(/^#{1,3}\s+(.+)$/gm, "<h3>$1</h3>");
  t = t.replace(/^#{4,5}\s+(.+)$/gm, "<h4>$1</h4>");
  t = t.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  t = t.replace(/`([^`]+)`/g, "<code>$1</code>");
  const isSep = (s) => /^\|[\s:\-|]+\|?$/.test(s.trim());
  const cells = (s) => s.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((x) => x.trim());
  const blocks = t.split(/\n{2,}/).map((blk) => {
    const lines = blk.split("\n").filter((x) => x.trim());
    if (!lines.length) return "";
    if (lines.length >= 2 && /^\|/.test(lines[0]) && isSep(lines[1])) {
      const head = cells(lines[0]);
      const rows = lines.slice(2).filter((x) => /^\|/.test(x)).map(cells);
      let h = "<table><thead><tr>" + head.map((c) => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>";
      h += rows.map((r) => "<tr>" + r.map((c) => "<td>" + c + "</td>").join("") + "</tr>").join("");
      return h + "</tbody></table>";
    }
    if (lines.every((x) => /^[-*]\s+/.test(x))) {
      return "<ul>" + lines.map((x) => "<li>" + x.replace(/^[-*]\s+/, "") + "</li>").join("") + "</ul>";
    }
    if (/^<h[34]>/.test(lines[0])) return lines.join("");
    return "<p>" + lines.join("<br>") + "</p>";
  });
  return blocks.join("");
}

function kbRenderCats(cats) {
  const box = $("#kbCats");
  box.innerHTML = "";
  [""].concat(cats).forEach((c) => {
    const b = el("button", c === kbCat ? "on" : "", c || "全部");
    b.onclick = () => { kbCat = c; loadKB(); };
    box.appendChild(b);
  });
}

async function loadKB() {
  const q = ($("#kbQ").value || "").trim();
  const r = await api(`/api/kb?q=${encodeURIComponent(q)}&cat=${encodeURIComponent(kbCat)}`);
  if (!r.ok) return toast(r.error || "知识库没加载出来");
  if (r.cats) { S.kbCats = r.cats; kbRenderCats(r.cats); }
  renderKbSide();
  const box = $("#kbList");
  box.innerHTML = "";
  if (!r.items.length) {
    box.appendChild(el("div", "kb-empty", "没搜到，换个词试试"));
    return;
  }
  r.items.forEach((it, i) => {
    const d = el("div", "kb-item");
    const b = document.createElement("b");
    b.appendChild(document.createTextNode(it.title || ""));
    b.appendChild(el("span", "kb-lv " + (it.level || ""), it.level || ""));
    d.appendChild(b);
    d.appendChild(el("span", null, it.one || ""));
    d.onclick = () => openKBItem(it.id, d);
    box.appendChild(d);
    if (i === 0 && !$("#kbDetail").dataset.loaded) openKBItem(it.id, d);
  });
}

async function openKBItem(id, node) {
  document.querySelectorAll(".kb-item.on").forEach((x) => x.classList.remove("on"));
  if (node) node.classList.add("on");
  const d = await api("/api/kb/" + id);
  if (!d || d.ok === false) return;
  const box = $("#kbDetail");
  box.dataset.loaded = "1";
  box.innerHTML = "";
  const h = el("h2", "kb-h1");
  h.appendChild(document.createTextNode(d.title || ""));
  h.appendChild(el("span", "kb-lv " + (d.level || ""), d.level || ""));
  if (d.cat) h.appendChild(el("span", "kb-lv", d.cat));
  if (d.syllabus) h.appendChild(el("span", "kb-lv", d.syllabus));
  box.appendChild(h);
  if (d.one) box.appendChild(el("div", "kb-one", d.one));
  if (d.analogy) box.appendChild(el("div", "kb-analogy", d.analogy));
  const md = el("div", "kb-md");
  md.innerHTML = mdToHtml(d.body);
  box.appendChild(md);

  if ((d.cmds || []).length) {
    const s = el("div", "kb-sec");
    s.appendChild(el("h5", null, "常用命令"));
    const w = el("div", "kb-cmds");
    d.cmds.forEach((c) => w.appendChild(el("code", null, c)));
    s.appendChild(w);
    box.appendChild(s);
  }
  if ((d.pits || []).length) {
    const s = el("div", "kb-sec");
    s.appendChild(el("h5", null, "容易踩的坑"));
    d.pits.forEach((p) => {
      const row = el("div", "kb-pit");
      row.appendChild(el("i", null, "·"));
      row.appendChild(el("span", null, p));
      s.appendChild(row);
    });
    box.appendChild(s);
  }
  if ((d.qa || []).length) {
    const s = el("div", "kb-sec");
    s.appendChild(el("h5", null, "常问"));
    d.qa.forEach((q) => {
      const row = el("div", "kb-qa");
      row.appendChild(el("b", null, q.q || ""));
      row.appendChild(el("span", null, q.a || ""));
      s.appendChild(row);
    });
    box.appendChild(s);
  }
  box.scrollTop = 0;
}

function openKB(cat) {
  const url = cat ? `/kb?cat=${encodeURIComponent(cat)}` : "/kb";
  window.open(url, "ensp-kb");
}

function renderKbSide() {
  const box = $("#kbCatsSide");
  if (!box) return;
  box.innerHTML = "";
  const all = el("button", kbCat === "" ? "on" : "", "全部");
  all.onclick = () => openKB("");
  box.appendChild(all);
  (S.kbCats || []).forEach((c) => {
    const b = el("button", c === kbCat ? "on" : "", c);
    b.onclick = () => openKB(c);
    box.appendChild(b);
  });
}

const on = (sel, fn) => { const e = $(sel); if (e) e.onclick = fn; };
const onKey = (sel, fn) => { const e = $(sel); if (e) e.addEventListener("keydown", fn); };

on("#btnTheme", () => setTheme(document.documentElement.dataset.theme === "apple" ? "huawei" : "apple"));
on("#btnFloat", async () => {
  const r = await api("/api/float", {});
  toast(r.ok ? (r.reused ? "小窗已经在屏幕上了" : "小窗钉在最前了") : (r.error || "打不开小窗"));
});

on("#btnBuild", doBuild);
on("#btnGrade", doGrade);
on("#examClose", () => $("#examModal").classList.add("hidden"));
on("#examSave", saveExam);
on("#gradeClose", () => $("#gradeModal").classList.add("hidden"));
on("#btnGen", openGen);
on("#aiHead", () => { if (!S.ai) setupKey(); });
on("#genClose", closeGen);
on("#genGo", doGenerate);
onKey("#genBrief", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doGenerate(); }
});
document.querySelectorAll(".chips button").forEach((b) => {
  b.onclick = () => { const t = $("#genBrief"); if (t) { t.value = b.dataset.b; t.focus(); } };
});
const gm = $("#genModal");
if (gm) gm.addEventListener("click", (e) => { if (e.target.id === "genModal") closeGen(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeGen(); });

document.addEventListener("keydown", (e) => {
  if (!(e.ctrlKey || e.metaKey)) return;
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "TEXTAREA" || tag === "INPUT") return;
  const k = (e.key || "").toLowerCase();
  if (k === "enter") { e.preventDefault(); doCheck(); }
  else if (k === "h") { e.preventDefault(); doHint(); }
  else if (k === "d") { e.preventDefault(); doDiagnose(); }
  else if (k === "k") { e.preventDefault(); openKB(); }
});
on("#runBack", closeGen);

on("#btnDiscover", async () => {
  if (!S.lab) return;
  toast("正在扫 2000-2100 的 console 端口…");
  const r = await api(`/api/lab/${S.lab.id}/discover`, {});
  if (!r.ok) return toast(r.error || "识别失败");
  await refreshStatus();
  if (!r.found || !r.found.length) return toast("一个 console 都没扫到，设备还没开？");
  toast(r.changed && r.changed.length ? "已对齐：" + r.changed.join("，") : "扫到的设备名对不上，端口没动");
});

on("#btnMermaid", async () => {
  if (!S.lab) return;
  const res = await fetch(`/api/lab/${S.lab.id}/mermaid`);
  const text = await res.text();
  const box = $("#output");
  box.classList.remove("hidden");
  box.innerHTML = "";
  box.appendChild(el("div", "why", "拓扑图源码（Mermaid）。贴进 Typora、Notion、语雀或 draw.io 就能出图，写实验报告和教案用得上。"));
  box.appendChild(el("pre", "ans", text));
});

let calibTimer = null;
let lastCalibMsg = "";

async function pollCalib() {
  const r = await api("/api/calibrate/status", {});
  if (!r.ok) return;
  if (r.msg && r.msg !== lastCalibMsg) {
    lastCalibMsg = r.msg;
    toast(r.msg);
  }
  if (r.state === "testing" && r.offset) {
    $("#btnCalib").textContent = "正在看设备起没起…";
  }
  if (r.state === "done") {
    clearInterval(calibTimer); calibTimer = null;
    S.calibrated = true;
    $("#btnCalib").textContent = "校准启动按钮";
    toast(`校准好了，刚试了一次：${r.ready}/${r.total} 台设备起来了`);
    refreshStatus();
    startPoll();
  }
  if (r.state === "failed") {
    clearInterval(calibTimer); calibTimer = null;
    $("#btnCalib").textContent = "校准启动按钮";
    toast(r.msg || "校准没成功");
  }
}

on("#btnCalib", async () => {
  if (!confirm("点确定之后：\n\n1. 你自己从任务栏把 eNSP 点出来\n2. 在里面点一下工具栏的绿色三角（这一下会真的启动设备）\n3. 我记下这个位置，顺便看设备起没起\n\n不用急着点，有 90 秒。确定开始。")) return;
  $("#btnCalib").textContent = "等你在 eNSP 里点一下…";
  lastCalibMsg = "";
  const r = await api("/api/calibrate/arm", {});
  if (!r.ok) {
    $("#btnCalib").textContent = "校准启动按钮";
    return toast(r.error || "启动校准失败");
  }
  if (calibTimer) clearInterval(calibTimer);
  calibTimer = setInterval(pollCalib, 1200);
});

on("#btnSave", async () => {
  if (!S.lab) return;
  if (!confirm("把每台设备的运行配置写进 flash（相当于关 eNSP 前做一次 save）。继续？")) return;
  toast("正在逐台保存…");
  const r = await api(`/api/lab/${S.lab.id}/save`, {});
  if (r.error) return toast(r.error);
  const bad = (r.report || []).filter((x) => !x.ok);
  toast(bad.length ? "有设备没存上：" + bad.map((b) => b.dev).join("、") : "全部保存成功");
});
on("#btnKB", openKB);
on("#btnCourse", () => window.open("/course", "ensp-course"));
on("#btnHelp", () => window.open("/help", "ensp-help"));
on("#kbClose", () => $("#kbModal").classList.add("hidden"));
on("#secLabs", () => toggleLabs());
on("#secKb", () => toggleSec("#secKb", "#kbCatsSide", "kbClosed"));

on("#kbNewGo", async () => {
  const t = ($("#kbNewTitle").value || "").trim();
  if (t.length < 2) return toast("先写个知识点名字");
  const btn = $("#kbNewGo");
  const old = btn.textContent;
  btn.disabled = true; btn.textContent = "生成中…";
  const r = await api("/api/kb/add", {
    title: t,
    level: $("#kbNewLevel").value,
    cat: $("#kbNewCat").value,
  });
  btn.disabled = false; btn.textContent = old;
  if (!r.ok) return toast(r.error || "入库失败");
  toast("已入库：" + r.title);
  $("#kbNewTitle").value = "";
  kbCat = "";
  document.querySelectorAll(".kb-item.on").forEach((x) => x.classList.remove("on"));
  $("#kbDetail").dataset.loaded = "";
  await loadKB();
  openKBItem(r.id);
});

const kbq = $("#kbQ");
if (kbq) {
  kbq.addEventListener("input", () => {
    clearTimeout(kbTimer);
    kbTimer = setTimeout(loadKB, 250);
  });
}

on("#btnReport", exportReport);
on("#btnCheck", doCheck);
on("#btnHint", doHint);
on("#btnDiag", doDiagnose);
on("#btnDiff", doDiff);
on("#btnAnswer", doAnswer);
on("#btnApply", doApply);
on("#btnSend", () => send());
onKey("#input", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
document.querySelectorAll(".quick button").forEach((b) => {
  b.onclick = () => send(b.dataset.q);
});
on("#btnReset", async () => {
  if (!S.lab) return;
  if (!confirm("清掉这个实验的进度和已生成的拓扑？设备需要在 eNSP 里自己关。")) return;
  await api("/api/lab/" + S.lab.id + "/reset", { progress: true });
  S.progress = { done: [] };
  toast("已重置");
  selectLab(S.lab.id);
});

if (localStorage.getItem("labsClosed")) toggleLabs(true);
if (localStorage.getItem("kbClosed")) toggleSec("#secKb", "#kbCatsSide", "kbClosed", true);

boot();
