"use strict";

const state = {chatMessages: [], uploads: [], proposal: null, proposalFollowupAnswer: "", activeAction: null, uploading: false, mailBusy: false, followUpAsked: []};
const byId = id => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const fieldLabels = {
  origin: "出発地", destination: "目的地",
  budget_jpy: "予算上限", duration_limit_days: "出張期間",
  arrival_deadline: "到着希望時刻", purpose: "出張目的", departure_at: "出発日時",
  arrive_by: "到着希望日時", return_by: "帰着希望日時",
  lodging_required: "宿泊",
};

const pageOrder = ["work-area", "proposal-panel", "email-panel"];
let activePage = "work-area";
let pageScrollFrame = 0;

function syncPageBookmarks() {
  const available = {
    "work-area": true,
    "proposal-panel": Boolean(state.proposal),
    "email-panel": Boolean(state.proposal?.selectedPlanId),
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
  if (!pageOrder.includes(pageId)) pageId = "work-area";
  activePage = pageId;
  const onConsultation = pageId === "work-area";
  const workArea = byId("work-area");
  const proposalPanel = byId("proposal-panel");
  const emailPanel = byId("email-panel");
  if (workArea) workArea.hidden = !onConsultation;
  if (proposalPanel) proposalPanel.hidden = pageId !== "proposal-panel" || !state.proposal;
  if (emailPanel) emailPanel.hidden = pageId !== "email-panel" || !state.proposal?.selectedPlanId;
  syncPageBookmarks();
}

function openPage(pageId) {
  if (pageId === "proposal-panel" && !state.proposal) return;
  if (pageId === "email-panel" && !state.proposal?.selectedPlanId) return;
  const target = byId(pageId);
  // A page is intentionally hidden while another page is active. Do not use
  // the current `hidden` state as an availability check, otherwise the
  // previous-page action can never navigate back to the hidden page.
  if (!target) return;
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
    if ((target === "work-area") || (target === "proposal-panel" && state.proposal) || (target === "email-panel" && state.proposal?.selectedPlanId)) {
      openPage(target);
      return;
    }
  }
});
byId("next-page").addEventListener("click", () => {
  const currentIndex = pageOrder.indexOf(activePage);
  for (let index = currentIndex + 1; index < pageOrder.length; index += 1) {
    const target = pageOrder[index];
    if ((target === "work-area") || (target === "proposal-panel" && state.proposal) || (target === "email-panel" && state.proposal?.selectedPlanId)) {
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
    if (visible[0]) setActivePage(visible[0].id);
  }, {passive: true});
}, {passive: true});
syncPageBookmarks();

function authHeaders(extra = {}) {
  const token = sessionStorage.getItem("team-access-token");
  return {...extra, ...(token ? {Authorization: `Bearer ${token}`} : {})};
}

async function refreshAssistantStatus() {
  const status = byId("assistant-status");
  try {
    const result = await api("/api/agent/status");
    status.textContent = result.model_configured
      ? "AI接続設定済み・接続は質問時に確認"
      : "AI API未設定・管理者の設定が必要です";
    status.classList.toggle("is-unavailable", !result.model_configured);
  } catch (error) {
    if (error.code !== "unauthorized") {
      status.textContent = "AI接続状態を確認できません";
      status.classList.add("is-unavailable");
    }
  }
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

async function deleteApi(path) {
  const response = await fetch(path, {method: "DELETE", headers: authHeaders()});
  const value = await response.json();
  if (response.status === 401) {
    showAccessGate();
    const error = new Error(value.message || "チームアクセスコードを入力してください。");
    error.code = "unauthorized";
    throw error;
  }
  if (!response.ok) throw new Error(value.message || "資料を削除できませんでした。");
  return value;
}

async function loadUploadedDocuments() {
  try {
    const records = await api("/api/snapshots");
    const storedUploads = records
      .filter(record => /^upload_[0-9a-f]{32}$/.test(record.document_id))
      .map(record => ({document_id: record.document_id, snapshot_id: record.snapshot_id, title: record.title, content: ""}));
    const current = new Map(state.uploads.map(item => [item.snapshot_id, item]));
    for (const item of storedUploads) if (!current.has(item.snapshot_id)) current.set(item.snapshot_id, item);
    state.uploads = [...current.values()];
    renderUploadList();
    updateComposerActions();
  } catch (error) {
    if (error.code !== "unauthorized") {
      const status = byId("chat-upload-state");
      status.textContent = "保存済み資料一覧を読み込めませんでした。";
      status.hidden = false;
      status.classList.add("is-error");
    }
  }
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

function renderUploadList() {
  const list = byId("chat-upload-list");
  list.replaceChildren();
  list.hidden = !state.uploads.length;
  for (const upload of state.uploads) {
    const item = node("div", undefined, "chat-upload-item");
    item.setAttribute("role", "listitem");
    const title = node("span", upload.title, "chat-upload-title");
    const remove = node("button", "削除", "chat-upload-remove");
    remove.type = "button";
    remove.setAttribute("aria-label", `${upload.title}を削除`);
    remove.addEventListener("click", () => removeUpload(upload));
    item.append(title, remove);
    list.append(item);
  }
}

async function removeUpload(upload) {
  if (state.activeAction || state.uploading || !upload.snapshot_id) return;
  if (!window.confirm(`${upload.title}をこの会話から削除しますか？資料スナップショットと検索インデックスも削除されます。`)) return;
  state.uploading = true;
  updateComposerActions();
  try {
    await deleteApi(`/api/documents/${encodeURIComponent(upload.snapshot_id)}`);
    state.uploads = state.uploads.filter(item => item.snapshot_id !== upload.snapshot_id);
    renderUploadList();
    clearProposal();
    const status = byId("chat-upload-state");
    status.textContent = `${upload.title}を削除しました。`;
    status.hidden = false;
    status.classList.remove("is-error");
  } catch (error) {
    const status = byId("chat-upload-state");
    status.textContent = error.message || String(error);
    status.hidden = false;
    status.classList.add("is-error");
  } finally {
    state.uploading = false;
    updateComposerActions();
  }
}

function updateComposerActions() {
  const busy = Boolean(state.activeAction || state.uploading || state.mailBusy);
  const hasContext = true;
  const send = byId("send-chat");
  const create = byId("create-proposal");
  const email = byId("generate-email");
  send.disabled = busy || !hasContext || !byId("chat-input").value.trim();
  create.disabled = busy || (!state.chatMessages.some(message => message.role === "user") && !byId("chat-input").value.trim());
  email.disabled = busy || !state.proposal?.selectedPlanId;
  send.textContent = state.activeAction === "chat" ? "回答を作成中…" : "会話で相談 ↗";
  create.textContent = state.activeAction === "proposal" ? "計画書を作成中…" : "計画書を作成 →";
  byId("chat-input").disabled = busy;
  byId("chat-file").disabled = busy;
  byId("proposal-followup-submit").disabled = busy;
  byId("proposal-followup-submit").textContent = state.activeAction === "chat"
    ? "AIに相談しています…" : "AIに相談して計画書を更新";
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
    "出張の起点として、会社の所在地とご希望の出発地のどちらを使いますか？",
    "今回の出張に適用する旅費規程をご存じですか？",
  ];
  const newQuestions = questions.filter(question => !state.followUpAsked.includes(question));
  if (!newQuestions.length) return false;
  state.followUpAsked.push(...newQuestions);
  const answer = [
    "計画書の作成に必要な条件が未確認です。分かる範囲で次の点を教えてください。",
    ...newQuestions.map(question => `・${question}`),
    "回答を入力して「会話で相談」を押すと、AI が内容を確認します。その後「計画書を作成」を押すと反映します。",
  ].join("\n");
  state.chatMessages.push({role: "assistant", content: answer});
  const messages = byId("chat-messages");
  messages.append(renderAssistantMessage(answer));
  messages.scrollTop = messages.scrollHeight;
  byId("work-area").scrollIntoView({behavior: "smooth", block: "start"});
  byId("chat-input").focus();
  return true;
}

function displayFieldValue(key, value) {
  if (value === true) return "必要";
  if (value === false) return "不要";
  if (key === "budget_jpy" && typeof value === "number") return `¥${value.toLocaleString("ja-JP")}`;
  if (key === "duration_limit_days" && typeof value === "number") return `${value}日以内`;
  return String(value);
}

function displayUploadName(filename) {
  const name = String(filename).split(/[\\/]/).pop() || "追加資料";
  const extensionIndex = name.lastIndexOf(".");
  return extensionIndex > 0 ? name.slice(0, extensionIndex) : name;
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
  const lodgingRequired = typeof fields.lodging_required === "boolean" ? fields.lodging_required : false;
  if (lodgingRequired !== fields.lodging_required) assumptions.push("模擬用宿泊：不要（宿泊の要否が未入力のため例示）");
  const purpose = typeof fields.purpose === "string" && fields.purpose.trim() ? fields.purpose : "出張条件の確認";
  if (!fields.purpose) assumptions.push("模擬用目的：出張条件の確認（目的が未入力のため例示）");
  return {
    trip: {
      schema_version: "1.0", trip_id: crypto.randomUUID(), company_id: null, employee_id: null,
      origin: fields.origin || null, destination: fields.destination || null,
      departure_at: departureAt, arrive_by: arriveBy, return_by: returnBy,
      purpose, lodging_required: lodgingRequired, confirmed: true,
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

function uploadedDocumentContext() {
  return state.uploads.map(upload => `資料：${upload.title}\n${upload.content}`).join("\n\n").slice(0, 12000);
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
  state.uploads.push({document_id: result.document_id, snapshot_id: result.snapshot_id, title: result.title, content: preview});
  renderUploadList();
  const status = byId("chat-upload-state");
  clearProposal();
  status.textContent = `${result.title} を読み込みました。${result.chunk_count} 個のテキストブロックを会話と確認処理に利用できます。${result.extraction_status === "partial" ? "認識できない箇所があるため、原文を確認してください。" : ""}`;
  status.hidden = false;
  updateComposerActions();
  return result;
}

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
      status.textContent = `${displayUploadName(file.name)} を読み取っています…`;
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
  state.proposalFollowupAnswer = "";
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
      trip_context: {},
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
  const userNotes = state.chatMessages.filter(message => message.role === "user").map(message => message.content);
  const fields = {};
  if (userNotes.length) {
    try {
      const baseTime = tokyoIso();
      // Parse each user message separately. Combining old and new messages
      // made the parser treat a previous route/date as the latest condition,
      // so follow-up answers could not reliably override the draft.
      for (const text of userNotes) {
        const parsed = await api("/api/intent/extract", {text, base_time: baseTime});
        for (const key of ["origin", "destination", "purpose", "lodging_required", "departure_at", "arrive_by", "return_by"]) {
          if (parsed.trip?.[key] !== undefined && parsed.trip[key] !== null) fields[key] = parsed.trip[key];
        }
        if (Number.isInteger(parsed.budget_jpy) && parsed.budget_jpy > 0) fields.budget_jpy = parsed.budget_jpy;
      }
    } catch (error) {
      throw new Error(`入力した条件を確認できませんでした。通信状態を確認して、もう一度お試しください。${error.message ? `（${error.message}）` : ""}`);
    }
  }
  const missing = [];
  const hasValue = value => value !== undefined && value !== null && value !== "" && value !== "未確認";
  for (const [key, label] of [
    ["origin", "出発地"], ["destination", "目的地"], ["purpose", "出張目的"],
    ["departure_at", "希望出発日時"], ["arrive_by", "到着希望日時"], ["return_by", "希望帰着日時"],
  ]) {
    if (!hasValue(fields[key])) missing.push(label);
  }
  if (typeof fields.lodging_required !== "boolean") missing.push("宿泊の要否");
  const route = `${valueOrUnknown(fields.origin, "origin")} → ${valueOrUnknown(fields.destination, "destination")}`;
  const budget = fields.budget_jpy === undefined ? "未設定" : valueOrUnknown(fields.budget_jpy, "budget_jpy");
  const simulation = simulationScenario(fields);
  const uploadedIds = [...new Set(state.uploads.map(item => item.document_id))];
  const uploadedSnapshots = [...new Set(state.uploads.map(item => item.snapshot_id).filter(Boolean))];
  let policyEvidence = [];
  let policyEvidenceError = "";
  if (uploadedIds.length && uploadedSnapshots.length) {
    try {
      const search = await api("/api/search", {
        company_id: null,
        document_ids: uploadedIds,
        snapshot_ids: uploadedSnapshots,
        usage_mode: "demo",
        query: `${fields.purpose || "出張"} 旅費 規程 制度 条件 上限 申請 承認 交通費 宿泊費 キャンセル 変更`,
        limit: 8,
      });
      policyEvidence = (search.results || []).map(hit => ({
        title: hit.title,
        article_label: hit.chunk?.article_label || "",
        locations: hit.chunk?.locations || [],
        text: hit.chunk?.text || "",
      })).filter(item => item.text);
    } catch (error) {
      policyEvidenceError = error.message || String(error);
    }
  }
  let simulationResult = null;
  let simulationError = "";
  try {
    simulationResult = await api("/api/simulation/offers", simulation.trip);
  } catch (error) {
    simulationError = error.message || String(error);
  }
  let travelContext = null;
  let contextError = "";
  try {
    travelContext = await api("/api/travel-context", simulation.trip);
  } catch (error) {
    contextError = error.message || String(error);
  }
  let workflowResult = null;
  let workflowError = "";
  const selectedDocuments = [...state.uploads];
  try {
    workflowResult = await api("/api/run", {
      trip: simulation.trip,
      plans: simulationResult?.plans || [],
      document_ids: [...new Set(selectedDocuments.map(document => document.document_id))],
      snapshot_ids: [...new Set(selectedDocuments.map(document => document.snapshot_id).filter(Boolean))],
    });
  } catch (error) {
    workflowError = error.message || String(error);
  }
  const workflowStatusLabels = {
    needs_rule_review: "計算結果と規程を人が確認してください",
    needs_offers: "実際の見積りがないため比較を完了できません",
    needs_information: "必要な出張条件が不足しています",
    needs_confirmation: "出張条件の確認が必要です",
    policy_scope_blocked: "規程資料の確認を中断しました",
  };
  const policyStatusLabels = {
    needs_human_review: "関連する原文候補があります。適用範囲を人が確認してください",
    not_found: "関連する原文候補を取得できませんでした。規程に記載がないことを示すものではありません",
    failed: "規程の検索に失敗しました",
    blocked: "規程資料の対象範囲を確認できませんでした",
  };
  const workflowLines = workflowResult ? [
    `- 処理結果：${workflowStatusLabels[workflowResult.status] || "処理を完了しました"}`,
    ...(workflowResult.comparison?.results || []).flatMap(result => {
      const planName = simulationResult?.details?.[result.plan_id]?.plan_name || result.plan_id;
      return [
        `- ${planName}：行程 ${result.itinerary_valid ? "条件内" : "要確認"}、費用 ${result.cost_complete ? "計算完了" : "未確定"}、予約可否 ${result.available === true ? "確認済み" : "未確認"}`,
        ...result.issues.slice(0, 4).map(issue => `- 要確認：${issue}`),
      ];
    }),
    `- 規程検索：${policyStatusLabels[workflowResult.policy?.status] || (workflowResult.policy ? "検索結果を確認してください" : "利用者が追加した制度資料がありません")}`,
    `- 規程の根拠候補：${workflowResult.policy?.evidence?.length || 0} 件。規程適合は自動判定していません。`,
    "有効な実見積りがないため、費用・時間の順位は作成していません。",
  ] : [
    `- サーバー側の確認を実行できませんでした：${workflowError}`,
    "この計画書にはローカル模擬値のみを表示しています。費用・行程・規程のサーバー側確認は未実施です。通信復旧後に再作成してください。",
  ];
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
  const weatherItems = travelContext?.weather?.data || [];
  const severeWeather = weatherItems.filter(item => item.severity === "severe");
  const contextLines = travelContext ? [
    `- カレンダー：${travelContext.calendar?.data_kind === "simulation" ? "模擬確認" : "確認済み"}`,
    `- 天気：${travelContext.weather?.data_kind === "simulation" ? "模擬確認" : "確認済み"}`,
    ...(weatherItems.map(item => `- ${item.date} ${item.destination}：${item.condition}、移動リスク ${item.transport_risk}`)),
    ...((travelContext.issues || []).map(issue => `- 注意：${issue}`)),
  ] : [`- 日程・天候確認を実行できませんでした：${contextError || "返却データがありません。"}`];
  const missingLines = missing.length ? [
    "## 作成後に確認する条件", "",
    "計画書を先に作成しました。次の条件は未確認のまま模擬値で例示しています。",
    ...missing.map(item => `- ${item}`),
  ] : [];
  const weatherAlertLines = severeWeather.map(item =>
    `! 天候注意：${item.date} の${item.destination}は${item.condition}の模擬判定です。${item.advice}`);
  const policySupplementLines = policyEvidence.length
    ? [
      "",
      "## 添付資料から検索した制度の原文",
      "",
      "以下は利用者が追加した資料をテキストブロック単位で検索して得た原文抜粋です。要約、適用可否の判断、記載されていない条件の補足はしていません。",
      ...policyEvidence.flatMap((item, index) => [
        "",
        `### 根拠 ${index + 1}：${item.title}`,
        ...(item.article_label ? [`条項表示：${item.article_label}`] : []),
        ...item.locations.map(location => `資料位置：${[location.page_number ? `p.${location.page_number}` : "", `ブロック ${location.block_index}`, location.locator].filter(Boolean).join(" / ")}`),
        "原文抜粋：",
        ...item.text.split(/\r?\n/).map(line => `> ${line}`),
      ]),
    ]
    : [
      "",
      "## 添付資料から検索した制度の原文",
      "",
      uploadedIds.length
        ? `資料の条項検索を完了できませんでした：${policyEvidenceError || "検索結果に該当箇所がありませんでした。"} 制度を推測して補っていません。`
        : "利用者から資料が追加されていないため、制度の補足は作成していません。資料を追加して計画書を作り直すと、該当する原文抜粋を表示します。",
    ];
  const lines = [
    "# 出張計画書",
    "",
    `作成日：${new Date().toLocaleDateString("ja-JP")}`,
    "",
    "## 出張概要",
    "",
    "- 対象：今回の出張",
    `- 出張目的：${valueOrUnknown(fields.purpose, "purpose")}`,
    `- 行程：${route}`,
    `- 出張期間：${valueOrUnknown(fields.duration_limit_days, "duration_limit_days")}`,
    `- 到着希望時刻：${valueOrUnknown(fields.arrival_deadline, "arrival_deadline")}`,
    `- 出発日時：${valueOrUnknown(fields.departure_at, "departure_at")}`,
    `- 到着期限：${valueOrUnknown(fields.arrive_by, "arrive_by")}`,
    `- 帰着期限：${valueOrUnknown(fields.return_by, "return_by")}`,
    `- 宿泊：${valueOrUnknown(fields.lodging_required, "lodging_required")}`,
    `- 予算上限：${budget}`,
    "",
    "## サーバー側の確認結果",
    "",
    ...workflowLines,
    "",
    "## 日程・天候・移動リスク",
    "",
    ...contextLines,
    ...simulation.assumptions.map(item => `- ${item}`),
    ...weatherAlertLines,
    "",
    ...missingLines,
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
    ...policySupplementLines,
    "",
  ];
  return {markdown: lines.join("\n"), fields, missing, userNotes, travelContext,
    simulationResult, policyEvidence, selectedPlanId: null};
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
  const selectionStatus = node("p", "計画書内の案を 1 つ選択してください。選択後に承認メールを作成できます。", "proposal-selection-status");
  selectionStatus.setAttribute("role", "status");
  documentHeader.append(selectionStatus);
  content.append(documentHeader);

  let section = null;
  let sectionName = "";
  let facts = null;
  let options = null;
  let activeOption = null;
  let proposalNotes = null;
  let list = null;
  let optionIndex = 0;
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
      if (sectionName === "添付資料から検索した制度の原文") {
        section = null;
        facts = null;
        options = null;
        activeOption = null;
        list = null;
        continue;
      }
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
    if (sectionName === "添付資料から検索した制度の原文") continue;
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
        const option = proposal.simulationResult?.plans?.[optionIndex];
        const select = node("button", "この案を選択", "proposal-select-button");
        select.type = "button";
        select.addEventListener("click", () => selectProposalOption(proposal, option?.plan_id, activeOption));
        optionHeading.append(select);
        activeOption.append(optionHeading);
        activeOption.dataset.planId = option?.plan_id || "";
        const details = node("div", undefined, "proposal-option-details");
        activeOption.append(details);
        options.append(activeOption);
        optionIndex += 1;
      } else if (sectionName === "行程案と費用") {
        options = node("div", undefined, "proposal-options");
        section?.append(options);
        activeOption = node("article", undefined, "proposal-option");
        const optionHeading = node("div", undefined, "proposal-option-heading");
        const isMock = /（模擬）$/.test(value);
        optionHeading.append(node("h4", value.replace(/（模擬）$/, "")));
        if (isMock) optionHeading.append(node("span", "模擬案", "proposal-option-badge"));
        const option = proposal.simulationResult?.plans?.[optionIndex];
        const select = node("button", "この案を選択", "proposal-select-button");
        select.type = "button";
        select.addEventListener("click", () => selectProposalOption(proposal, option?.plan_id, activeOption));
        optionHeading.append(select);
        activeOption.append(optionHeading, node("div", undefined, "proposal-option-details"));
        activeOption.dataset.planId = option?.plan_id || "";
        options.append(activeOption);
        optionIndex += 1;
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
    if (line.startsWith("! ") && section) {
      section.append(node("p", line.slice(2).trim(), "proposal-weather-alert"));
    } else if (sectionName === "行程案と費用" && section) {
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
  if (proposal.policyEvidence?.length) {
    const sourceSection = node("section", undefined, "proposal-section policy-evidence-section");
    sourceSection.append(node("h3", "添付資料から検索した制度の原文", "proposal-section-title"));
    sourceSection.append(node("p", "利用者が追加した資料をブロック単位で検索した原文抜粋です。制度の要約や適用可否の判断は行っていません。", "proposal-copy"));
    for (const [index, evidence] of proposal.policyEvidence.entries()) {
      const card = node("article", undefined, "policy-evidence-card");
      card.append(node("h4", `根拠 ${index + 1}：${evidence.title}`, "policy-evidence-title"));
      if (evidence.article_label) card.append(node("p", `条項表示：${evidence.article_label}`, "policy-evidence-location"));
      for (const location of evidence.locations) {
        const position = [location.page_number ? `p.${location.page_number}` : "", `ブロック ${location.block_index}`, location.locator].filter(Boolean).join(" / ");
        if (position) card.append(node("p", `資料位置：${position}`, "policy-evidence-location"));
      }
      const excerpt = node("blockquote", evidence.text, "policy-evidence-quote");
      card.append(excerpt);
      sourceSection.append(card);
    }
    content.append(sourceSection);
  }
  const followup = byId("proposal-followup");
  if (followup) {
    followup.hidden = !proposal.missing.length && !state.proposalFollowupAnswer;
    byId("proposal-followup-missing").textContent = proposal.missing.length
      ? `未確認：${proposal.missing.join("、")}` : "追加確認はありません。";
    const answer = byId("proposal-followup-answer");
    answer.hidden = !state.proposalFollowupAnswer;
    byId("proposal-followup-answer-text").textContent = state.proposalFollowupAnswer;
  }
  byId("proposal-panel").hidden = false;
  setActivePage("proposal-panel");
  const followupTarget = proposal.missing.length ? byId("proposal-followup") : byId("proposal-panel");
  followupTarget.scrollIntoView({behavior: "smooth", block: "start"});
}

function selectProposalOption(proposal, planId) {
  if (!planId) return;
  proposal.selectedPlanId = planId;
  const selected = proposal.simulationResult?.details?.[planId]?.plan_name || planId;
  proposal.selectedPlanName = selected;
  document.querySelectorAll(".proposal-option").forEach(option => {
    const isSelected = option.dataset.planId === planId;
    option.classList.toggle("is-selected", isSelected);
    const button = option.querySelector(".proposal-select-button");
    if (button) button.textContent = isSelected ? "選択中" : "この案を選択";
  });
  const status = document.querySelector(".proposal-selection-status");
  if (status) status.textContent = `選択中：${selected}。この案をもとに承認メールを作成できます。`;
  updateComposerActions();
  syncPageBookmarks();
}

function downloadText(content, filename) {
  const url = URL.createObjectURL(new Blob([content], {type: "text/markdown;charset=utf-8"}));
  const link = node("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function openProposalConfirmation() {
  const draftNote = byId("chat-input").value.trim();
  const userConditions = [
    ...state.chatMessages.filter(message => message.role === "user").map(message => message.content),
    ...(draftNote ? [draftNote] : []),
  ];
  const confirmation = [
    "対象：今回の出張",
    ...(userConditions.length ? ["会話で伝えた条件：", ...userConditions.map(value => `・${value}`)] : []),
  ].join("\n");
  byId("proposal-confirm-content").textContent = confirmation;
  const dialog = byId("proposal-confirm-dialog");
  if (typeof dialog.showModal === "function") dialog.showModal();
  else if (window.confirm(`${confirmation}\n\nこの条件で計画書を作成しますか？`)) generateProposal();
}

async function generateProposal({preserveFollowupAnswer = false} = {}) {
  if (state.activeAction || state.uploading) return;
  if (!preserveFollowupAnswer) state.proposalFollowupAnswer = "";
  const draftNote = byId("chat-input").value.trim();
  clearProposal();
  if (draftNote) {
    state.chatMessages.push({role: "user", content: draftNote});
    appendUserMessage(draftNote, "計画書に反映する条件");
    byId("chat-input").value = "";
  }
  state.activeAction = "proposal";
  updateComposerActions();
  try {
    const proposal = await buildProposal();
    state.proposal = proposal;
    renderProposal(state.proposal);
  } catch (error) {
    const status = byId("chat-upload-state");
    status.textContent = error.message || String(error);
    status.hidden = false;
    status.classList.add("is-error");
  } finally {
    state.activeAction = null;
    updateComposerActions();
  }
}

byId("create-proposal").addEventListener("click", openProposalConfirmation);
byId("cancel-proposal-confirm").addEventListener("click", () => byId("proposal-confirm-dialog").close("cancel"));
byId("confirm-proposal").addEventListener("click", () => {
  byId("proposal-confirm-dialog").close("confirm");
  generateProposal();
});
async function askProposalFollowup(message) {
  const history = state.chatMessages.slice(-12);
  state.chatMessages.push({role: "user", content: message});
  appendUserMessage(message, "計画書への追加条件");
  const answerBox = byId("proposal-followup-answer");
  const answerText = byId("proposal-followup-answer-text");
  answerBox.hidden = false;
  answerText.textContent = "OrcaRouter に相談しています…";
  state.activeAction = "chat";
  updateComposerActions();
  try {
    const result = await api("/api/agent/chat", {
      message,
      history,
      trip_context: state.proposal?.fields || {},
      document_ids: state.uploads.map(upload => upload.document_id),
    });
    state.proposalFollowupAnswer = result.answer || "回答を作成できませんでした。";
  } catch (error) {
    state.proposalFollowupAnswer = error.message || String(error);
  } finally {
    state.chatMessages.push({role: "assistant", content: state.proposalFollowupAnswer});
    const messages = byId("chat-messages");
    messages.append(renderAssistantMessage(state.proposalFollowupAnswer));
    answerText.textContent = state.proposalFollowupAnswer;
    answerBox.hidden = false;
    state.activeAction = null;
    updateComposerActions();
  }
}

byId("proposal-followup-submit").addEventListener("click", async () => {
  const input = byId("proposal-followup-input");
  const value = input.value.trim();
  if (!value || state.activeAction || state.uploading) return;
  input.value = "";
  await askProposalFollowup(value);
  await generateProposal({preserveFollowupAnswer: true});
});

byId("download-proposal").addEventListener("click", () => {
  if (state.proposal) downloadText(state.proposal.markdown, "出張計画書.md");
});

byId("generate-email").addEventListener("click", () => {
  if (!state.proposal?.selectedPlanId) return;
  byId("email-panel").hidden = false;
  syncPageBookmarks();
  setActivePage("email-panel");
  byId("email-panel").scrollIntoView({behavior: "smooth", block: "start"});
  byId("email-recipient").focus({preventScroll: true});
});

function manualEmailTemplate(planTitle, recipient, purpose) {
  const name = planTitle || "出張計画";
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
  if (state.mailBusy || state.activeAction || state.uploading) return;
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
      plan_title: "出張計画",
      recipient,
      purpose,
      document_context: uploadedDocumentContext(),
      plan_context: state.proposal
        ? `${state.proposal.markdown}\n\nユーザーが選択した案：${state.proposal.selectedPlanName || state.proposal.selectedPlanId}`
        : "",
      conversation_context: conversation.join("\n").slice(0, 12000),
    });
    showEmailDraft(result, result.status === "success"
      ? "メール文を作成しました。内容を確認してご利用ください。"
      : "メール作成機能は現在メンテナンス中です。以下のテンプレートに入力してください。");
  } catch (_error) {
    const fallback = manualEmailTemplate("出張計画", recipient, purpose);
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
    updateComposerActions();
    refreshAssistantStatus();
    loadUploadedDocuments();
  } catch (error) {
    byId("access-error").textContent = error.message || String(error);
    byId("access-error").hidden = false;
  } finally {
    button.disabled = false;
  }
});

updateComposerActions();
refreshAssistantStatus();
loadUploadedDocuments();
