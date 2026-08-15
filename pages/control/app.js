// Group Chat Plus Lite — 插件页控制台（卡片式/胶囊式）
const bridge = window.AstrBotPluginPage;

const state = { values: {}, runtime: {}, version: "", groups: [] };

/* ================= 隐藏参数定义（不在 _conf_schema.json，插件页补充收纳） ================= */
const EXTRA_META = {
  custom_storage_max_messages: { label: "自建存储最大消息数", type: "int", min: 10, hint: "插件自建历史存储的最大消息条数" },
  decision_ai_persona_name: { label: "判断指定人格", type: "string", hint: "留空=使用当前人格" },
  decision_ai_reasoning_log: { label: "思考过程写日志", type: "bool", hint: "将读空气判断的思考过程写入插件日志" },
  decision_ai_reasoning_log_mode: { label: "思考日志模式", type: "string", hint: "console / file" },
  enable_decision_ai_reasoning: { label: "判断输出思考过程", type: "bool", hint: "让判断AI先输出思考再给 yes/no" },
  judgment_reasoning_start_marker: { label: "思考开始标记", type: "string", hint: "解析思考过程的起始标记" },
  judgment_reasoning_end_marker: { label: "思考结束标记", type: "string", hint: "解析思考过程的结束标记" },
  enable_full_command_detection: { label: "完整指令检测", type: "bool", hint: "识别完整指令列表中的指令" },
  enable_command_prefix_match: { label: "指令前缀匹配", type: "bool", hint: "按前缀匹配指令" },
  at_all_probability_boost_value: { label: "@全体概率加成", type: "float", min: 0, max: 1, step: 0.01, hint: "@全体成员消息的临时概率提升值" },
  enable_duplicate_time_limit: { label: "复读时效限制", type: "bool", hint: "重复检测附带时效窗口" },
  probability_filter_cache_delay: { label: "概率过滤缓存延迟(ms)", type: "int", min: 0, hint: "概率过滤阶段的缓存延迟" },
  reply_timeout_warning_threshold: { label: "回复超时告警阈值(秒)", type: "int", min: 1, hint: "超过该时长输出告警日志" },
  reply_generation_timeout_warning: { label: "回复生成超时告警(秒)", type: "int", min: 1, hint: "生成回复阶段的超时告警" },
  enable_welcome_message_parsing: { label: "新成员入群解析", type: "bool", hint: "解析新成员入群消息" },
  welcome_message_mode: { label: "欢迎消息模式", type: "string", hint: "处理新成员消息的方式" },
  gcp_clear_image_cache_allowed_user_ids: { label: "允许清图缓存的用户", type: "list", hint: "每行一个用户ID" },
  ignore_at_others_mode: { label: "忽略@他人模式", type: "string", hint: "strict / loose" },
  platform_image_caption_fast_check_count: { label: "平台图述快速检查次数", type: "int", min: 1, hint: "快速检查平台图片描述的最大次数" },
  poke_bot_probability_boost_reference: { label: "被戳概率加成参考", type: "float", min: 0, max: 1, step: 0.01, hint: "被戳时概率加成的参考值" },
  max_images_per_message: { label: "单条消息最大图片数", type: "int", min: 1, max: 50, hint: "单条消息最多处理几张图片" },
};

/* ================= 分组主开关（卡片"已启用/已关闭"徽章判定） ================= */
const MASTERS = {
  gcp_section_basic: "enable_group_chat",
  gcp_section_probability: null,
  gcp_section_decision: null,
  gcp_section_reply: null,
  gcp_section_forward: "enable_forward_message_parsing",
  gcp_section_image: "enable_image_processing",
  gcp_section_memory: "enable_memory_injection",
  gcp_section_keyword: null,
  gcp_section_filter: { any: ["enable_user_blacklist", "enable_command_filter", "enable_ignore_at_others", "enable_ignore_at_all"] },
  gcp_section_emoji: "enable_emoji_filter",
  gcp_section_poke: { key: "poke_message_mode", neq: "ignore" },
  gcp_section_duplicate: "enable_duplicate_filter",
  gcp_section_concurrent: null,
  gcp_section_content_filter: { any: ["enable_output_content_filter", "enable_save_content_filter"] },
  gcp_extra: null,
};

/* ================= 流水线环节（常驻启用）→ 分组映射 ================= */
const STAGE_ORDER = [
  { id: "probability", icon: "🎲", title: "概率筛选" },
  { id: "command", icon: "🎛️", title: "指令&关键词" },
  { id: "at", icon: "📢", title: "@必回处理" },
  { id: "decision", icon: "🧠", title: "读空气AI判断" },
  { id: "reply", icon: "💬", title: "回复生成" },
];
const STAGE_GROUPS = {
  probability: ["gcp_section_probability"],
  command: ["gcp_section_keyword", "gcp_section_filter"],
  at: ["gcp_section_filter"],
  decision: ["gcp_section_decision"],
  reply: ["gcp_section_reply"],
};

/* ================= 分组摘要（卡片副标题） ================= */
function groupSummary(gid, keys) {
  const v = state.values;
  switch (gid) {
    case "gcp_section_basic": return `总开关${v.enable_group_chat ? "开" : "关"} · ${(v.enabled_groups || []).length} 个群`;
    case "gcp_section_probability": return `初始 ${v.initial_probability ?? "-"}`;
    case "gcp_section_decision": return `倾向 ${v.decision_ai_reply_tendency ?? "persona"} · 超时 ${v.decision_ai_timeout ?? "-"}s`;
    case "gcp_section_reply": return `上下文 ${v.max_context_messages ?? "-"} 条`;
    case "gcp_section_forward": return `嵌套深度 ${v.forward_max_nesting_depth ?? "-"}`;
    case "gcp_section_image": return `范围 ${v.image_to_text_scope ?? "-"}`;
    case "gcp_section_memory": return `${v.memory_plugin_mode ?? "-"} · top${v.livingmemory_top_k ?? "-"}`;
    case "gcp_section_keyword": return `触发关键词 ${(v.trigger_keywords || []).length} 条`;
    case "gcp_section_filter": return `黑名单 ${(v.blacklist_user_ids || []).length} 人`;
    case "gcp_section_emoji": return `衰减 ${v.emoji_probability_decay ?? "-"}`;
    case "gcp_section_poke": return `模式 ${v.poke_message_mode ?? "-"}`;
    case "gcp_section_duplicate": return `检查 ${v.duplicate_filter_check_count ?? "-"} 条`;
    case "gcp_section_concurrent": return `${v.concurrent_mode ?? "legacy"} · 合并 ${v.smart_concurrent_merge_wait ?? "-"}s`;
    case "gcp_section_content_filter": return `输出${v.enable_output_content_filter ? "开" : "关"}`;
    case "gcp_extra": return `${keys.length} 项高级参数`;
    default: return `${keys.length} 项配置`;
  }
}

/* 分组字段元数据（由 status 返回的 schema 分组动态构建 + EXTRA_META 补充） */
const META = {};
function buildMeta(groups) {
  Object.keys(META).forEach((k) => delete META[k]);
  (groups || []).forEach((g) => {
    Object.entries(g.items || {}).forEach(([k, m]) => {
      META[k] = { label: m.description || k, type: m.type || "string", options: m.options || null, hint: m.hint || "" };
    });
  });
  Object.assign(META, EXTRA_META);
}


const $ = (sel) => document.querySelector(sel);

/* ================= 渲染 ================= */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderHeader() {
  $("#ver").textContent = state.version || "…";
  const on = !!state.values.enable_group_chat;
  $("#dotMain").className = "dot" + (on ? "" : " off");
  $("#mainSwitch").textContent = "群聊回复：" + (on ? "启用" : "已停用");
  $("#tendencyPill").textContent = "倾向：" + (state.values.decision_ai_reply_tendency ?? "persona");
  $("#smartPill").textContent = "并发：" + (state.values.concurrent_mode ?? "legacy");
}

function renderStats() {
  const rt = state.runtime || {};
  const boxes = [
    ["运行版本", state.version || "-"],
    ["概率状态会话", rt.probability_session_count ?? "-"],
    ["Smart 批次快照", rt.smart_batch_snapshot_count ?? "-"],
    ["处理中会话", rt.processing_session_count ?? "-"],
  ];
  $("#statsRow").innerHTML = boxes.map(([k, v]) => `<div class="stat-box"><div class="v">${esc(v)}</div><div class="k">${esc(k)}</div></div>`).join("");
}

/* 主开关判定：master=null 视为常驻启用；字符串=布尔开关；{key,neq}/{key,eq}/{any:[...]} 为组合判定 */
function isMasterOn(master) {
  if (!master) return true;
  if (typeof master === "string") return !!state.values[master];
  if (master.any) return master.any.some((k) => !!state.values[k]);
  if (master.neq) return state.values[master.key] !== master.neq;
  if (master.eq) return state.values[master.key] === master.eq;
  return true;
}

function stageSummary(stageId) {
  const v = state.values;
  if (stageId === "probability") return `初始 ${v.initial_probability ?? "-"}`;
  if (stageId === "command") return `关键词${(v.trigger_keywords || []).length}条`;
  if (stageId === "at") return `忽略@他人${v.enable_ignore_at_others ? "开" : "关"}`;
  if (stageId === "decision") return `倾向 ${v.decision_ai_reply_tendency ?? "persona"}`;
  if (stageId === "reply") return `上下文 ${v.max_context_messages ?? "-"}条`;
  return "";
}

function renderPipeline() {
  $("#pipeline").innerHTML = STAGE_ORDER.map((s, idx) => {
    const html = `
      <div class="capsule" data-stage="${s.id}" role="button" tabindex="0">
        <span class="num">${idx + 1}</span>
        <div class="cap-name">${s.icon} ${s.title}</div>
        <div class="cap-state"><span class="dot on"></span>${esc(stageSummary(s.id))}</div>
      </div>`;
    return idx < STAGE_ORDER.length - 1 ? html + `<div class="arrow">→</div>` : html;
  }).join("");
  $("#pipeline").querySelectorAll(".capsule").forEach((el) => {
    el.addEventListener("click", () => toggleStagePanel(el.dataset.stage, el));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") toggleStagePanel(el.dataset.stage, el); });
  });
}

function cardOn(card) {
  return isMasterOn(MASTERS[card.id]);
}

function renderCards() {
  $("#cards").innerHTML = (state.groups || []).map((g) => {
    const on = cardOn(g);
    const keys = Object.keys(g.items || {});
    const emoji = (g.title || "").match(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}][\u{FE0F}]?/u)?.[0] || "📦";
    const name = (g.title || g.id).replace(emoji, "").replace(/^\s+/, "").trim() || g.id;
    return `
      <div class="card" data-card="${g.id}" role="button" tabindex="0">
        <div class="card-head">
          <span class="icon">${emoji}</span>
          <span class="name">${esc(name)}</span>
          <span class="badge ${on ? "on" : "off"}">${on ? "已启用" : "已关闭"}</span>
        </div>
        <div class="card-summary">${esc(groupSummary(g.id, keys))}</div>
      </div>`;
  }).join("");
  $("#cards").querySelectorAll(".card").forEach((el) => {
    el.addEventListener("click", () => toggleCardPanel(el.dataset.card, el));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") toggleCardPanel(el.dataset.card, el); });
  });
}

/* ================= 编辑面板 ================= */
function fieldControl(key) {
  const def = META[key] || { label: key, type: "string" };
  const val = state.values[key];
  const title = `<div class="field-title">${esc(def.label)}</div>`;
  const hint = def.hint ? `<div class="field-hint">${esc(def.hint)}</div>` : "";
  if (def.type === "bool") {
    return `
      <div class="field">
        ${title}
        <label class="switch"><input type="checkbox" data-key="${key}" ${val ? "checked" : ""} /><span class="slider"></span></label>
        ${hint}
      </div>`;
  }
  if (def.type === "select" || (def.options && def.options.length)) {
    const opts = (def.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("");
    return `
      <div class="field">
        ${title}
        <select data-key="${key}">${opts}</select>
        ${hint}
      </div>`;
  }
  if (def.type === "list") {
    const listVal = Array.isArray(val) ? val.join("\n") : (val ? String(val) : "");
    return `
      <div class="field">
        ${title}
        <textarea data-key="${key}" rows="5" placeholder="每行一项">${esc(listVal)}</textarea>
        ${hint}
      </div>`;
  }
  const num = def.type === "int" || def.type === "float";
  if (num) {
    const step = def.step ?? (def.type === "int" ? 1 : 0.01);
    return `
      <div class="field">
        ${title}
        <input type="number" data-key="${key}" value="${esc(val)}" min="${def.min ?? ""}" max="${def.max ?? ""}" step="${step}" />
        ${hint}
      </div>`;
  }
  if (def.type === "text") {
    return `
      <div class="field">
        ${title}
        <textarea data-key="${key}" rows="5">${esc(val)}</textarea>
        ${hint}
      </div>`;
  }
  return `
    <div class="field">
      ${title}
      <input type="text" data-key="${key}" value="${esc(val)}" />
      ${hint}
    </div>`;
}

function buildPanel(title, keys, onSave) {
  const wrap = document.createElement("div");
  wrap.className = "edit-panel";
  wrap.innerHTML = `
    <h3>${title}</h3>
    <div class="form-grid">${keys.map(fieldControl).join("")}</div>
    <div class="save-bar">
      <div class="save-status">修改后点击保存，配置即时写入并生效。</div>
      <button class="btn">保存</button>
    </div>`;
  const btn = wrap.querySelector(".btn");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    const updates = {};
    wrap.querySelectorAll("[data-key]").forEach((el) => {
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
        const keep = activePanel ? { key: activePanel.key, id: activePanel.id } : null;
        closeActive();
        renderAll();
        if (keep) {
          const sel = keep.key === "stage" ? `[data-stage="${keep.id}"]` : `[data-card="${keep.id}"]`;
          const targetEl = document.querySelector(sel);
          if (targetEl) {
            if (keep.key === "stage") toggleStagePanel(keep.id, targetEl);
            else toggleCardPanel(keep.id, targetEl);
          }
        }
      } else {
        toast("保存失败：" + (res && res.message ? res.message : "未知错误"), "err");
      }
    } catch (err) {
      toast("保存失败：" + err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });
  return wrap;
}

/* 流水线/卡片面板的展开收起（互斥）
   注意：面板使用页面中固定的容器（#stagePanelWrap / #cardPanelWrap），
   关闭时只清空容器内容，容器本身保留——避免 replaceWith 目标丢失导致点击无响应 */
let activePanel = null; // { el, wrap, key, id }
const stageWrapEl = document.getElementById("stagePanelWrap");
const cardWrapEl = document.getElementById("cardPanelWrap");

function closeActive() {
  if (!activePanel) return;
  if (activePanel.el && activePanel.el.classList) {
    activePanel.el.classList.remove("active");
  }
  if (activePanel.wrap) activePanel.wrap.innerHTML = "";
  activePanel = null;
}

function groupById(gid) {
  return (state.groups || []).find((g) => g.id === gid);
}

function toggleStagePanel(stageId, el) {
  if (activePanel && activePanel.el === el) { closeActive(); return; }
  closeActive();
  stageWrapEl.innerHTML = "";
  const gids = STAGE_GROUPS[stageId] || [];
  gids.forEach((gid) => {
    const g = groupById(gid);
    if (!g) return;
    stageWrapEl.appendChild(buildPanel(`${g.title} · 配置`, Object.keys(g.items || {})));
  });
  el.classList.add("active");
  activePanel = { el, wrap: stageWrapEl, key: "stage", id: stageId };
  stageWrapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function toggleCardPanel(groupId, el) {
  const g = groupById(groupId);
  if (!g) return;
  if (activePanel && activePanel.el === el) { closeActive(); return; }
  closeActive();
  cardWrapEl.innerHTML = "";
  cardWrapEl.appendChild(buildPanel(`${g.title} · 配置`, Object.keys(g.items || {})));
  el.classList.add("active");
  activePanel = { el, wrap: cardWrapEl, key: "card", id: groupId };
  cardWrapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ================= 提示词编辑与预览 ================= */
async function renderPrompts() {
  try {
    const res = await bridge.apiGet("prompts");
    const data = res && res.data !== undefined ? res.data : res;
    if (!data) return;
    const modeText = (m) => (m === "override" ? "override · 自定义覆盖" : "append · 默认拼接");
    const modeDesc = (m) =>
      m === "override"
        ? "留空 = 使用默认提示词；填写后完全替换默认提示词"
        : "留空 = 使用默认提示词；填写后追加在默认提示词之后";
    const card = (title, icon, p, cfgKey) => `
      <div class="prompt-card" data-prompt-card="${cfgKey}">
        <h3>${icon} ${title}</h3>
        <div class="meta">模式：${modeText(p.mode)} · ${p.has_custom ? "已配置自定义提示词" : "使用默认提示词"}</div>
        <div class="field" style="margin-top: 8px">
          <div class="field-title">✏️ 自定义提示词</div>
          <textarea data-prompt-edit="${cfgKey}" rows="6" placeholder="在这里输入你的自定义提示词…">${esc(p.extra)}</textarea>
          <div class="field-hint">${modeDesc(p.mode)}</div>
        </div>
        <div class="save-bar" style="margin-top: 10px">
          <span class="save-status" data-prompt-status="${cfgKey}"></span>
          <button class="btn" data-prompt-save="${cfgKey}">保存提示词</button>
        </div>
        <details class="prompt-preview">
          <summary>👁️ 生效提示词预览（拼接后全文，只读）</summary>
          <pre>${esc(p.text)}</pre>
        </details>
      </div>`;
    $("#promptGrid").innerHTML =
      card("读空气判断提示词", "🧠", data.decision || { mode: "append", has_custom: false, extra: "", text: "" }, "decision_ai_extra_prompt") +
      card("回复生成提示词（尾部引导）", "💬", data.reply || { mode: "append", has_custom: false, extra: "", text: "" }, "reply_ai_extra_prompt");
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
            toast("提示词保存失败", "err");
          }
        } catch (err) {
          status.textContent = "保存失败：" + err.message;
          toast("提示词保存失败：" + err.message, "err");
        } finally {
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    $("#promptGrid").innerHTML = `<div class="prompt-card">提示词加载失败：${esc(err.message)}</div>`;
  }
}

/* ================= toast ================= */
let toastTimer = null;
function toast(msg, type) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "show " + (type || "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

/* ================= 启动 ================= */
async function renderAll() {
  renderHeader();
  renderStats();
  renderPipeline();
  renderCards();
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
  try {
    await bridge.ready();
  } catch (e) {
    /* 非 iframe 环境（如直接打开）也尝试加载 */
  }
  await loadStatus();
  renderPrompts();
}

init();
