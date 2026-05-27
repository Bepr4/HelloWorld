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

let currentRunId = null;
let currentPackage = null;
let eventSource = null;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;

  resetRun();
  addMessage("user", message);
  setRunState("running", "运行中");
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

function connectEvents(runId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource(`/api/runs/${runId}/events`);
  eventSource.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "stream") {
      if (event.status !== "running") eventSource.close();
      return;
    }
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

function renderEvent(event) {
  const row = document.createElement("article");
  row.className = "event-row";

  const step = document.createElement("div");
  step.className = "event-step";
  step.textContent = event.type;

  const main = document.createElement("div");
  main.className = "event-main";
  const title = document.createElement("strong");
  title.textContent = event.message;
  main.appendChild(title);

  if (event.data !== null && event.data !== undefined) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "查看数据";
    const pre = document.createElement("pre");
    pre.textContent = JSON.stringify(event.data, null, 2);
    details.appendChild(summary);
    details.appendChild(pre);
    main.appendChild(details);
  }

  const status = document.createElement("div");
  status.className = `event-status ${event.status}`;
  status.textContent = event.status;

  row.append(step, main, status);
  eventStream.prepend(row);
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
    <div class="item-meta">${escapeHtml(source.publisher || "")} · ${escapeHtml(source.source_tier || "")} · ${escapeHtml(source.fetch_status || "")}</div>
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
  eventStream.innerHTML = "";
  resultList.innerHTML = "";
  sourceList.innerHTML = "";
  sourceText.textContent = "选择一个来源查看正文。";
  jsonView.textContent = "{}";
  metricSources.textContent = "0";
  metricBlocks.textContent = "0";
  metricSuggestions.textContent = "0";
}

function setRunState(state, label) {
  runState.className = `run-state ${state}`;
  runState.textContent = label;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
