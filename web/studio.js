(function () {
  const $ = (selector, root) => (root || document).querySelector(selector);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const api = (path, body) => window.enspJSON(path, body);
  const esc = (value) => String(value == null ? "" : value).replace(/[&<>"]/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
  }[ch]));

  function notify(message) {
    if (typeof window.toast === "function") window.toast(message);
    else {
      const node = $("#toast");
      if (!node) return;
      node.textContent = message;
      node.classList.add("on");
      setTimeout(() => node.classList.remove("on"), 2600);
    }
  }

  function closeModal(id) {
    const modal = $("#" + id);
    if (modal) modal.classList.add("hidden");
  }

  function openModal(id) {
    const modal = $("#" + id);
    if (modal) modal.classList.remove("hidden");
    return modal;
  }

  function modal(id, html) {
    const box = el("div", "modal hidden");
    box.id = id;
    box.innerHTML = html;
    document.body.appendChild(box);
    box.addEventListener("click", (event) => {
      if (event.target === box) box.classList.add("hidden");
    });
    box.querySelectorAll("[data-close]").forEach((button) => {
      button.onclick = () => box.classList.add("hidden");
    });
    return box;
  }

  function fmtTime(seconds) {
    if (!seconds) return "-";
    return new Date(seconds * 1000).toLocaleString("zh-CN", { hour12: false });
  }

  function announce(lab) {
    window.dispatchEvent(new CustomEvent("studio:labs-changed", { detail: { select: lab && lab.id } }));
  }

  // ---------------------------------------------------------------------
  // Topology editor
  // ---------------------------------------------------------------------
  const topo = {
    modal: null, models: null, modelsPromise: null,
    devices: [], links: [], selected: -1, linkFrom: null, linking: false,
    title: "", subtitle: "", copyOnly: true, existingId: "", busy: false,
    stageW: 1200, stageH: 700
  };

  function loadModels() {
    if (topo.models) return Promise.resolve(topo.models);
    if (!topo.modelsPromise) {
      topo.modelsPromise = api("/api/topology/capabilities").then((result) => {
        if (!result.ok) throw new Error(result.error || "读取设备型号失败");
        topo.models = result.models || [];
        return topo.models;
      }).catch((err) => {
        topo.modelsPromise = null;
        throw err;
      });
    }
    return topo.modelsPromise;
  }

  function modelInfo(model) {
    return (topo.models || []).find((item) => item.model === model) || {};
  }

  function defaultName(model) {
    const prefix = model === "PC" ? "PC" : model.startsWith("S") ? "SW" : "R";
    const used = new Set(topo.devices.map((item) => item.name));
    for (let index = 1; index < 100; index += 1) {
      const name = prefix + index;
      if (!used.has(name)) return name;
    }
    return prefix + Date.now();
  }

  function ensureTopoModal() {
    if (topo.modal) return topo.modal;
    topo.modal = modal("topoModal", `
      <div class="modal-box studio-box topo-box">
        <div class="studio-head">
          <div class="studio-title">
            <h3>拓扑编辑器</h3>
            <p>拖拽设备、连接接口，保存后由 eNSP 后端生成拓扑。端口会自动分配。</p>
          </div>
          <div class="studio-head-actions">
            <button id="topoNew" class="btn ghost">清空新建</button>
            <button class="x" data-close>×</button>
          </div>
        </div>
        <div class="topo-meta">
          <label>实验名<input id="topoTitle" maxlength="40" placeholder="例如：三交换机 VLAN 实验"></label>
          <label>说明<input id="topoSubtitle" maxlength="120" placeholder="一句话说明这张拓扑"></label>
        </div>
        <div class="topo-layout">
          <aside class="topo-panel topo-palette">
            <div class="studio-label">设备</div>
            <div id="topoModels" class="topo-models"></div>
            <div class="studio-label">操作</div>
            <button id="topoLinkMode" class="btn">连接两台设备</button>
            <p class="studio-note">添加后拖动设备调整位置。连接模式下依次点击两台设备；接口由后端自动选取空闲端口。</p>
          </aside>
          <div class="topo-stage-wrap">
            <div class="topo-toolbar">
              <span>画布</span>
              <span id="topoCount" class="studio-dim">0 台设备 / 0 条链路</span>
            </div>
            <div id="topoStage" class="topo-stage">
              <svg id="topoLines" class="topo-lines" viewBox="0 0 1200 700" preserveAspectRatio="none"></svg>
              <div id="topoNodes" class="topo-nodes"></div>
            </div>
          </div>
          <aside class="topo-panel topo-inspector">
            <div class="studio-label">属性</div>
            <div id="topoInspector" class="topo-inspector-body"></div>
            <div class="studio-label">链路</div>
            <div id="topoLinks" class="topo-link-list"></div>
          </aside>
        </div>
        <div id="topoError" class="studio-error hidden"></div>
        <div class="studio-actions">
          <span id="topoSaveNote" class="studio-dim"></span>
          <button id="topoSave" class="btn primary">保存沙箱</button>
        </div>
      </div>`);
    $("#topoNew", topo.modal).onclick = () => resetTopology(null, true);
    $("#topoLinkMode", topo.modal).onclick = () => {
      topo.linking = !topo.linking;
      topo.linkFrom = null;
      $("#topoLinkMode", topo.modal).classList.toggle("primary", topo.linking);
      $("#topoLinkMode", topo.modal).textContent = topo.linking ? "退出连接模式" : "连接两台设备";
      renderTopology();
    };
    $("#topoSave", topo.modal).onclick = saveTopology;
    return topo.modal;
  }

  function resetTopology(lab, blank) {
    topo.devices = blank ? [] : JSON.parse(JSON.stringify((lab && lab.devices) || []));
    topo.links = blank ? [] : JSON.parse(JSON.stringify((lab && lab.links) || []));
    topo.selected = topo.devices.length ? 0 : -1;
    topo.linkFrom = null;
    topo.linking = false;
    topo.existingId = lab && !blank ? lab.id : "";
    topo.copyOnly = !(lab && !blank && lab.sandbox && lab.source === "user");
    topo.title = lab && !blank ? (topo.copyOnly ? `${lab.title} · 副本` : lab.title) : "未命名拓扑";
    topo.subtitle = lab && !blank ? (lab.subtitle || "") : "自定义拓扑沙箱";
    $("#topoTitle", topo.modal).value = topo.title;
    $("#topoSubtitle", topo.modal).value = topo.subtitle;
    $("#topoLinkMode", topo.modal).classList.remove("primary");
    $("#topoLinkMode", topo.modal).textContent = "连接两台设备";
    $("#topoSave", topo.modal).textContent = topo.copyOnly ? "另存为沙箱" : "保存沙箱";
    $("#topoSaveNote", topo.modal).textContent = topo.copyOnly
      ? "内置/模板实验不会原地修改，会另存一个自定义沙箱。"
      : "保存后会清理旧拓扑状态，需要重新一键搭建。";
    $("#topoError", topo.modal).classList.add("hidden");
    renderTopology();
  }

  async function openTopology(lab) {
    try {
      await loadModels();
    } catch (err) {
      return notify(err.message || "读取设备型号失败");
    }
    ensureTopoModal();
    resetTopology(lab, !lab);
    openModal(topo.modal.id);
  }

  function renderTopology() {
    if (!topo.modal) return;
    renderTopoPalette();
    renderTopoNodes();
    renderTopoLines();
    renderTopoInspector();
    renderTopoLinks();
    $("#topoCount", topo.modal).textContent = `${topo.devices.length} 台设备 / ${topo.links.length} 条链路`;
  }

  function renderTopoPalette() {
    const box = $("#topoModels", topo.modal);
    box.innerHTML = "";
    (topo.models || []).forEach((item) => {
      const button = el("button", "topo-model");
      button.appendChild(el("b", null, item.label));
      button.appendChild(el("small", null, item.console ? "有 console" : "无 console"));
      button.onclick = () => {
        const model = item.model;
        const device = {
          name: defaultName(model), model,
          x: 100 + (topo.devices.length % 5) * 150,
          y: 100 + Math.floor(topo.devices.length / 5) * 130
        };
        if (model === "PC") {
          device.ip = "192.168.10.10";
          device.mask = "255.255.255.0";
          device.gateway = "192.168.10.1";
        }
        topo.devices.push(device);
        topo.selected = topo.devices.length - 1;
        renderTopology();
      };
      box.appendChild(button);
    });
  }

  function makeTopoNode(device, index) {
    const node = el("div", "topo-node");
    if (index === topo.selected) node.classList.add("on");
    if (topo.linkFrom === index) node.classList.add("linking");
    node.style.left = `${device.x || 100}px`;
    node.style.top = `${device.y || 100}px`;
    const badge = el("div", "topo-node-model", device.model);
    const name = el("b", null, device.name);
    const meta = el("small", null, device.model === "PC" ? (device.ip || "PC") : "console");
    node.appendChild(badge);
    node.appendChild(name);
    node.appendChild(meta);
    node.addEventListener("pointerdown", (event) => startNodeDrag(event, index));
    return node;
  }

  function renderTopoNodes() {
    const box = $("#topoNodes", topo.modal);
    box.innerHTML = "";
    topo.devices.forEach((device, index) => box.appendChild(makeTopoNode(device, index)));
  }

  function startNodeDrag(event, index) {
    event.preventDefault();
    const stage = $("#topoStage", topo.modal);
    const rect = stage.getBoundingClientRect();
    const startX = event.clientX;
    const startY = event.clientY;
    const device = topo.devices[index];
    const originX = Number(device.x) || 0;
    const originY = Number(device.y) || 0;
    let moved = false;
    const move = (moveEvent) => {
      const dx = moveEvent.clientX - startX;
      const dy = moveEvent.clientY - startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      device.x = Math.max(0, Math.min(topo.stageW - 110, Math.round(originX + dx)));
      device.y = Math.max(0, Math.min(topo.stageH - 70, Math.round(originY + dy)));
      const node = $("#topoNodes", topo.modal).children[index];
      if (node) {
        node.style.left = `${device.x}px`;
        node.style.top = `${device.y}px`;
      }
      renderTopoLines();
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      if (!moved) chooseTopoNode(index);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  function chooseTopoNode(index) {
    if (!topo.linking) {
      topo.selected = index;
      renderTopology();
      return;
    }
    if (topo.linkFrom == null) {
      topo.linkFrom = index;
      topo.selected = index;
      renderTopology();
      return;
    }
    if (topo.linkFrom === index) {
      topo.linkFrom = null;
      renderTopology();
      return;
    }
    const a = topo.devices[topo.linkFrom];
    const b = topo.devices[index];
    const exists = topo.links.some((link) => (link.a === a.name && link.b === b.name) ||
      (link.a === b.name && link.b === a.name));
    if (!exists) topo.links.push({ a: a.name, b: b.name });
    topo.linkFrom = null;
    topo.linking = false;
    $("#topoLinkMode", topo.modal).classList.remove("primary");
    $("#topoLinkMode", topo.modal).textContent = "连接两台设备";
    renderTopology();
  }

  function renderTopoLines() {
    const svg = $("#topoLines", topo.modal);
    svg.innerHTML = "";
    topo.links.forEach((link) => {
      const a = topo.devices.find((item) => item.name === link.a);
      const b = topo.devices.find((item) => item.name === link.b);
      if (!a || !b) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", String(Number(a.x || 0) + 52));
      line.setAttribute("y1", String(Number(a.y || 0) + 30));
      line.setAttribute("x2", String(Number(b.x || 0) + 52));
      line.setAttribute("y2", String(Number(b.y || 0) + 30));
      line.setAttribute("class", "topo-line");
      svg.appendChild(line);
    });
  }

  function renderTopoInspector() {
    const box = $("#topoInspector", topo.modal);
    box.innerHTML = "";
    const device = topo.devices[topo.selected];
    if (!device) {
      box.appendChild(el("p", "studio-empty", "选择设备后在这里编辑名称、型号和 PC 地址。"));
      return;
    }
    const nameLabel = el("label", null, "设备名");
    const name = el("input");
    name.maxLength = 16;
    name.value = device.name;
    name.onchange = () => {
      const value = name.value.trim();
      if (!/^[A-Za-z][A-Za-z0-9_-]{0,15}$/.test(value)) return notify("设备名必须以字母开头，只含字母数字_-");
      const old = device.name;
      if (topo.devices.some((item, index) => index !== topo.selected && item.name === value)) {
        return notify("设备名重复");
      }
      topo.links.forEach((link) => {
        if (link.a === old) link.a = value;
        if (link.b === old) link.b = value;
      });
      device.name = value;
      renderTopology();
    };
    nameLabel.appendChild(name);
    box.appendChild(nameLabel);

    const modelLabel = el("label", null, "型号");
    const model = el("select");
    (topo.models || []).forEach((item) => {
      const option = el("option", null, item.label);
      option.value = item.model;
      option.selected = item.model === device.model;
      model.appendChild(option);
    });
    model.onchange = () => {
      if (topo.links.some((link) => link.a === device.name || link.b === device.name)) {
        if (!confirm("换型号会删除这台设备的链路，继续？")) {
          model.value = device.model;
          return;
        }
        topo.links = topo.links.filter((link) => link.a !== device.name && link.b !== device.name);
      }
      device.model = model.value;
      if (device.model === "PC" && !device.ip) {
        device.ip = "192.168.10.10";
        device.mask = "255.255.255.0";
        device.gateway = "192.168.10.1";
      }
      renderTopology();
    };
    modelLabel.appendChild(model);
    box.appendChild(modelLabel);

    if (device.model === "PC") {
      [["ip", "IP 地址"], ["mask", "子网掩码"], ["gateway", "默认网关"]].forEach(([key, label]) => {
        const wrapper = el("label", null, label);
        const input = el("input");
        input.value = device[key] || "";
        input.oninput = () => { device[key] = input.value.trim(); };
        wrapper.appendChild(input);
        box.appendChild(wrapper);
      });
    }
    const remove = el("button", "btn ghost studio-danger", "删除设备");
    remove.onclick = () => {
      const current = topo.devices[topo.selected];
      topo.links = topo.links.filter((link) => link.a !== current.name && link.b !== current.name);
      topo.devices.splice(topo.selected, 1);
      topo.selected = topo.devices.length ? Math.min(topo.selected, topo.devices.length - 1) : -1;
      renderTopology();
    };
    box.appendChild(remove);
  }

  function renderTopoLinks() {
    const box = $("#topoLinks", topo.modal);
    box.innerHTML = "";
    if (!topo.links.length) {
      box.appendChild(el("p", "studio-empty", "还没有链路。"));
      return;
    }
    topo.links.forEach((link, index) => {
      const row = el("div", "topo-link-row");
      const text = el("div");
      text.appendChild(el("b", null, `${link.a} ↔ ${link.b}`));
      text.appendChild(el("small", null, `${link.aPort || "自动"} / ${link.bPort || "自动"}`));
      const remove = el("button", "topo-remove", "×");
      remove.title = "删除链路";
      remove.onclick = () => {
        topo.links.splice(index, 1);
        renderTopology();
      };
      row.appendChild(text);
      row.appendChild(remove);
      box.appendChild(row);
    });
  }

  async function saveTopology() {
    if (topo.busy) return;
    const error = $("#topoError", topo.modal);
    error.classList.add("hidden");
    const title = ($("#topoTitle", topo.modal).value || "").trim();
    const subtitle = ($("#topoSubtitle", topo.modal).value || "").trim();
    const payload = {
      title, subtitle,
      devices: topo.devices,
      links: topo.links
    };
    if (!topo.copyOnly && topo.existingId) payload.id = topo.existingId;
    topo.busy = true;
    $("#topoSave", topo.modal).disabled = true;
    const result = await api("/api/topology/save", payload);
    topo.busy = false;
    $("#topoSave", topo.modal).disabled = false;
    if (!result.ok) {
      error.textContent = result.error || "保存失败";
      error.classList.remove("hidden");
      return;
    }
    closeModal(topo.modal.id);
    notify("沙箱已保存，请重新一键搭建");
    announce(result.lab);
  }

  // ---------------------------------------------------------------------
  // Web terminal
  // ---------------------------------------------------------------------
  const terminal = {
    modal: null, lab: null, socket: null, device: "", history: [], historyIndex: 0
  };

  function ensureTerminalModal() {
    if (terminal.modal) return terminal.modal;
    terminal.modal = modal("terminalModal", `
      <div class="modal-box studio-box terminal-box">
        <div class="studio-head">
          <div class="studio-title">
            <h3>Web 终端</h3>
            <p>行模式 console 会话；命令执行在当前设备视图，支持 system-view 等交互。</p>
          </div>
          <div class="studio-head-actions">
            <span id="termState" class="term-state">未连接</span>
            <button id="termReconnect" class="btn ghost">重连</button>
            <button class="x" data-close>×</button>
          </div>
        </div>
        <div id="termDevices" class="term-devices"></div>
        <pre id="termOut" class="term-out" tabindex="0"></pre>
        <div class="term-composer">
          <span class="term-prompt">&gt;</span>
          <input id="termInput" autocomplete="off" spellcheck="false" placeholder="输入命令，Enter 执行；↑↓ 翻历史，Ctrl+L 清屏">
          <button id="termSend" class="btn primary">执行</button>
        </div>
        <p class="studio-note">终端不会显示彩色图表或实时逐字符回显；长输出会完整回传。设备需先在 eNSP 中启动。</p>
      </div>`);
    $("#termSend", terminal.modal).onclick = sendTerminalCommand;
    $("#termReconnect", terminal.modal).onclick = () => connectTerminal(terminal.device);
    $("#termInput", terminal.modal).addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        sendTerminalCommand();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        terminal.historyIndex = Math.max(0, terminal.historyIndex - 1);
        $("#termInput", terminal.modal).value = terminal.history[terminal.historyIndex] || "";
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        terminal.historyIndex = Math.min(terminal.history.length, terminal.historyIndex + 1);
        $("#termInput", terminal.modal).value = terminal.history[terminal.historyIndex] || "";
      } else if (event.key.toLowerCase() === "l" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        $("#termOut", terminal.modal).textContent = "";
      }
    });
    terminal.modal.addEventListener("click", (event) => {
      if (event.target === terminal.modal) closeTerminal();
    });
    terminal.modal.querySelector("[data-close]").addEventListener("click", closeTerminal);
    return terminal.modal;
  }

  function terminalAppend(text, cls) {
    const out = $("#termOut", terminal.modal);
    const span = el("span", cls || "");
    span.textContent = text.endsWith("\n") ? text : text + "\n";
    out.appendChild(span);
    if (out.textContent.length > 250000) {
      out.textContent = out.textContent.slice(-180000);
    }
    out.scrollTop = out.scrollHeight;
  }

  function terminalState(text, bad) {
    const node = $("#termState", terminal.modal);
    node.textContent = text;
    node.classList.toggle("bad", !!bad);
  }

  async function openTerminal(lab) {
    ensureTerminalModal();
    if (!lab) return notify("先选一个实验");
    terminal.lab = lab;
    terminal.device = "";
    const status = await api(`/api/lab/${encodeURIComponent(lab.id)}/status`);
    const devices = (status.devices || []).filter((item) => item.port);
    const tabs = $("#termDevices", terminal.modal);
    tabs.innerHTML = "";
    if (!devices.length) {
      terminalState("设备未启动", true);
      tabs.appendChild(el("span", "studio-dim", "没有 console 设备。先在 eNSP 中点启动。"));
    } else {
      devices.forEach((item) => {
        const button = el("button", "term-device", `${item.name}${item.up ? "" : " · 未就绪"}`);
        button.classList.toggle("up", !!item.up);
        button.onclick = () => connectTerminal(item.name);
        button.dataset.device = item.name;
        tabs.appendChild(button);
      });
      terminal.device = devices[0].name;
    }
    $("#termOut", terminal.modal).textContent = "";
    openModal(terminal.modal.id);
    setTimeout(() => $("#termInput", terminal.modal).focus(), 60);
    if (terminal.device) connectTerminal(terminal.device);
    else terminalState("未连接", true);
  }

  async function connectTerminal(device) {
    if (!terminal.lab || !device) return;
    closeTerminalSocket();
    terminal.device = device;
    $("#termDevices", terminal.modal).querySelectorAll(".term-device").forEach((button) => {
      button.classList.toggle("on", button.dataset.device === device);
    });
    terminalState("连接中…", false);
    $("#termInput", terminal.modal).disabled = true;
    $("#termSend", terminal.modal).disabled = true;
    let token;
    try {
      token = await window.enspGetToken();
    } catch (err) {
      terminalState("会话失败", true);
      terminalAppend(err.message || "无法获取本地会话", "term-error");
      return;
    }
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${location.host}/ws/terminal?token=${encodeURIComponent(token)}` +
      `&lab_id=${encodeURIComponent(terminal.lab.id)}&device=${encodeURIComponent(device)}`;
    const socket = new WebSocket(url);
    terminal.socket = socket;
    socket.onopen = () => {
      terminalState("设备连接中…", false);
      $("#termInput", terminal.modal).disabled = true;
      $("#termSend", terminal.modal).disabled = true;
    };
    socket.onmessage = (event) => {
      let data;
      try { data = JSON.parse(event.data); } catch (err) { return; }
      if (data.type === "ready") {
        terminalAppend(`--- ${data.device} 已连接 ---`, "term-system");
        if (data.output) terminalAppend(data.output);
        terminalState("已连接", false);
        $("#termInput", terminal.modal).disabled = false;
        $("#termSend", terminal.modal).disabled = false;
        $("#termInput", terminal.modal).focus();
      } else if (data.type === "output") {
        if (data.output) terminalAppend(data.output);
      } else if (data.type === "error") {
        terminalAppend(data.message || "执行失败", "term-error");
      } else if (data.type === "closed") {
        terminalState("已断开", true);
      }
    };
    socket.onerror = () => terminalState("连接失败", true);
    socket.onclose = () => {
      if (terminal.socket !== socket) return;
      terminal.socket = null;
      terminalState("已断开", true);
      $("#termInput", terminal.modal).disabled = true;
      $("#termSend", terminal.modal).disabled = true;
    };
  }

  function closeTerminalSocket() {
    if (terminal.socket) {
      try { terminal.socket.close(); } catch (err) {}
      terminal.socket = null;
    }
  }

  function closeTerminal() {
    closeTerminalSocket();
    closeModal(terminal.modal.id);
  }

  function sendTerminalCommand() {
    const input = $("#termInput", terminal.modal);
    const command = (input.value || "").trim();
    if (!command || !terminal.socket || terminal.socket.readyState !== WebSocket.OPEN) return;
    terminal.history.push(command);
    terminal.historyIndex = terminal.history.length;
    input.value = "";
    terminal.socket.send(JSON.stringify({ type: "command", command }));
  }

  // ---------------------------------------------------------------------
  // Snapshots
  // ---------------------------------------------------------------------
  const snapshots = { modal: null, lab: null, items: [], busy: false };

  function ensureSnapshotModal() {
    if (snapshots.modal) return snapshots.modal;
    snapshots.modal = modal("snapshotModal", `
      <div class="modal-box studio-box snapshot-box">
        <div class="studio-head">
          <div class="studio-title">
            <h3>配置快照</h3>
            <p>保存所有 console 设备的运行配置，稍后可逐台重放。恢复前会自动再存一份。</p>
          </div>
          <button class="x" data-close>×</button>
        </div>
        <div class="snapshot-capture">
          <input id="snapLabel" maxlength="80" placeholder="快照名称，例如：OSPF 完成态">
          <button id="snapCapture" class="btn primary">保存当前配置</button>
        </div>
        <p class="studio-note">重放会覆盖同名配置并保留快照外现有配置，不会清空整机。配置可能含口令，请勿公开分享沙箱包。</p>
        <div id="snapList" class="snapshot-list"></div>
        <pre id="snapDetail" class="snapshot-detail hidden"></pre>
      </div>`);
    $("#snapCapture", snapshots.modal).onclick = captureSnapshot;
    return snapshots.modal;
  }

  async function openSnapshots(lab) {
    ensureSnapshotModal();
    if (!lab) return notify("先选一个实验");
    snapshots.lab = lab;
    $("#snapLabel", snapshots.modal).value = "";
    $("#snapDetail", snapshots.modal).classList.add("hidden");
    openModal(snapshots.modal.id);
    await loadSnapshotList();
  }

  async function loadSnapshotList() {
    const result = await api(`/api/lab/${encodeURIComponent(snapshots.lab.id)}/snapshots`);
    snapshots.items = result.items || [];
    const box = $("#snapList", snapshots.modal);
    box.innerHTML = "";
    if (!snapshots.items.length) {
      box.appendChild(el("p", "studio-empty", "还没有快照。设备启动并配置后点「保存当前配置」。"));
      return;
    }
    snapshots.items.forEach((item) => {
      const row = el("div", "snapshot-row");
      const main = el("div", "snapshot-main");
      main.appendChild(el("b", null, item.label || "未命名快照"));
      main.appendChild(el("small", null, `${fmtTime(item.at)} · ${item.devices} 台设备${item.variant ? " · " + item.variant : ""}`));
      const actions = el("div", "snapshot-actions");
      const view = el("button", "btn ghost", "查看");
      const restore = el("button", "btn", "恢复");
      const del = el("button", "btn ghost studio-danger", "删除");
      view.onclick = () => viewSnapshot(item.id);
      restore.onclick = () => restoreSnapshot(item);
      del.onclick = () => deleteSnapshot(item);
      actions.appendChild(view);
      actions.appendChild(restore);
      actions.appendChild(del);
      row.appendChild(main);
      row.appendChild(actions);
      box.appendChild(row);
    });
  }

  async function viewSnapshot(id) {
    const result = await api(`/api/lab/${encodeURIComponent(snapshots.lab.id)}/snapshots/${encodeURIComponent(id)}`);
    if (!result || result.ok === false || !result.devices) return notify(result.error || "读取快照失败");
    const text = Object.entries(result.devices).map(([name, info]) =>
      `===== ${name} =====\n${info.config || ""}`).join("\n\n");
    const detail = $("#snapDetail", snapshots.modal);
    detail.textContent = text;
    detail.classList.remove("hidden");
  }

  async function captureSnapshot() {
    if (snapshots.busy) return;
    snapshots.busy = true;
    const button = $("#snapCapture", snapshots.modal);
    button.disabled = true;
    const result = await api(`/api/lab/${encodeURIComponent(snapshots.lab.id)}/snapshots`,
      { label: ($("#snapLabel", snapshots.modal).value || "").trim() });
    snapshots.busy = false;
    button.disabled = false;
    if (!result.ok) return notify(result.error || "快照失败");
    $("#snapLabel", snapshots.modal).value = "";
    notify("配置快照已保存");
    await loadSnapshotList();
  }

  async function restoreSnapshot(item) {
    if (!confirm(`恢复「${item.label}」？\n\n会逐台重放快照配置，并在恢复前自动保存当前状态。`)) return;
    const result = await api(`/api/lab/${encodeURIComponent(snapshots.lab.id)}/snapshots/${encodeURIComponent(item.id)}/restore`, { confirm: true });
    if (!result.ok) {
      const detail = (result.report || []).map((row) => `${row.dev}: ${row.message}`).join("；");
      return notify((result.error || "恢复失败") + (detail ? "；" + detail : ""));
    }
    const warnings = (result.report || []).reduce((total, row) => total + (row.warnings || []).length, 0);
    notify("快照已重放，自动留档已生成" + (warnings ? `，${warnings} 条平台默认项已跳过` : ""));
    await loadSnapshotList();
  }

  async function deleteSnapshot(item) {
    if (!confirm(`删除快照「${item.label}」？`)) return;
    const result = await api(`/api/lab/${encodeURIComponent(snapshots.lab.id)}/snapshots/${encodeURIComponent(item.id)}/delete`, {});
    if (!result.ok) return notify(result.error || "删除失败");
    await loadSnapshotList();
  }

  // ---------------------------------------------------------------------
  // Sandbox
  // ---------------------------------------------------------------------
  async function exportSandbox(lab) {
    if (!lab) return notify("先选一个实验");
    try {
      const response = await window.enspFetch(`/api/lab/${encodeURIComponent(lab.id)}/export-sandbox`);
      if (!response.ok) throw new Error("导出失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${(lab.title || "sandbox").replace(/[\\/:*?"<>|]/g, "_")}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      setTimeout(() => { URL.revokeObjectURL(url); anchor.remove(); }, 1000);
      notify("沙箱包已导出");
    } catch (err) {
      notify("导出失败：" + (err.message || err));
    }
  }

  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const chunks = [];
    for (let i = 0; i < bytes.length; i += 0x8000) {
      chunks.push(String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000)));
    }
    return btoa(chunks.join(""));
  }

  function chooseSandboxImport() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip,application/zip";
    input.onchange = async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      if (file.size > 4 * 1024 * 1024) return notify("沙箱文件不能超过 4MB");
      try {
        const buffer = await file.arrayBuffer();
        const result = await api("/api/sandbox/import", { data: toBase64(buffer) });
        if (!result.ok) return notify(result.error || "导入失败");
        notify(`沙箱已导入${result.snapshots ? "，含 " + result.snapshots + " 个快照" : ""}`);
        announce(result.lab);
      } catch (err) {
        notify("导入失败：" + (err.message || err));
      }
    };
    input.click();
  }

  window.Studio = {
    openTopology,
    openTerminal,
    openSnapshots,
    exportSandbox,
    chooseSandboxImport
  };
})();
