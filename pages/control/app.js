// Group Chat Plus Lite — 插件页控制台（分组 tab 分页版）
const bridge = window.AstrBotPluginPage;
const state = { values: {}, runtime: {}, version: "", groups: [] };
let activeIdx = 0;       // 当前显示的分组下标
let configDirty = false; // 当前面板是否有未保存改动

const $ = (sel) => document.querySelector(sel);
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function stripEmoji(s) {
  const m = String(s ?? "").match(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}][\u{FE0F}]?/u);
  return (m ? String(s).replace(m[0], "") : String(s ?? "")).trim();
}

/* ============ 分组主开关（卡片徽章判定） ============ */
const MASTERS = {
  gcp_basic: "enable_group_chat",
  gcp_decision: null,
  gcp_trigger: null,
  gcp_reply: null,
  gcp_manage: { any: ["enable_user_blacklist", "enable_command_filter"] },
  gcp_concurrent: null,
  gcp_enhance: { any: ["enable_image_processing", "enable_memory_injection", "enable_emoji_filter"] },
};
function isMasterOn(master) {
  if (!master) return true;
  if (typeof master === "string") return !!state.values[master];
  if (master.any) return master.any.some((k) => !!state.values[k]);
  if (master.neq) return state.values[master.key] !== master.neq;
  return true;
}

/* ============ 流水线环节 → 分组映射（新分组 id） ============ */
const STAGE_ORDER = [
  { id: "probability", icon: "🎲", title: "读空气概率" },
  { id: "command", icon: "🎛️", title: "触发&过滤" },
  { id: "at", icon: "📢", title: "@必回" },
  { id: "decision", icon: "🧠", title: "AI判断" },
  { id: "reply", icon: "💬", title: "回复生成" },
];
const STAGE_GROUPS = {
  probability: "gcp_decision",
  command: "gcp_trigger",
  at: "gcp_manage",
  decision: "gcp_decision",
  reply: "gcp_reply",
};

/* ============ 分组摘要 ============ */
function groupSummary(gid) {
  const v = state.values;
  switch (gid) {
    case "gcp_basic": return `总开关${v.enable_group_chat ? "开" : "关"} · ${(v.enabled_groups || []).length} 个群`;
    case "gcp_decision": return `随机${v.enable_random_probability_filter ? "开" : "AI主导"} · 倾向 ${v.decision_ai_reply_tendency ?? "persona"}`;
    case "gcp_trigger": return `触发词 ${(v.trigger_keywords || []).length} 条`;
    case "gcp_reply": return `上下文 ${v.max_context_messages ?? "-"} 条 · 防复读${v.enable_duplicate_filter ? "开" : "关"}`;
    case "gcp_manage": return `黑名单 ${(v.blacklist_user_ids || []).length} 人`;
    case "gcp_concurrent": return `${v.concurrent_mode ?? "legacy"} 模式`;
    case "gcp_enhance": return "图片 / 记忆 / 表情 / 戳一戳";
    default: return "";
  }
}

/* ============ 字段元数据 ============ */
const META = {};
function buildMeta(groups) {
  Object.keys(META).forEach((k) => delete META[k]);
  (groups || []).forEach((g) => {
    Object.entries(g.items || {}).forEach(([k, m]) => {
      META[k] = { label: m.description || k, type: m.type || "string", options: m.options || null, hint: m.hint || "" };
    });
  });
}

/* ============ 入口渲染 ============ */
function renderHeader() {
  $("#ver").textContent = state.version || "…";
  const on = !!state.values.enable_group_chat;
  $("#dotMain").className = "dot" + (on ? "" : " off");
  $("#mainSwitch").textContent = "群聊回复：" + (on ? "启用" : "停用");
  $("#tendencyPill").textContent = "倾向：" + (state.values.decision_ai_reply_tendency ?? "persona");
  $("#smartPill").textContent = "并发：" + (state.values.concurrent_mode ?? "legacy");
}

function renderPipeline() {
  $("#pipeline").innerHTML = STAGE_ORDER.map((s, idx) => {
    const html = `
      <div class="capsule" data-stage="${s.id}" role="button" tabindex="0">
        <span class="num">${idx + 1}</span>
        <div class="cap-name">${s.icon} ${s.title}</div>
        <div class="cap-state">${esc(groupsById(STAGE_GROUPS[s.id]) ? groupSummary(STAGE_GROUPS[s.id]) : "")}</div>
      </div>`;
    return idx < STAGE_ORDER.length - 1 ? html + `<div class="arrow">→</div>` : html;
  }).join("");
  $("#pipeline").querySelectorAll(".capsule").forEach((el) => {
    const act = () => { const gid = STAGE_GROUPS[el.dataset.stage]; if (gid) goToGroup(gid); };
    el.addEventListener("click", act);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") act(); });
  });
}

const groupIdList = () => (state.groups || []).map((g) => g.id);
function groupById(gid) { return (state.groups || []).find((g) => g.id === gid); }
function groupsById(gids) { return (Array.isArray(gids) ? gids : [gids]).map(groupById).filter(Boolean).length; }

/* ============ 配置：tab + 分页 ============ */
function renderTabs() {
  $("#tabs").innerHTML = (state.groups || []).map((g, idx) => {
    const on = isMasterOn(MASTERS[g.id]);
    return `<button class="tab ${idx === activeIdx ? "active" : ""}" data-tab="${idx}">
      <span class="tab-em">${(g.title || "").match(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}][\u{FE0F}]?/u)?.[0] || "📦"}</span>
      <span class="tab-name">${esc(stripEmoji(g.title || g.id))}</span>
      <span class="dot ${on ? "" : " off"}"></span>
    </button>`;
  }).join("");
  $("#tabs").querySelectorAll(".tab").forEach((el) => {
    el.addEventListener("click", () => selectTab(Number(el.dataset.tab)));
  });
}

function renderGroup() {
  const groups = state.groups || [];
  if (!groups.length) return;
  activeIdx = Math.max(0, Math.min(activeIdx, groups.length - 1));
  const g = groups[activeIdx];
  renderTabs();
  const keys = Object.keys(g.items || {});
  const on = isMasterOn(MASTERS[g.id]);
  $("#configPanel").innerHTML = `
    <div class="panel-head">
      <h3>${esc(g.title || g.id)}</h3>
      <span class="badge ${on ? "on" : "off"}">${on ? "已启用" : "已关闭"}</span>
    </div>
    <div class="form-grid">${keys.map(fieldControl).join("")}</div>
    <div class="save-bar">
      <span class="save-status" id="saveStatus">${configDirty ? "⚠️ 有未保存改动" : "修改后点击保存生效"}</span>
      <button class="btn" id="saveBtn">保存本组</button>
    </div>`;
  $("#configPanel").querySelector("#saveBtn").addEventListener("click", saveGroup);
  // 改动标记
  $("#configPanel").querySelectorAll("[data-key]").forEach((el) => {
    el.addEventListener("input", () => { configDirty = true; const s = $("#saveStatus"); if (s) s.textContent = "⚠️ 有未保存改动"; });
  });
  bindHints(); // 每次重绘后重新绑定 ⓘ 说明
}

function selectTab(idx) {
  if (configDirty && !confirm("当前分组有未保存的改动，切换将丢弃。确定继续？")) return;
  configDirty = false;
  activeIdx = idx;
  renderGroup();
}

function goToGroup(gid) {
  const idx = groupIdList().indexOf(gid);
  if (idx >= 0) { configDirty = false; activeIdx = idx; renderGroup(); }
}

/* ============ 字段控件（长说明收进 ⓘ） ============ */
function fieldControl(key) {
  const def = META[key] || { label: key, type: "string", hint: "" };
  const val = state.values[key];
  const label = `<span class="field-label">${esc(def.label)}</span>${def.hint ? `<span class="hint-ico" data-hint="${esc(def.hint)}" title="点击查看说明">ⓘ</span>` : ""}`;
  let ctrl = "";
  if (def.type === "bool") {
    ctrl = `<label class="switch"><input type="checkbox" data-key="${key}" ${val ? "checked" : ""} /><span class="slider"></span></label>`;
  } else if (def.type === "select" || (def.options && def.options.length)) {
    const opts = (def.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("");
    ctrl = `<select data-key="${key}">${opts}</select>`;
  } else if (def.type === "list") {
    ctrl = `<textarea data-key="${key}" rows="4" placeholder="每行一项">${esc(Array.isArray(val) ? val.join("\n") : val || "")}</textarea>`;
  } else if (def.type === "int" || def.type === "float") {
    const step = def.step ?? (def.type === "int" ? 1 : 0.01);
    ctrl = `<input type="number" data-key="${key}" value="${esc(val)}" min="${def.min ?? ""}" max="${def.max ?? ""}" step="${step}" />`;
  } else if (def.type === "text" || (def.type === "string" && String(def.label).length > 6 && typeof val === "string" && val && val.includes("\n"))) {
    ctrl = `<textarea data-key="${key}" rows="5">${esc(val ?? "")}</textarea>`;
  } else {
    ctrl = `<input type="text" data-key="${key}" value="${esc(val ?? "")}" />`;
  }
  return `<div class="field">${label}${ctrl}</div>`;
}

/* ============ 保存 ============ */
async function saveGroup() {
  const btn = $("#saveBtn");
  btn.disabled = true;
  const updates = {};
  $("#configPanel").querySelectorAll("[data-key]").forEach((el) => {
    const key = el.dataset.key;
    const def = META[key] || { type: "string" };
    if (def.type === "bool") updates[key] = el.checked;
    else if (def.type === "int") updates[key] = parseInt(el.value, 10);
    else if (def.type === "float") updates[key] = parseFloat(el.value);
    else if (def.type === "list") updates[key] = el.value.split("\n").map((s) => s.trim()).filter(Boolean);
    else updates[key] = el.value;
  });
  try {
    const res = await bridge.apiPost("config/save", { updates });
    const data = res && res.data !== undefined ? res.data : res;
    if (data && data.applied) {
      toast(`已保存 ${data.applied.length} 项${data.skipped && data.skipped.length ? "，忽略 " + data.skipped.length + " 项" : ""}`, "ok");
      Object.assign(state.values, updates);
      configDirty = false;
      renderGroup();
    } else {
      toast("保存失败：" + ((res && res.message) || "未知错误"), "err");
    }
  } catch (err) {
    toast("保存失败：" + err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

/* ============ ⓘ 说明小框 ============ */
function bindHints() {
  const root = $("#configPanel");
  root.querySelectorAll(".hint-ico").forEach((ico) => {
    ico.addEventListener("click", (e) => {
      e.stopPropagation();
      const text = ico.dataset.hint || "";
      const box = $("#tipBox");
      box.textContent = text;
      box.classList.toggle("show");
      if (box.classList.contains("show")) {
        const r = ico.getBoundingClientRect();
        box.style.top = (r.bottom + 6 + window.scrollY) + "px";
        box.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 320)) + "px";
      }
    });
  });
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".hint-ico")) $("#tipBox").classList.remove("show");
});

/* ============ 提示词预览 ============ */
async function renderPrompts() {
  try {
    const res = await bridge.apiGet("prompts");
    const data = res && res.data !== undefined ? res.data : res;
    if (!data) return;
    const modeText = (m) => (m === "override" ? "override · 自定义覆盖" : "append · 默认拼接");
    const modeDesc = (m) =>
      m === "override" ? "留空 = 使用默认提示词；填写后完全替换默认提示词" : "留空 = 使用默认提示词；填写后追加在默认提示词之后";
    const card = (title, icon, p, cfgKey) => `
      <div class="prompt-card">
        <h3>${icon} ${title}</h3>
        <div class="meta">模式：${modeText(p.mode)} · ${p.has_custom ? "已配置自定义提示词" : "使用默认提示词"}</div>
        <textarea data-prompt-edit="${cfgKey}" rows="4" placeholder="在这里输入你的自定义提示词…">${esc(p.extra)}</textarea>
        <div class="row">
          <span class="save-status" data-prompt-status="${cfgKey}">${modeDesc(p.mode)}</span>
          <button class="btn" data-prompt-save="${cfgKey}">保存</button>
        </div>
        <details class="prompt-preview">
          <summary>👁️ 生效提示词预览（只读）</summary>
          <pre>${esc(p.text)}</pre>
        </details>
      </div>`;
    $("#promptGrid").innerHTML =
      card("读空气判断提示词", "🧠", data.decision || { mode: "append", has_custom: false, extra: "", text: "" }, "decision_ai_extra_prompt") +
      card("回复生成提示词", "💬", data.reply || { mode: "append", has_custom: false, extra: "", text: "" }, "reply_ai_extra_prompt");
    $("#promptGrid").querySelectorAll("[data-prompt-save]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const key = btn.dataset.promptSave;
        const ta = document.querySelector(`textarea[data-prompt-edit="${key}"]`);
        const status = document.querySelector(`[data-prompt-status="${key}"]`);
        if (!ta || !status) return;
        btn.disabled = true;
        status.textContent = "保存中…";
        try {
          const res = await bridge.apiPost("config/save", { updates: { [key]: ta.value } });
          const data = res && res.data !== undefined ? res.data : res;
          if (data && data.applied && data.applied.includes(key)) {
            status.textContent = "✅ 已保存";
            toast("提示词已保存", "ok");
            await renderPrompts();
          } else {
            status.textContent = "保存失败：" + ((res && res.message) || "未知错误");
          }
        } catch (err) {
          status.textContent = "保存失败：" + err.message;
        } finally {
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    $("#promptGrid").innerHTML = `<div class="prompt-card">提示词加载失败：${esc(err.message)}</div>`;
  }
}

/* ============ toast ============ */
let toastTimer = null;
function toast(msg, type) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show " + (type || "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
}

/* ============ 启动 ============ */
function renderAll() {
  renderHeader();
  renderTabs();
  renderGroup();
  renderPipeline();
}

async function loadStatus() {
  try {
    const res = await bridge.apiGet("status");
    const data = res && res.data !== undefined ? res.data : res;
    if (!data) throw new Error("status 返回为空");
    state.version = data.version || "";
    state.values = data.values || {};
    state.runtime = data.runtime || {};
    state.groups = data.groups || [];
    buildMeta(state.groups);
    renderAll();
  } catch (err) {
    $("#mainSwitch").textContent = "状态加载失败：" + err.message;
    toast("状态加载失败：" + err.message, "err");
  }
}

async function init() {
  try { await bridge.ready(); } catch (e) { /* 非 iframe 环境也能加载 */ }
  await loadStatus();
  renderPrompts();
}

init();
