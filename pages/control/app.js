// Group Chat Plus Lite — 插件页控制台（卡片式/胶囊式）
const bridge = window.AstrBotPluginPage;

const state = { values: {}, runtime: {}, version: "" };

/* ================= 字段定义 ================= */
const FIELDS = {
  enable_group_chat: { label: "群聊回复总开关", type: "bool", hint: "关闭后插件不再处理任何群聊消息" },
  enable_debug_log: { label: "详细日志", type: "bool", hint: "调试排错用" },
  initial_probability: { label: "初始回复概率", type: "float", min: 0, max: 1, step: 0.01, hint: "非@消息进入判断链的概率（1=全部进入读空气判断）" },
  after_reply_probability: { label: "回复后追加概率", type: "float", min: 0, max: 1, step: 0.01, hint: "机器人刚回复后，紧接着消息的回复概率" },
  probability_duration: { label: "概率时长(秒)", type: "int", min: 1, max: 86400, hint: "回复后概率状态的持续时间" },
  decision_ai_reply_tendency: { label: "读空气回复倾向", type: "select", options: ["persona", "reserved", "active"], labels: { persona: "persona · 人格倾向优先", reserved: "reserved · 更克制", active: "active · 更主动" }, hint: "persona=以人格社交倾向为最高依据；reserved=只回明确需求；active=主动参与" },
  decision_ai_prompt_mode: { label: "判断提示词模式", type: "select", options: ["append", "override"], labels: { append: "append · 拼接", override: "override · 覆盖" }, hint: "append=默认提示词+补充；override=只用自定义提示词" },
  decision_ai_timeout: { label: "判断超时(秒)", type: "int", min: 3, max: 300, hint: "读空气AI调用的超时时间" },
  decision_ai_include_persona: { label: "判断时注入人格", type: "bool", hint: "让判断AI按人格社交倾向判断是否回复" },
  enable_decision_ai_reasoning: { label: "思考过程输出", type: "bool", hint: "让判断AI先输出思考过程再给 yes/no" },
  decision_ai_reasoning_log: { label: "思考过程记日志", type: "bool", hint: "将判断思考过程写入插件日志" },
  reply_ai_prompt_mode: { label: "回复提示词模式", type: "select", options: ["append", "override"], labels: { append: "append · 拼接", override: "override · 覆盖" }, hint: "回复内容默认由 AstrBot 人格链路生成，此处仅控制上下文拼接方式" },
  include_timestamp: { label: "附带时间戳", type: "bool", hint: "在上下文中标注消息发送时间" },
  include_sender_info: { label: "附带发送者信息", type: "bool", hint: "在上下文中标注谁在说话" },
  max_context_messages: { label: "最大上下文消息数", type: "int", min: -1, max: 200, hint: "-1=不限制，0=失忆（不推荐），建议 20~30" },
  enable_forward_message_parsing: { label: "转发消息解析", type: "bool", hint: "把群聊合并转发解析为单条可读文本" },
  forward_max_nesting_depth: { label: "嵌套解析深度", type: "int", min: 0, max: 10, hint: "嵌套转发的最大展开深度" },
  enable_image_processing: { label: "图片识别", type: "bool", hint: "通过概率筛选的消息中的图片转文字描述" },
  image_to_text_scope: { label: "图片处理范围", type: "select", options: ["all", "mention_only", "at_only", "keyword_only"], labels: { all: "全部消息", mention_only: "@或关键词触发", at_only: "仅@机器人", keyword_only: "仅关键词" }, hint: "图片转文字的应用范围" },
  max_images_per_message: { label: "单条最大图片数", type: "int", min: 1, max: 50, hint: "单条消息最多处理几张图片" },
  enable_emoji_filter: { label: "表情包消息降权", type: "bool", hint: "纯表情包消息降低回复概率" },
  emoji_probability_decay: { label: "表情包概率衰减", type: "float", min: 0, max: 1, step: 0.05, hint: "表情包消息的概率乘数" },
  enable_memory_injection: { label: "记忆注入", type: "bool", hint: "调用记忆插件注入长期记忆（需已安装）" },
  memory_plugin_mode: { label: "记忆插件模式", type: "select", options: ["auto", "legacy", "livingmemory"], labels: { auto: "auto · 自动检测", legacy: "legacy · 旧版记忆", livingmemory: "livingmemory" }, hint: "选择使用的记忆存储插件" },
  livingmemory_top_k: { label: "记忆召回数量", type: "int", min: 1, max: 50, hint: "每次调用 LivingMemory 召回的条数" },
  keyword_smart_mode: { label: "关键词智能模式", type: "bool", hint: "关键词触发后仍交读空气判断而非必回" },
  enable_user_blacklist: { label: "用户黑名单", type: "bool", hint: "黑名单用户的消息不参与回复" },
  enable_command_filter: { label: "指令过滤", type: "bool", hint: "以 / ! # 开头的指令消息不参与回复" },
  enable_ignore_at_others: { label: "忽略@他人消息", type: "bool", hint: "@了别人但没有@机器人的消息不回复" },
  enable_ignore_at_all: { label: "忽略@全体消息", type: "bool", hint: "@全体成员的消息不回复" },
  poke_message_mode: { label: "戳一戳模式", type: "select", options: ["ignore", "bot_only", "all"], labels: { ignore: "ignore · 忽略", bot_only: "bot_only · 仅被戳", all: "all · 全部" }, hint: "戳一戳消息的处理范围" },
  poke_bot_skip_probability: { label: "被戳直接回复", type: "bool", hint: "被戳时跳过概率筛选直接判断" },
  enable_poke_after_reply: { label: "回复后戳回去", type: "bool", hint: "AI 回复后反戳发送者" },
  enable_duplicate_filter: { label: "防复读", type: "bool", hint: "过滤内容重复的回复" },
  duplicate_filter_check_count: { label: "复读检查条数", type: "int", min: 1, max: 50, hint: "检查最近几条消息是否重复" },
  concurrent_mode: { label: "并发模式", type: "select", options: ["legacy", "smart"], labels: { legacy: "legacy · 传统", smart: "smart · 智能合并" }, hint: "smart=合并短时间内的多条消息批量处理" },
  concurrent_wait_max_loops: { label: "等待最大轮询次数", type: "int", min: 1, max: 60, hint: "Smart 并发等待的轮询上限" },
  concurrent_wait_interval: { label: "轮询间隔(秒)", type: "float", min: 0.1, max: 10, step: 0.1, hint: "Smart 并发等待的轮询间隔" },
  enable_smart_batch_reply_hint: { label: "批次合并提示", type: "bool", hint: "合并处理时在上下文标注批次说明" },
  smart_concurrent_merge_wait: { label: "合并等待(秒)", type: "int", min: 1, max: 300, hint: "等待多久内到达的消息合并处理" },
  smart_concurrent_max_batch_size: { label: "最大批次数", type: "int", min: 1, max: 100, hint: "单次合并最多处理多少条消息" },
  smart_concurrent_claim_delay: { label: "抢占延迟(秒)", type: "float", min: 0, max: 10, step: 0.1, hint: "消息进入合并窗口的延迟" },
  enable_output_content_filter: { label: "输出内容过滤", type: "bool", hint: "按规则过滤 AI 回复内容" },
  enable_save_content_filter: { label: "保存内容过滤", type: "bool", hint: "按规则过滤写入历史的 AI 内容" },
};

/* ================= 流水线阶段 ================= */
const STAGES = [
  { id: "probability", icon: "🎲", title: "概率筛选", keys: ["initial_probability", "after_reply_probability", "probability_duration"], summary: (v) => v.initial_probability ?? "-" },
  { id: "command", icon: "🎛️", title: "指令&关键词", keys: ["enable_command_filter", "keyword_smart_mode"], summary: (v) => (v.enable_command_filter ? "指令过滤开" : "指令过滤关") },
  { id: "at", icon: "📢", title: "@必回处理", keys: ["enable_ignore_at_others", "enable_ignore_at_all"], summary: (v) => [v.enable_ignore_at_others ? "忽略@他人" : null, v.enable_ignore_at_all ? "忽略@全体" : null].filter(Boolean).join(" / ") || "未启用过滤" },
  { id: "decision", icon: "🧠", title: "读空气AI判断", keys: ["decision_ai_reply_tendency", "decision_ai_prompt_mode", "decision_ai_timeout", "decision_ai_include_persona", "enable_decision_ai_reasoning", "decision_ai_reasoning_log"], summary: (v) => v.decision_ai_reply_tendency ?? "-" },
  { id: "reply", icon: "💬", title: "回复生成", keys: ["reply_ai_prompt_mode", "include_timestamp", "include_sender_info", "max_context_messages"], summary: (v) => v.max_context_messages === -1 ? "上下文不限" : v.max_context_messages === 0 ? "无上下文" : (v.max_context_messages ?? "-") + " 条" },
];

/* ================= 功能卡片 ================= */
const CARDS = [
  { id: "image", icon: "🖼️", name: "图片识别", keys: ["enable_image_processing", "image_to_text_scope", "max_images_per_message"], summary: (v) => v.enable_image_processing ? `范围：${v.image_to_text_scope ?? "-"}` : "未启用" },
  { id: "forward", icon: "🔁", name: "转发解析", keys: ["enable_forward_message_parsing", "forward_max_nesting_depth"], summary: (v) => v.enable_forward_message_parsing ? `深度 ${v.forward_max_nesting_depth ?? "-"}` : "未启用" },
  { id: "blacklist", icon: "🚫", name: "黑名单", keys: ["enable_user_blacklist"], summary: (v) => v.enable_user_blacklist ? "已启用" : "未启用" },
  { id: "memory", icon: "🧠", name: "记忆注入", keys: ["enable_memory_injection", "memory_plugin_mode", "livingmemory_top_k"], summary: (v) => v.enable_memory_injection ? `${v.memory_plugin_mode ?? "-"} · top${v.livingmemory_top_k ?? "-"}` : "未启用" },
  { id: "emoji", icon: "😀", name: "表情包降权", keys: ["enable_emoji_filter", "emoji_probability_decay"], summary: (v) => v.enable_emoji_filter ? `衰减 ${v.emoji_probability_decay ?? "-"}` : "未启用" },
  { id: "poke", icon: "👆", name: "戳一戳", keys: ["poke_message_mode", "poke_bot_skip_probability", "enable_poke_after_reply"], summary: (v) => `${v.poke_message_mode ?? "-"} · 反戳${v.enable_poke_after_reply ? "开" : "关"}` },
  { id: "duplicate", icon: "🔎", name: "防复读", keys: ["enable_duplicate_filter", "duplicate_filter_check_count"], summary: (v) => v.enable_duplicate_filter ? `检查 ${v.duplicate_filter_check_count ?? "-"} 条` : "未启用" },
  { id: "smart", icon: "⚡", name: "Smart并发", keys: ["concurrent_mode", "concurrent_wait_max_loops", "concurrent_wait_interval", "enable_smart_batch_reply_hint", "smart_concurrent_merge_wait", "smart_concurrent_max_batch_size", "smart_concurrent_claim_delay"], summary: (v) => `${v.concurrent_mode ?? "legacy"} · 合并 ${v.smart_concurrent_merge_wait ?? "-"}s` },
  { id: "filter", icon: "✂️", name: "内容过滤", keys: ["enable_output_content_filter", "enable_save_content_filter"], summary: (v) => [v.enable_output_content_filter ? "输出" : null, v.enable_save_content_filter ? "保存" : null].filter(Boolean).join("+") || "未启用" },
];

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

function stageState(stage) {
  const on = stage.keys.some((k) => !!state.values[k]);
  return on;
}

function renderPipeline() {
  $("#pipeline").innerHTML = STAGES.map((s, idx) => {
    const on = stageState(s);
    const html = `
      <div class="capsule" data-stage="${s.id}" role="button" tabindex="0">
        <span class="num">${idx + 1}</span>
        <div class="cap-name">${s.icon} ${s.title}</div>
        <div class="cap-state"><span class="dot ${on ? "on" : "off"}"></span>${esc(s.summary(state.values))}</div>
      </div>`;
    return idx < STAGES.length - 1 ? html + `<div class="arrow">→</div>` : html;
  }).join("");
  $("#pipeline").querySelectorAll(".capsule").forEach((el) => {
    el.addEventListener("click", () => toggleStagePanel(el.dataset.stage, el));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") toggleStagePanel(el.dataset.stage, el); });
  });
}

function cardOn(card) {
  return card.keys.some((k) => !!state.values[k]);
}

function renderCards() {
  $("#cards").innerHTML = CARDS.map((c) => {
    const on = cardOn(c);
    return `
      <div class="card" data-card="${c.id}" role="button" tabindex="0">
        <div class="card-head">
          <span class="icon">${c.icon}</span>
          <span class="name">${c.name}</span>
          <span class="badge ${on ? "on" : "off"}">${on ? "已启用" : "已关闭"}</span>
        </div>
        <div class="card-summary">${esc(c.summary(state.values))}</div>
      </div>`;
  }).join("");
  $("#cards").querySelectorAll(".card").forEach((el) => {
    el.addEventListener("click", () => toggleCardPanel(el.dataset.card, el));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") toggleCardPanel(el.dataset.card, el); });
  });
}

/* ================= 编辑面板 ================= */
function fieldControl(key) {
  const def = FIELDS[key];
  const val = state.values[key];
  if (def.type === "bool") {
    return `
      <div class="field-row">
        <label>${esc(def.label)}<span class="hint">${esc(def.hint || "")}</span></label>
        <label class="switch"><input type="checkbox" data-key="${key}" ${val ? "checked" : ""} /><span class="slider"></span></label>
      </div>`;
  }
  if (def.type === "select") {
    const opts = (def.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc((def.labels && def.labels[o]) || o)}</option>`).join("");
    return `
      <div class="field">
        <label>${esc(def.label)}<span class="hint">${esc(def.hint || "")}</span></label>
        <select data-key="${key}">${opts}</select>
      </div>`;
  }
  const num = def.type === "int" || def.type === "float";
  if (num) {
    const step = def.step ?? (def.type === "int" ? 1 : 0.01);
    return `
      <div class="field">
        <label>${esc(def.label)}<span class="hint">${esc(def.hint || "")}</span></label>
        <input type="number" data-key="${key}" value="${esc(val)}" min="${def.min ?? ""}" max="${def.max ?? ""}" step="${step}" />
      </div>`;
  }
  return `
    <div class="field">
      <label>${esc(def.label)}<span class="hint">${esc(def.hint || "")}</span></label>
      <input type="text" data-key="${key}" value="${esc(val)}" />
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
      const def = FIELDS[key];
      if (def.type === "bool") updates[key] = el.checked;
      else if (def.type === "int") updates[key] = parseInt(el.value, 10);
      else if (def.type === "float") updates[key] = parseFloat(el.value);
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

function toggleStagePanel(stageId, el) {
  const stage = STAGES.find((s) => s.id === stageId);
  if (!stage) return;
  if (activePanel && activePanel.el === el) { closeActive(); return; }
  closeActive();
  stageWrapEl.innerHTML = "";
  stageWrapEl.appendChild(buildPanel(`${stage.icon} ${stage.title} · 配置`, stage.keys));
  el.classList.add("active");
  activePanel = { el, wrap: stageWrapEl, key: "stage", id: stageId };
  stageWrapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function toggleCardPanel(cardId, el) {
  const card = CARDS.find((c) => c.id === cardId);
  if (!card) return;
  if (activePanel && activePanel.el === el) { closeActive(); return; }
  closeActive();
  cardWrapEl.innerHTML = "";
  cardWrapEl.appendChild(buildPanel(`${card.icon} ${card.name} · 配置`, card.keys));
  el.classList.add("active");
  activePanel = { el, wrap: cardWrapEl, key: "card", id: cardId };
  cardWrapEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ================= 提示词预览 ================= */
async function renderPrompts() {
  try {
    const res = await bridge.apiGet("prompts");
    const data = res && res.data !== undefined ? res.data : res;
    if (!data) return;
    const modeText = (m) => (m === "override" ? "override · 自定义覆盖" : "append · 默认拼接");
    const card = (title, icon, p) => `
      <div class="prompt-card">
        <h3>${icon} ${title}</h3>
        <div class="meta">模式：${modeText(p.mode)} · ${p.has_custom ? "已配置自定义提示词" : "使用默认提示词"}</div>
        <pre data-collapse="${title}">${esc(p.text)}</pre>
        <button class="btn btn-ghost collapse-btn" data-target="${title}">展开 / 收起</button>
      </div>`;
    $("#promptGrid").innerHTML =
      card("读空气判断提示词", "🧠", data.decision || { mode: "-", has_custom: false, text: "" }) +
      card("回复生成提示词（尾部引导）", "💬", data.reply || { mode: "-", has_custom: false, text: "" });
    $("#promptGrid").querySelectorAll(".collapse-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pre = document.querySelector(`pre[data-collapse="${btn.dataset.target}"]`);
        if (pre) pre.style.maxHeight = pre.style.maxHeight === "none" ? "" : "none";
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
