"use strict";

const state = {projects: [], project: null, chatMessages: [], uploads: [], proposal: null, activeAction: null, uploading: false, mailBusy: false, followUpAsked: []};
const byId = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const fieldLabels = {
  project_name: "出張プロジェクト", origin: "出発地", destination: "目的地",
  budget_jpy: "予算上限", duration_limit_days: "出張期間",
  arrival_deadline: "到着希望時刻", purpose: "出張目的", departure_at: "出発日時",
  arrive_by: "到着希望日時", return_by: "帰着希望日時", travelers: "出張人数",
  lodging_required: "宿泊",
};

const pageOrder = ["work-area", "proposal-panel", "email-panel"];
let activePage = "work-area";
let pageScrollFrame = 0;

function syncPageBookmarks() {
  const available = {
    "work-area": true,
    "proposal-panel": Boolean(state.proposal),
    "email-panel": Boolean(state.project),
  };
  const buttons = [...document.querySelectorAll(".page-bookmark")];
  for (const button of buttons) {
    const target = button.dataset.pageTarget;
    button.disabled = !available[target];
    button.classList.toggle("is-current", target === activePage);
    button.classList.toggle("is-complete", target === "work-area" ? Boolean(state.proposal) :
      target === "proposal-panel" ? Boolean(state.proposal) : Boolean(byId("email-output") && !byId("email-output").hidden));
    if (target === activePage) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  }
  const currentIndex = pageOrder.indexOf(activePage);
  const previous = [...pageOrder.slice(0, currentIndex)].reverse().find(id => available[id]);
  const next = pageOrder.slice(currentIndex + 1).find(id => available[id]);
  byId("previous-page").disabled = !previous;
  byId("next-page").disabled = !next;
}

function setActivePage(pageId) {
  activePage = pageId;
  syncPageBookmarks();
}

function openPage(pageId) {
  if (pageId === "proposal-panel" && !state.proposal) return;
  if (pageId === "email-panel") {
    if (!state.project) return;
    byId("email-panel").hidden = false;
  }
  const target = byId(pageId);
  if (!target || target.hidden) return;
  setActivePage(pageId);
  target.scrollIntoView({behavior: "smooth", block: "start"});
}

for (const button of document.querySelectorAll(".page-bookmark")) {
  button.addEventListener("click", () => openPage(button.dataset.pageTarget));
}
byId("previous-page").addEventListener("click", () => {
  const currentIndex = pageOrder.indexOf(activePage);
  for (let index = currentIndex - 1; index >= 0; index -= 1) {
    const target = pageOrder[index];
    if ((target === "work-area") || (target === "proposal-panel" && state.proposal) || (target === "email-panel" && state.project)) {
      openPage(target);
      return;
    }
  }
});
byId("next-page").addEventListener("click", () => {
  const currentIndex = pageOrder.indexOf(activePage);
  for (let index = currentIndex + 1; index < pageOrder.length; index += 1) {
    const target = pageOrder[index];
    if ((target === "work-area") || (target === "proposal-panel" && state.proposal) || (target === "email-panel" && state.project)) {
      openPage(target);
      return;
    }
  }
});

window.addEventListener("scroll", () => {
  if (pageScrollFrame) return;
  pageScrollFrame = requestAnimationFrame(() => {
    pageScrollFrame = 0;
    const activationLine = Math.min(420, Math.max(82, window.innerHeight * 0.48));
    const visible = pageOrder
      .map(id => byId(id))
      .filter(element => element && !element.hidden)
      .map(element => ({id: element.id, top: element.getBoundingClientRect().top}))
      .filter(item => item.top <= activationLine)
      .sort((a, b) => b.top - a.top);
    setActivePage(visible[0]?.id || "work-area");
  }, {passive: true});
}, {passive: true});
syncPageBookmarks();

function authHeaders(extra = {}) {
  const token = sessionStorage.getItem("team-access-token");
  return {...extra, ...(token ? {Authorization: `Bearer ${token}`} : {})};
}

function showAccessGate() {
  byId("access-gate").hidden = false;
  byId("access-password").focus();
}

async function api(path, body) {
  const options = body === undefined ? {headers: authHeaders()} : {
    method: "POST", headers: authHeaders({"Content-Type": "application/json"}), body: JSON.stringify(body),
  };
  const response = await fetch(path, options);
  const value = await response.json();
  if (response.status === 401) {
    showAccessGate();
    const error = new Error(value.message || "チームアクセスコードを入力してください。");
    error.code = "unauthorized";
    throw error;
  }
  if (!response.ok) throw new Error(value.message || "処理に失敗しました。");
  return value;
}

function setProjectMessage(message, isError = false) {
  const box = byId("project-message");
  box.textContent = message;
  box.classList.toggle("is-error", isError);
  box.hidden = !message;
}

function clearProposal() {
  state.proposal = null;
  byId("proposal-panel").hidden = true;
  clearEmailDraft();
  setActivePage("work-area");
}

function clearEmailDraft() {
  byId("email-panel").hidden = true;
  byId("email-status").textContent = "";
  byId("email-status").hidden = true;
  byId("email-status").classList.remove("is-error");
  byId("email-output").hidden = true;
  byId("email-recipient").value = "";
  byId("email-purpose").value = "出張計画の共有・確認依頼";
  byId("email-subject").value = "";
  byId("email-body").value = "";
}

function updateComposerActions() {
  const busy = Boolean(state.activeAction || state.uploading || state.mailBusy);
  const hasContext = Boolean(state.project || state.uploads.length);
  const send = byId("send-chat");
  const create = byId("create-proposal");
  const email = byId("generate-email");
  send.disabled = busy || !hasContext || !byId("chat-input").value.trim();
  create.disabled = busy || !state.project;
  email.disabled = busy || !state.project;
  send.textContent = state.activeAction === "chat" ? "回答を作成中…" : "会話で相談 ↗";
  create.textContent = state.activeAction === "proposal" ? "計画書を作成中…" : "計画書を作成 →";
  byId("chat-input").disabled = busy;
  byId("chat-file").disabled = busy;
  byId("project-select").disabled = busy;
  byId("create-email-draft").disabled = busy;
  byId("email-recipient").disabled = busy;
  byId("email-purpose").disabled = busy;
}

function appendUserMessage(message, author = "あなた") {
  const item = node("article", undefined, "chat-message user-message");
  item.append(node("span", author, "message-author"), node("p", message));
  const list = byId("chat-messages");
  list.append(item);
  list.scrollTop = list.scrollHeight;
}

function askFollowUpQuestions(missing) {
  const questions = [
    ...missing.map(item => `${item}を教えてください。`),
    "交通費・宿泊費・日当のうち、予算上限に含めたい費用を教えてください。",
    "出張の起点として、会社本店とプロジェクトの出発地のどちらを希望しますか？",
    "今回の出張に適用する旅費規程をご存じですか？",
  ];
  const newQuestions = questions.filter(question => !state.followUpAsked.includes(question));
  if (!newQuestions.length) return false;
  state.followUpAsked.push(...newQuestions);
  const answer = [
    "計画書を作成しました。ご希望に沿った内容にするため、分かる範囲で次の点を教えてください。",
    ...newQuestions.map(question => `・${question}`),
    "回答を入力して「会話で相談」を押すと、AI が内容を確認します。その後「計画書を作成」を押すと反映します。",
  ].join("\n");
  state.chatMessages.push({role: "assistant", content: answer});
  const messages = byId("chat-messages");
  messages.append(renderAssistantMessage(answer));
  messages.scrollTop = messages.scrollHeight;
  byId("proposal-panel").after(byId("work-area"));
  byId("work-area").scrollIntoView({behavior: "smooth", block: "start"});
  byId("chat-input").focus();
  return true;
}

function displayFieldValue(key, value) {
  if (value === true) return "必要";
  if (value === false) return "不要";
  if (key === "budget_jpy" && typeof value === "number") return `¥${value.toLocaleString("ja-JP")}`;
  if (key === "duration_limit_days" && typeof value === "number") return `${value}日以内`;
  if (key === "travelers" && typeof value === "number") return `${value}名`;
  return String(value);
}

function displayFileName(path) {
  const filename = String(path).split(/[\\/]/).pop() || String(path);
  const extensionIndex = filename.lastIndexOf(".");
  return extensionIndex > 0 ? filename.slice(0, extensionIndex) : filename;
}

function tokyoIso(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(date).filter(part => part.type !== "literal").map(part => [part.type, part.value]));
  return parts.year + "-" + parts.month + "-" + parts.day + "T" + parts.hour + ":" + parts.minute + ":" + parts.second + "+09:00";
}

function simulationScenario(fields) {
  const assumptions = [];
  const tokyoNow = tokyoIso();
  const dateParts = tokyoNow.slice(0, 10).split("-").map(Number);
  const sampleDate = new Date(Date.UTC(dateParts[0], dateParts[1] - 1, dateParts[2] + 1)).toISOString().slice(0, 10);
  const departureDate = typeof fields.departure_at === "string" && /^\d{4}-\d{2}-\d{2}/.test(fields.departure_at)
    ? fields.departure_at.slice(0, 10) : sampleDate;
  let departureAt = fields.departure_at;
  if (!departureAt) {
    departureAt = departureDate + "T08:00:00+09:00";
    assumptions.push("模擬用出発日時：" + departureAt + "（出発日は未入力のため翌日、時刻は例示値）");
  }
  const deadlineClock = typeof fields.arrival_deadline === "string"
    ? fields.arrival_deadline.match(/(?:^|\D)([01]?\d|2[0-3]):([0-5]\d)(?:\D|$)/) : null;
  let arriveBy = fields.arrive_by;
  if (!arriveBy) {
    const clock = deadlineClock ? deadlineClock[1].padStart(2, "0") + ":" + deadlineClock[2] : "12:00";
    arriveBy = departureDate + "T" + clock + ":00+09:00";
    assumptions.push("模擬用到着希望時刻：" + arriveBy + (deadlineClock
      ? "（日付は未入力のため例示）" : "（具体時刻は未入力のため正午を例示）"));
  }
  let returnBy = fields.return_by;
  if (!returnBy) {
    returnBy = departureDate + "T20:00:00+09:00";
    assumptions.push("模擬用帰着期限：" + returnBy + "（未入力のため同日 20:00 を例示）");
  }
  const travelers = Number.isInteger(fields.travelers) && fields.travelers > 0 ? fields.travelers : 1;
  if (travelers !== fields.travelers) assumptions.push("模擬用人数：1 名（人数未入力のため例示）");
  const lodgingRequired = typeof fields.lodging_required === "boolean" ? fields.lodging_required : false;
  if (lodgingRequired !== fields.lodging_required) assumptions.push("模擬用宿泊：不要（宿泊の要否が未入力のため例示）");
  const purpose = typeof fields.purpose === "string" && fields.purpose.trim() ? fields.purpose : "出張条件の確認";
  if (!fields.purpose) assumptions.push("模擬用目的：出張条件の確認（目的が未入力のため例示）");
  return {
    trip: {
      schema_version: "1.0", trip_id: crypto.randomUUID(), company_id: null, employee_id: null,
      origin: fields.origin || null, destination: fields.destination || null,
      departure_at: departureAt, arrive_by: arriveBy, return_by: returnBy,
      purpose, travelers, lodging_required: lodgingRequired, confirmed: true,
    },
    assumptions,
  };
}

function knownSimulationSubtotal(plan) {
  return plan.costs.reduce((total, item) => {
    if (item.unit_amount === null || item.quantity === null) return total;
    return total + item.unit_amount * item.quantity;
  }, 0);
}

function yen(amount) {
  return "¥" + amount.toLocaleString("ja-JP");
}

function displayTokyoDateTime(value) {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo", year: "numeric", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date(value));
}

function renderProject(project) {
  state.project = project;
  byId("project-overview").hidden = false;
  byId("project-title").textContent = project.project_name;
  byId("project-document-count").textContent = `関連資料 ${project.documents.length} 件`;
  const fields = byId("project-fields");
  fields.replaceChildren();
  for (const [key, label] of Object.entries(fieldLabels)) {
    const value = project.fields[key];
    if (value === undefined) continue;
    const row = node("div", undefined, "project-field");
    row.append(node("dt", label), node("dd", displayFieldValue(key, value)));
    fields.append(row);
  }

  const documents = byId("project-documents");
  documents.replaceChildren();
  for (const source of project.documents) {
    const card = node("details", undefined, "project-document");
    const summary = node("summary");
    summary.append(
      node("span", source.document_kind === "policy" ? "制度" : "プロジェクト", "source-kind"),
      node("strong", source.title),
      node("small", displayFileName(source.path)),
    );
    card.append(summary, node("pre", source.content, "source-preview"));
    documents.append(card);
  }
  byId("assistant-status").textContent = "";
  updateComposerActions();
  syncPageBookmarks();
  state.proposal = null;
  byId("proposal-panel").hidden = true;
}

async function loadProjects() {
  try {
    state.projects = await api("/api/projects");
    const select = byId("project-select");
    select.replaceChildren(new Option("出張プロジェクトを選択してください", ""));
    for (const project of state.projects) select.add(new Option(project.project_name, project.project_id));
    setProjectMessage(state.projects.length ? "" : "登録済みプロジェクトはありません。");
  } catch (error) {
    if (error.code !== "unauthorized") setProjectMessage(error.message || String(error), true);
  }
}

function renderAssistantMessage(answer, citations = []) {
  const card = node("article", undefined, "chat-message assistant-message");
  card.append(node("span", "旅程 AI", "message-author"), node("p", answer));
  if (citations.length) {
    const details = node("details", undefined, "chat-citations");
    details.append(node("summary", `回答の根拠 · ${citations.length} 件`));
    for (const citation of citations) {
      const item = node("div", undefined, "citation-item");
      item.append(node("strong", `[${citation.reference}] ${citation.title}`),
                  node("small", citation.location || "位置情報なし"),
                  node("p", citation.text || ""));
      details.append(item);
    }
    card.append(details);
  }
  return card;
}

function projectContext() {
  const sections = [];
  if (state.project) {
    sections.push(`選択プロジェクト：${state.project.project_name}`);
    for (const [key, value] of Object.entries(state.project.fields)) {
      sections.push(`${fieldLabels[key] || key}：${displayFieldValue(key, value)}`);
    }
    for (const document of state.project.documents) {
      sections.push(`\n資料：${document.title}\n${document.content}`);
    }
  }
  for (const upload of state.uploads) sections.push(`\n今回追加した資料：${upload.title}\n${upload.content}`);
  return sections.join("\n").slice(0, 12000);
}

function projectContextFields() {
  const fields = state.project ? {...state.project.fields} : {};
  fields.project_id = state.project?.project_id || null;
  fields.project_name = state.project?.project_name || null;
  return fields;
}

async function importFile(file) {
  if (file.size > 25 * 1024 * 1024) throw new Error("ファイルは 25 MiB 以下にしてください。");
  const response = await fetch("/api/import", {
    method: "POST",
    headers: authHeaders({"Content-Type": "application/octet-stream", "X-File-Name": encodeURIComponent(file.name)}),
    body: file,
  });
  const result = await response.json();
  if (response.status === 401) {
    showAccessGate();
    throw new Error(result.message || "チームアクセスコードを入力してください。");
  }
  if (!response.ok) throw new Error(result.message || "ファイルを読み取れませんでした。");
  const preview = result.preview || "";
  state.uploads.push({document_id: result.document_id, title: result.title, content: preview});
  const status = byId("chat-upload-state");
  clearProposal();
  status.textContent = `${result.title} を読み込みました。${result.chunk_count} 個のテキストブロックを会話と計画書に利用できます。${result.extraction_status === "partial" ? "認識できない箇所があるため、原文を確認してください。" : ""}`;
  status.hidden = false;
  updateComposerActions();
  return result;
}

byId("project-select").addEventListener("change", event => {
  const project = state.projects.find(item => item.project_id === event.target.value);
  setProjectMessage("");
  state.chatMessages = [];
  state.followUpAsked = [];
  byId("proposal-panel").before(byId("work-area"));
  clearProposal();
  byId("chat-messages").replaceChildren(renderAssistantMessage(project
    ? `${project.project_name} の登録資料を参照します。`
    : "選択したプロジェクト資料と追加資料をもとに、出張条件を整理します。"));
  if (project) renderProject(project);
  else {
    state.project = null;
    byId("project-overview").hidden = true;
    updateComposerActions();
    syncPageBookmarks();
    byId("assistant-status").textContent = "プロジェクトを選択してください";
  }
});

byId("chat-input").addEventListener("input", updateComposerActions);

byId("chat-file").addEventListener("change", async event => {
  const files = [...event.target.files];
  event.target.value = "";
  if (!files.length) return;
  clearProposal();
  const status = byId("chat-upload-state");
  status.hidden = false;
  status.classList.remove("is-error");
  state.uploading = true;
  updateComposerActions();
  try {
    for (const file of files) {
      status.textContent = `${displayFileName(file.name)} を読み取っています…`;
      await importFile(file);
    }
  } catch (error) {
    status.textContent = error.message || String(error);
    status.classList.add("is-error");
  } finally {
    state.uploading = false;
    updateComposerActions();
  }
});

byId("chat-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (state.activeAction || state.uploading) return;
  const message = byId("chat-input").value.trim();
  if (!message) return;
  const history = state.chatMessages.slice(-12);
  clearProposal();
  state.chatMessages.push({role: "user", content: message});
  appendUserMessage(message);
  byId("chat-input").value = "";
  state.activeAction = "chat";
  updateComposerActions();
  const list = byId("chat-messages");
  const pending = node("article", undefined, "chat-message assistant-message pending-message");
  pending.append(node("span", "旅程 AI", "message-author"), node("p", "登録資料と会話を確認しています…"));
  list.append(pending);
  list.scrollTop = list.scrollHeight;
  try {
    const result = await api("/api/agent/chat", {
      message,
      history,
      trip_context: projectContextFields(),
      project_context: projectContext(),
      project_id: state.project?.project_id || null,
      document_ids: state.uploads.map(upload => upload.document_id),
    });
    pending.replaceWith(renderAssistantMessage(result.answer || "回答を作成できませんでした。", result.citations || []));
    state.chatMessages.push({role: "assistant", content: result.answer || ""});
  } catch (error) {
    pending.replaceWith(renderAssistantMessage(error.message || String(error)));
    state.chatMessages.push({role: "assistant", content: error.message || String(error)});
  } finally {
    state.activeAction = null;
    updateComposerActions();
    list.scrollTop = list.scrollHeight;
    byId("chat-input").focus();
  }
});

function valueOrUnknown(value, key) {
  if (value === undefined || value === null || value === "") return "未確認";
  return displayFieldValue(key, value);
}

async function buildProposal() {
  if (!state.project) throw new Error("先に出張プロジェクトを選択してください。");
  const userNotes = state.chatMessages.filter(message => message.role === "user").map(message => message.content);
  const fields = {...state.project.fields};
  if (userNotes.length) {
    const origin = fields.origin || "";
    const destination = fields.destination || "";
    const text = `${origin && destination ? `${origin}から${destination}へ ` : ""}${userNotes.join("。")}`;
    try {
      const baseTime = tokyoIso();
      const parsed = await api("/api/intent/extract", {text, base_time: baseTime});
      for (const key of ["origin", "destination", "purpose", "travelers", "lodging_required", "departure_at", "arrive_by", "return_by"]) {
        if (parsed.trip?.[key] !== undefined && parsed.trip[key] !== null) fields[key] = parsed.trip[key];
      }
    } catch (_error) {
      // The original project facts and user notes remain in the draft when extraction is unavailable.
    }
  }
  const missing = [];
  for (const [key, label] of [["departure_at", "希望出発日時"], ["arrive_by", "到着希望日時"], ["return_by", "希望帰着日時"], ["travelers", "出張人数"], ["lodging_required", "宿泊の要否"]]) {
    if (fields[key] === undefined) missing.push(label);
  }
  const deadlineKnown = fields.arrival_deadline !== undefined && fields.arrival_deadline !== "未確認";
  if (fields.arrive_by === undefined && !deadlineKnown && !missing.includes("到着希望日時")) missing.push("到着希望日時");
  const policyDocument = state.project.documents.find(document => document.document_kind === "policy");
  const policyExcerpt = policyDocument
    ? policyDocument.content
    : "出張旅費規程の資料が登録されていないため、交通費・宿泊費・日当の取扱いは未確認です。";
  const route = `${valueOrUnknown(fields.origin, "origin")} → ${valueOrUnknown(fields.destination, "destination")}`;
  const budget = fields.budget_jpy === undefined ? "未設定" : valueOrUnknown(fields.budget_jpy, "budget_jpy");
  const simulation = simulationScenario(fields);
  let simulationResult = null;
  let simulationError = "";
  try {
    simulationResult = await api("/api/simulation/offers", simulation.trip);
  } catch (error) {
    simulationError = error.message || String(error);
  }
  const simulationLines = simulationResult?.plans?.length
    ? simulationResult.plans.flatMap(plan => {
      const details = simulationResult.details?.[plan.plan_id] || {};
      const outbound = plan.legs.find(leg => leg.direction === "outbound");
      const returning = plan.legs.find(leg => leg.direction === "return");
      const subtotal = knownSimulationSubtotal(plan);
      const budgetDelta = typeof fields.budget_jpy === "number" ? subtotal - fields.budget_jpy : null;
      const arrivalsInTime = outbound && new Date(outbound.arrival_at) <= new Date(simulation.trip.arrive_by);
      return [
        "- " + (details.plan_name || plan.plan_id) + "（模擬）",
        "  往路：" + (outbound ? displayTokyoDateTime(outbound.departure_at) + " → " + displayTokyoDateTime(outbound.arrival_at) : "未設定") + "（時刻は模擬）",
        "  到着希望時刻との比較：" + (arrivalsInTime ? "例示条件内" : "例示条件に不適合") + "（模擬時刻）",
        "  復路：" + (returning ? displayTokyoDateTime(returning.departure_at) + " → " + displayTokyoDateTime(returning.arrival_at) : "未設定") + "（時刻は模擬）",
        "  既知費目の模擬小計：" + yen(subtotal) + "（日当など金額不明の費目を除く）",
        "  予算との比較：" + (budgetDelta === null ? "予算未登録" : budgetDelta > 0 ? yen(budgetDelta) + " 超過" : yen(-budgetDelta) + " 以内"),
        "  空席：" + (details.seat_inventory?.label || "未確認"),
        ...(details.hotel ? ["  宿泊候補：" + details.hotel.name + "、" + yen(details.hotel.nightly_price_jpy) + "／泊（架空の施設・金額）"] : []),
      ];
    })
    : ["模擬データの生成を完了できませんでした：" + (simulationError || "返却データがありません。")];
  const lines = [
    `# ${state.project.project_name} 出張計画書`,
    "",
    `作成日：${new Date().toLocaleDateString("ja-JP")}`,
    "",
    "## 出張概要",
    "",
    `- 対象プロジェクト：${state.project.project_name}`,
    `- 出張目的：${valueOrUnknown(fields.purpose, "purpose")}`,
    `- 行程：${route}`,
    `- 出張期間：${valueOrUnknown(fields.duration_limit_days, "duration_limit_days")}`,
    `- 到着希望時刻：${valueOrUnknown(fields.arrival_deadline, "arrival_deadline")}`,
    `- 出発日時：${valueOrUnknown(fields.departure_at, "departure_at")}`,
    `- 到着期限：${valueOrUnknown(fields.arrive_by, "arrive_by")}`,
    `- 帰着期限：${valueOrUnknown(fields.return_by, "return_by")}`,
    `- 出張人数：${valueOrUnknown(fields.travelers, "travelers")}`,
    `- 宿泊：${valueOrUnknown(fields.lodging_required, "lodging_required")}`,
    `- 予算上限：${budget}`,
    "",
    "## 登録済みの出張旅費規程",
    "",
    ...policyExcerpt.split(/\r?\n/),
    "",
    "## 行程案と費用",
    "",
    "### ローカル模擬データによる比較",
    "",
    ...simulationLines,
    "この比較は固定の模擬値であり、実際の運行・見積り結果ではありません。空席・予約可否・実運賃は未確認です。日当など金額が確認できない費目は模擬小計に含めていません。",
    "宿泊が必要な場合に表示する施設名・位置・料金は架空の模擬値です。実在施設の案内や予約には使えません。",
    "",
    `${route} の出張を計画します。登録期間は ${valueOrUnknown(fields.duration_limit_days, "duration_limit_days")} です。実際の運行情報に基づく行程は未取得です。上記の模擬時刻と、実際の出張条件を分けて確認してください。`,
    `予算上限は ${budget} です。実際の交通費見積りを取得していないため、実費に基づく予算内判定と総額は未確認です。模擬小計と実際の費用は区別してください。`,
    "宿泊が必要な場合は、規程記載額と実際の宿泊費を照合し、差額の取扱いを承認者に確認してください。",
    "",
  ];
  return {markdown: lines.join("\n"), fields, missing, policyDocument, userNotes};
}

function renderProposal(proposal) {
  const content = byId("proposal-content");
  content.replaceChildren();
  const lines = proposal.markdown.split("\n");
  const title = lines.find(line => line.startsWith("# "))?.slice(2) || "出張計画書";
  const createdAt = lines.find(line => line.startsWith("作成日："))?.slice("作成日：".length) || "";
  const documentHeader = node("header", undefined, "proposal-document-heading");
  documentHeader.append(node("h2", title, "proposal-document-title"));
  if (createdAt) {
    const date = node("div", undefined, "proposal-created-at");
    date.append(node("span", "作成日"), node("time", createdAt));
    documentHeader.append(date);
  }
  content.append(documentHeader);

  let section = null;
  let sectionName = "";
  let facts = null;
  let options = null;
  let activeOption = null;
  let proposalNotes = null;
  let list = null;
  const splitPair = value => {
    const matched = value.match(/^([^：:]+)[：:、]\s*(.*)$/);
    return matched ? [matched[1].trim(), matched[2].trim()] : null;
  };
  const addDetail = (parent, label, value, className) => {
    const row = node("div", undefined, className);
    row.append(node("span", label, `${className}-label`), node("span", value, `${className}-value`));
    parent.append(row);
    return row;
  };

  for (const line of lines) {
    if (line.startsWith("# ") || line.startsWith("作成日：") || !line.trim()) {
      list = null;
      continue;
    }
    if (line.startsWith("## ")) {
      sectionName = line.slice(3).trim();
    section = node("section", undefined, `proposal-section ${sectionName === "行程案と費用" ? "proposal-travel-section" : ""}`.trim());
      section.append(node("h3", sectionName, "proposal-section-title"));
      content.append(section);
      facts = sectionName === "出張概要" ? node("div", undefined, "proposal-facts") : null;
      options = null;
      if (facts) section.append(facts);
      activeOption = null;
      list = null;
      continue;
    }
    if (line.startsWith("### ")) {
      activeOption = null;
      list = null;
      if (section) section.append(node("h4", line.slice(4).trim(), "proposal-subtitle"));
      if (sectionName === "行程案と費用" && !options) {
        options = node("div", undefined, "proposal-options");
        section?.append(options);
      }
      continue;
    }
    if (line.startsWith("- ")) {
      const value = line.slice(2).trim();
      if (facts) {
        const pair = splitPair(value);
        if (pair) addDetail(facts, pair[0], pair[1], "proposal-fact");
      } else if (options) {
        activeOption = node("article", undefined, "proposal-option");
        const optionHeading = node("div", undefined, "proposal-option-heading");
        const isMock = /（模擬）$/.test(value);
        optionHeading.append(node("h4", value.replace(/（模擬）$/, "")));
        if (isMock) optionHeading.append(node("span", "模擬案", "proposal-option-badge"));
        activeOption.append(optionHeading);
        const details = node("div", undefined, "proposal-option-details");
        activeOption.append(details);
        options.append(activeOption);
      } else if (sectionName === "行程案と費用") {
        options = node("div", undefined, "proposal-options");
        section?.append(options);
        activeOption = node("article", undefined, "proposal-option");
        const optionHeading = node("div", undefined, "proposal-option-heading");
        const isMock = /（模擬）$/.test(value);
        optionHeading.append(node("h4", value.replace(/（模擬）$/, "")));
        if (isMock) optionHeading.append(node("span", "模擬案", "proposal-option-badge"));
        activeOption.append(optionHeading, node("div", undefined, "proposal-option-details"));
        options.append(activeOption);
      } else {
        if (!list) {
          list = node("ul", undefined, "proposal-list");
          section?.append(list);
        }
        list.append(node("li", value));
      }
      continue;
    }
    if (/^\s{2,}/.test(line) && activeOption) {
      const pair = splitPair(line.trim());
      if (pair) {
        const details = activeOption.querySelector(".proposal-option-details");
        const detail = addDetail(details, pair[0], pair[1], "proposal-option-detail");
          if (pair[0] === "予算との比較") detail.classList.add(pair[1].includes("超過") ? "is-over-budget" : "is-within-budget");
          if (pair[0] === "往路" || pair[0] === "復路") detail.classList.add("is-route");
      } else {
        activeOption.append(node("p", line.trim(), "proposal-option-note"));
      }
      list = null;
      continue;
    }
    activeOption = null;
    list = null;
    if (sectionName === "行程案と費用" && section) {
      if (!proposalNotes) {
        proposalNotes = node("aside", undefined, "proposal-notes");
        proposalNotes.append(node("span", "模擬データの確認事項", "proposal-notes-title"));
        section.append(proposalNotes);
      }
      proposalNotes.append(node("p", line.trim(), "proposal-note"));
    } else if (section) {
      section.append(node("p", line.trim(), "proposal-copy"));
    }
  }
  byId("proposal-panel").hidden = false;
  syncPageBookmarks();
  byId("proposal-panel").scrollIntoView({behavior: "smooth", block: "start"});
}

function downloadText(content, filename) {
  const url = URL.createObjectURL(new Blob([content], {type: "text/markdown;charset=utf-8"}));
  const link = node("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

byId("create-proposal").addEventListener("click", async () => {
  if (state.activeAction || state.uploading || !state.project) return;
  clearEmailDraft();
  const draftNote = byId("chat-input").value.trim();
  if (draftNote) {
    state.chatMessages.push({role: "user", content: draftNote});
    appendUserMessage(draftNote, "計画書に反映する条件");
    byId("chat-input").value = "";
  }
  state.activeAction = "proposal";
  updateComposerActions();
  try {
    state.proposal = await buildProposal();
    renderProposal(state.proposal);
    askFollowUpQuestions(state.proposal.missing);
  } catch (error) {
    setProjectMessage(error.message || String(error), true);
  } finally {
    state.activeAction = null;
    updateComposerActions();
  }
});

byId("download-proposal").addEventListener("click", () => {
  if (state.proposal) downloadText(state.proposal.markdown, `${state.project.project_name}_出張計画書.md`);
});

byId("generate-email").addEventListener("click", () => {
  if (!state.project) return;
  byId("email-panel").hidden = false;
  syncPageBookmarks();
  setActivePage("email-panel");
  byId("email-panel").scrollIntoView({behavior: "smooth", block: "start"});
  byId("email-recipient").focus({preventScroll: true});
});

function manualEmailTemplate(projectName, recipient, purpose) {
  const name = projectName || "出張プロジェクト";
  return {
    subject: `【出張計画のご確認】${name}`,
    body: `${recipient || "{{宛名}}"} 様\n\nお疲れさまです。\n${name}に関する出張について、${purpose || "下記の内容"}をご確認いただきたく、ご連絡しました。\n\n【出張目的】\n（目的を入力してください）\n\n【行程・費用】\n（計画書を確認して内容を入力してください）\n\n【確認・ご対応いただきたいこと】\n（確認事項や希望期限を入力してください）\n\nお手数をおかけしますが、よろしくお願いいたします。\n（差出人名）`,
  };
}

function showEmailDraft(draft, message) {
  byId("email-subject").value = draft.subject || "";
  byId("email-body").value = draft.body || "";
  byId("email-output").hidden = false;
  syncPageBookmarks();
  const status = byId("email-status");
  status.textContent = message;
  status.classList.toggle("is-error", draft.status !== "success");
  status.hidden = false;
  byId("email-output").scrollIntoView({behavior: "smooth", block: "nearest"});
}

byId("email-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (state.mailBusy || state.activeAction || state.uploading || !state.project) return;
  const recipient = byId("email-recipient").value.trim();
  const purpose = byId("email-purpose").value.trim() || "出張計画の共有・確認依頼";
  const conversation = state.chatMessages.slice(-10)
    .map(message => `${message.role === "user" ? "本人" : "旅程 AI"}：${message.content}`);
  const currentNote = byId("chat-input").value.trim();
  if (currentNote) conversation.push(`本人：${currentNote}`);
  state.mailBusy = true;
  byId("create-email-draft").textContent = "メール文を作成中…";
  const status = byId("email-status");
  status.textContent = "メール文を作成しています…";
  status.hidden = false;
  status.classList.remove("is-error");
  updateComposerActions();
  try {
    const result = await api("/api/email/generate", {
      project_name: state.project.project_name,
      recipient,
      purpose,
      project_context: projectContext(),
      plan_context: state.proposal?.markdown || "",
      conversation_context: conversation.join("\n").slice(0, 12000),
    });
    showEmailDraft(result, result.status === "success"
      ? "メール文を作成しました。内容を確認してご利用ください。"
      : "メール作成機能は現在メンテナンス中です。以下のテンプレートに入力してください。");
  } catch (_error) {
    const fallback = manualEmailTemplate(state.project.project_name, recipient, purpose);
    showEmailDraft(fallback, "メール作成機能は現在メンテナンス中です。以下のテンプレートに入力してください。");
  } finally {
    state.mailBusy = false;
    byId("create-email-draft").textContent = "メール文を作成";
    updateComposerActions();
  }
});

byId("copy-email").addEventListener("click", async () => {
  const value = `件名：${byId("email-subject").value}\n\n${byId("email-body").value}`;
  try {
    await navigator.clipboard.writeText(value);
    byId("email-status").textContent = "メール文をコピーしました。";
    byId("email-status").classList.remove("is-error");
  } catch (_error) {
    byId("email-status").textContent = "コピーできませんでした。件名と本文を選択してコピーしてください。";
    byId("email-status").classList.add("is-error");
  }
});

byId("access-form").addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const result = await api("/api/login", {password: byId("access-password").value});
    sessionStorage.setItem("team-access-token", result.token);
    byId("access-gate").hidden = true;
    byId("access-password").value = "";
    await loadProjects();
  } catch (error) {
    byId("access-error").textContent = error.message || String(error);
    byId("access-error").hidden = false;
  } finally {
    button.disabled = false;
  }
});

loadProjects();
updateComposerActions();
