// 这个文件负责前端工作台交互：提交运行、接收 SSE 事件、聚合进度指标并展示最终材料包。
const form = document.querySelector("#agentForm");
const input = document.querySelector("#messageInput");
const button = document.querySelector("#runButton");
const chatLog = document.querySelector("#chatLog");
const eventStream = document.querySelector("#eventStream");
const runState = document.querySelector("#runState");
const jsonView = document.querySelector("#jsonView");
const resultList = document.querySelector("#resultList");
const sourceList = document.querySelector("#sourceList");
const sourceText = document.querySelector("#sourceText");
const metricSources = document.querySelector("#metricSources");
const metricBlocks = document.querySelector("#metricBlocks");
const metricSuggestions = document.querySelector("#metricSuggestions");
const clearEvents = document.querySelector("#clearEvents");
const currentStepTitle = document.querySelector("#currentStepTitle");
const currentStepDetail = document.querySelector("#currentStepDetail");
const stageBoard = document.querySelector("#stageBoard");
const warningList = document.querySelector("#warningList");
const fetchTableBody = document.querySelector("#fetchTableBody");
const progressMetrics = {
  candidates: document.querySelector("#metricCandidates"),
  fetched: document.querySelector("#metricFetched"),
  fetchSuccess: document.querySelector("#metricFetchSuccess"),
  fetchFailed: document.querySelector("#metricFetchFailed"),
  accepted: document.querySelector("#metricAccepted"),
  warnings: document.querySelector("#metricWarnings"),
};

const STAGES = [
  ["prepare", "准备", "配置、范围、时间线"],
  ["search", "搜索", "Tavily 候选来源"],
  ["fetch", "抓正文", "Crawl4AI 下载与抽取"],
  ["decide", "整理", "LLM 选择来源并结构化"],
  ["storage", "写入", "保存材料包"],
];

const EVENT_LABELS = {
  chat: "对话",
  config: "配置",
  scope: "范围",
  timeline: "时间线",
  task: "任务单",
  sources: "白名单",
  news_collect: "工具",
  news_agent: "新闻 Agent",
  llm_agent: "LLM 决策",
  llm_agent_repair: "JSON 修复",
  llm_agent_final: "最终决策",
  llm_agent_result: "整理结果",
  tool_call: "工具调用",
  finance: "金融占位",
  storage: "写入",
  done: "完成",
  error: "错误",
};

const STATUS_LABELS = {
  started: "进行中",
  completed: "完成",
  success: "成功",
  failed: "失败",
  warning: "警告",
  rejected: "拒绝",
  running: "运行中",
  user: "用户",
  assistant: "Agent",
};

let currentRunId = null;
let currentPackage = null;
let eventSource = null;
let progress = createProgressState();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  resetRun();
  addMessage("user", message);
  setRunState("running", "运行中");
  setCurrentStep("启动运行", "正在创建后台任务");
  button.disabled = true;

  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });

  if (!response.ok) {
    const error = await response.text();
    addMessage("assistant", `启动失败：${error}`);
    setRunState("failed", "失败");
    button.disabled = false;
    return;
  }

  const payload = await response.json();
  currentRunId = payload.run_id;
  connectEvents(currentRunId);
});

clearEvents.addEventListener("click", () => {
  eventStream.innerHTML = "";
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`#panel-${tab.dataset.tab}`).classList.add("active");
  });
});

renderProgress();

function connectEvents(runId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/runs/${runId}/events`);
  eventSource.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "stream") {
      if (event.status !== "running") eventSource.close();
      return;
    }
    updateProgress(event);
    renderEvent(event);
    handleEvent(event);
  };
  eventSource.onerror = () => {
    addMessage("assistant", "事件流连接中断。");
    setRunState("failed", "中断");
    button.disabled = false;
    eventSource.close();
  };
}

function handleEvent(event) {
  if (event.type === "chat" && event.status === "assistant") {
    addMessage("assistant", event.message);
  }
  if (event.type === "done" && event.status === "completed") {
    currentPackage = event.data;
    renderPackage(currentPackage);
    setRunState("completed", "完成");
    button.disabled = false;
  }
  if (event.type === "error") {
    addMessage("assistant", event.data?.error || event.message);
    setRunState("failed", "失败");
    button.disabled = false;
  }
}

function updateProgress(event) {
  const summary = summarizeEvent(event);
  setCurrentStep(summary.title, summary.detail || "");
  updateStage(event);

  if (isSearchReturn(event)) {
    progress.stats.candidates += Number(event.data?.count || 0);
  }

  if (isFetchReturn(event)) {
    const row = {
      publisher: event.data?.publisher || domainFromUrl(event.data?.url),
      title: event.data?.title || event.data?.url || "未命名来源",
      status: event.data?.fetch_status || "unknown",
      error: event.data?.error || "",
      url: event.data?.url || "",
    };
    progress.fetches.unshift(row);
    progress.fetches = progress.fetches.slice(0, 12);
    progress.stats.fetched += 1;
    if (row.status === "success") progress.stats.fetchSuccess += 1;
    if (row.status === "failed") progress.stats.fetchFailed += 1;
  }

  if (event.type === "llm_agent_result") {
    progress.stats.accepted = event.data?.source_documents?.length || event.data?.accepted_urls?.length || 0;
  }
  if (event.type === "done") {
    progress.stats.accepted = event.data?.source_documents?.length || progress.stats.accepted;
  }

  if (event.status === "warning" || event.status === "failed" || (event.type === "llm_agent_repair" && event.status !== "started")) {
    progress.warnings.unshift({
      title: summary.title,
      detail: summary.detail || event.data?.error || event.message,
      status: event.status,
    });
    progress.warnings = progress.warnings.slice(0, 8);
    progress.stats.warnings = progress.warnings.length;
  }

  renderProgress();
}

function renderProgress() {
  stageBoard.innerHTML = "";
  STAGES.forEach(([key, label, caption]) => {
    const stage = progress.stages[key];
    const item = document.createElement("article");
    item.className = `stage-card ${stage}`;
    item.innerHTML = `
      <div class="stage-title">
        <span class="stage-dot"></span>
        <strong>${label}</strong>
      </div>
      <p class="stage-detail">${caption}</p>
      <em class="stage-state">${statusLabel(stage)}</em>
    `;
    stageBoard.appendChild(item);
  });

  progressMetrics.candidates.textContent = progress.stats.candidates;
  progressMetrics.fetched.textContent = progress.stats.fetched;
  progressMetrics.fetchSuccess.textContent = progress.stats.fetchSuccess;
  progressMetrics.fetchFailed.textContent = progress.stats.fetchFailed;
  progressMetrics.accepted.textContent = progress.stats.accepted;
  progressMetrics.warnings.textContent = progress.stats.warnings;

  warningList.innerHTML = "";
  if (progress.warnings.length === 0) {
    warningList.innerHTML = `<p class="empty-note">还没有警告或降级。</p>`;
  } else {
    progress.warnings.forEach((item) => {
      const row = document.createElement("article");
      row.className = `warning-item ${item.status}`;
      row.innerHTML = `<strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.detail || "")}</span>`;
      warningList.appendChild(row);
    });
  }

  fetchTableBody.innerHTML = "";
  if (progress.fetches.length === 0) {
    fetchTableBody.innerHTML = `<tr><td colspan="4" class="empty-cell">还没有抓取 URL。</td></tr>`;
  } else {
    progress.fetches.forEach((item) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeHtml(item.publisher || "-")}</td>
        <td><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title)}</a></td>
        <td><span class="fetch-pill ${escapeHtml(item.status)}">${statusLabel(item.status)}</span></td>
        <td>${escapeHtml(item.error || "")}</td>
      `;
      fetchTableBody.appendChild(row);
    });
  }
}

function renderEvent(event) {
  const summary = summarizeEvent(event);
  const row = document.createElement("article");
  row.className = `event-row ${event.status}`;

  const step = document.createElement("div");
  step.className = "event-step";
  step.textContent = EVENT_LABELS[event.type] || event.type;

  const main = document.createElement("div");
  main.className = "event-main";
  const title = document.createElement("strong");
  title.textContent = summary.title;
  main.appendChild(title);

  if (summary.detail) {
    const detail = document.createElement("p");
    detail.className = "event-detail";
    detail.textContent = summary.detail;
    main.appendChild(detail);
  }
  if (summary.chips.length > 0) {
    const chips = document.createElement("div");
    chips.className = "chip-row";
    summary.chips.forEach((chip) => {
      const item = document.createElement("span");
      item.className = "chip";
      item.textContent = chip;
      chips.appendChild(item);
    });
    main.appendChild(chips);
  }

  if (event.data !== null && event.data !== undefined) {
    const details = document.createElement("details");
    const rawSummary = document.createElement("summary");
    rawSummary.textContent = "查看原始数据";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(event.data, null, 2);
    details.appendChild(rawSummary);
    details.appendChild(pre);
    main.appendChild(details);
  }

  const status = document.createElement("div");
  status.className = `event-status ${event.status}`;
  status.textContent = statusLabel(event.status);

  row.append(step, main, status);
  eventStream.prepend(row);
}

function summarizeEvent(event) {
  const data = event.data || {};
  const chips = [];
  let title = event.message || EVENT_LABELS[event.type] || event.type;
  let detail = "";

  if (isSearchReturn(event)) {
    title = `搜索返回 ${data.count || 0} 个白名单候选`;
    detail = (data.queries || []).join(" / ");
    chips.push(data.provider || "搜索服务");
  } else if (isFetchReturn(event)) {
    title = data.fetch_status === "success" ? `抓取成功：${data.title || data.url}` : `抓取失败：${data.title || data.url}`;
    detail = data.error || `来源：${data.publisher || domainFromUrl(data.url)}${data.published_at ? `，发布时间：${data.published_at}` : ""}`;
    chips.push(data.publisher || domainFromUrl(data.url));
    chips.push(statusLabel(data.fetch_status || event.status));
  } else if (event.type === "llm_agent" && event.status === "completed" && data.decision) {
    const calls = data.decision.tool_calls || [];
    title = data.decision.final ? "LLM 给出最终整理方案" : `LLM 决定调用 ${calls.length} 个工具`;
    detail = data.decision.thought || "";
    calls.slice(0, 4).forEach((call) => chips.push(call.tool));
  } else if (event.type === "llm_agent" && event.status === "warning") {
    title = "LLM 决策降级";
    detail = data.error || event.message;
    chips.push(`已抓取 ${data.partial_documents || 0}`);
  } else if (event.type === "llm_agent_repair") {
    title = event.status === "completed" ? "JSON 自动修复成功" : event.status === "started" ? "正在修复 LLM JSON" : "JSON 自动修复失败";
    detail = data.error || "";
  } else if (event.type === "llm_agent_result") {
    const count = data.source_documents?.length || 0;
    title = `整理出 ${count} 条可用来源`;
    detail = `${data.news_blocks?.length || 0} 个新闻块，${data.accepted_urls?.length || 0} 个 accepted URL`;
  } else if (event.type === "storage" && event.status === "completed") {
    title = "材料包已写入磁盘";
    detail = data.output_dir || "";
    chips.push(`${data.source_documents || 0} sources`);
    chips.push(`${data.news_blocks || 0} blocks`);
  } else if (event.type === "done") {
    title = "模块一运行完成";
    detail = `${data.source_documents || 0} 条来源，${data.news_blocks || 0} 个新闻块`;
  } else if (data.error) {
    detail = data.error;
  }

  return { title, detail, chips };
}

function renderPackage(pkg) {
  jsonView.textContent = JSON.stringify(pkg, null, 2);
  metricSources.textContent = pkg.source_documents?.length ?? 0;
  metricBlocks.textContent = pkg.news_blocks?.length ?? 0;
  metricSuggestions.textContent = pkg.timeline_update_suggestions?.length ?? 0;

  resultList.innerHTML = "";
  addResult("事件范围", pkg.confirmed_scope || pkg.confirmed_event || "");
  (pkg.baseline_timeline || []).forEach((item) => {
    addResult(`时间线：${item.title}`, `${item.start_date || "无日期"} · ${item.summary || ""}`);
  });
  (pkg.news_blocks || []).forEach((block) => {
    addResult(`新闻块：${block.title}`, `${block.summary || ""}\n来源：${(block.source_refs || []).join(", ")}`);
  });

  sourceList.innerHTML = "";
  sourceText.textContent = "选择一个来源查看正文。";
  (pkg.source_documents || []).forEach((source) => renderSourceButton(source));
}

function renderSourceButton(source) {
  const item = document.createElement("button");
  item.className = "source-item";
  item.type = "button";
  item.innerHTML = `
    <strong>${escapeHtml(source.title || source.url)}</strong>
    <div class="item-meta">${escapeHtml(source.publisher || "")} · ${escapeHtml(source.source_tier || "")} · ${escapeHtml(statusLabel(source.fetch_status || ""))}</div>
  `;
  item.addEventListener("click", async () => {
    document.querySelectorAll(".source-item").forEach((node) => node.classList.remove("active"));
    item.classList.add("active");
    sourceText.textContent = "读取中...";
    const response = await fetch(`/api/runs/${currentRunId}/sources/${source.source_id}`);
    sourceText.textContent = response.ok ? await response.text() : "这个来源没有可预览正文。";
  });
  sourceList.appendChild(item);
}

function addResult(title, body) {
  const item = document.createElement("article");
  item.className = "result-item";
  item.innerHTML = `<strong>${escapeHtml(title)}</strong><div class="item-meta">${escapeHtml(body)}</div>`;
  resultList.appendChild(item);
}

function addMessage(role, text) {
  const article = document.createElement("article");
  article.className = `message ${role}`;
  article.innerHTML = `
    <div class="avatar">${role === "user" ? "U" : "A"}</div>
    <div class="bubble"><p>${escapeHtml(text)}</p></div>
  `;
  chatLog.appendChild(article);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function resetRun() {
  if (eventSource) eventSource.close();
  currentRunId = null;
  currentPackage = null;
  progress = createProgressState();
  eventStream.innerHTML = "";
  resultList.innerHTML = "";
  sourceList.innerHTML = "";
  sourceText.textContent = "选择一个来源查看正文。";
  jsonView.textContent = "{}";
  metricSources.textContent = "0";
  metricBlocks.textContent = "0";
  metricSuggestions.textContent = "0";
  setCurrentStep("待机", "输入事件后开始采集。");
  renderProgress();
}

function createProgressState() {
  return {
    stages: {
      prepare: "pending",
      search: "pending",
      fetch: "pending",
      decide: "pending",
      storage: "pending",
    },
    stats: {
      candidates: 0,
      fetched: 0,
      fetchSuccess: 0,
      fetchFailed: 0,
      accepted: 0,
      warnings: 0,
    },
    warnings: [],
    fetches: [],
  };
}

function updateStage(event) {
  const key = stageForEvent(event);
  if (!key) return;
  const incoming = stageStatus(event);
  const current = progress.stages[key];
  if (current === "failed" || (current === "warning" && incoming === "completed")) return;
  progress.stages[key] = incoming;
}

function stageForEvent(event) {
  if (["config", "scope", "timeline", "task", "sources", "news_collect"].includes(event.type)) return "prepare";
  if (isSearchEvent(event)) return "search";
  if (isFetchEvent(event)) return "fetch";
  if (["news_agent", "llm_agent", "llm_agent_repair", "llm_agent_final", "llm_agent_result"].includes(event.type)) return "decide";
  if (["storage", "done"].includes(event.type)) return "storage";
  return null;
}

function stageStatus(event) {
  if (event.status === "failed" || event.status === "rejected") return "failed";
  if (event.status === "warning") return "warning";
  if (event.status === "started" || event.status === "running") return "running";
  return "completed";
}

function setCurrentStep(title, detail) {
  currentStepTitle.textContent = title;
  currentStepDetail.textContent = detail || "等待下一步事件。";
}

function setRunState(state, label) {
  runState.className = `run-state ${state}`;
  runState.textContent = label;
}

function isSearchEvent(event) {
  return event.data?.tool === "web_search" || event.message?.includes("web_search");
}

function isSearchReturn(event) {
  return event.type === "tool_call" && event.status === "completed" && isSearchEvent(event) && typeof event.data?.count === "number";
}

function isFetchEvent(event) {
  return event.data?.tool === "fetch_url" || event.message?.includes("fetch_url") || Boolean(event.data?.fetch_status);
}

function isFetchReturn(event) {
  return event.type === "tool_call" && event.status === "completed" && isFetchEvent(event) && Boolean(event.data?.fetch_status);
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "未知";
}

function domainFromUrl(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
