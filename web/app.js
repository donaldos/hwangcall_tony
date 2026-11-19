// 상담 보조 화면 (CLAUDE.md 6장)
//
// 오디오 상태: idle ─[녹음]→ recording ─[중단]→ finalizing ─(stopped)→ idle
// AI 의견은 오디오 상태와 따로 돈다: stopped 직후 자동 요청되고, 그동안에도 다음 녹음을 시작할 수 있다.
const FINALIZE_TIMEOUT_MS = 15000; // 서버 측 상한(기본 8초)보다 길게
const STICK_THRESHOLD_PX = 80; // 바닥에서 이 안쪽이면 새 내용에 맞춰 자동 스크롤
const EMPTY_CHAT_HTML =
  '<div class="chat-empty">상담자 정보를 입력하고 [적용]한 뒤<br>[녹음]을 누르면 통화 내용과 AI 의견이 여기에 차례로 표시됩니다.</div>';
const PROFILE_FIELDS = ["name", "age", "gender", "traits", "concern"];
const PROFILE_LABELS = { name: "호칭", age: "나이", gender: "성별", traits: "특징", concern: "고민" };

const $ = (id) => document.getElementById(id);
const els = {
  form: $("profile-form"),
  profileState: $("profile-state"),
  newSession: $("btn-new"),
  save: $("btn-save"),
  chat: $("chat"),
  jump: $("btn-jump"),
  dot: $("status-dot"),
  status: $("status-text"),
  meterFill: $("meter-fill"),
  meterDb: $("meter-db"),
  record: $("btn-record"),
  recordLabel: $("record-label"),
  toast: $("toast"),
};

let audioState = "idle"; // idle | recording | finalizing
let ws = null;
let audio = null; // { ctx, stream, node }
let config = null;
let finalizeTimer = null;
let turnCount = 0;
let currentTurn = null; // { id, number, finals: [], body, partialEl }
let appliedProfile = emptyProfile();
let entries = []; // 저장용 기록
let unsaved = false;
let savedId = null; // 한 번 저장한 상담은 같은 기록을 갱신한다
let startedAt = null;
const adviceRequests = new Set(); // 진행 중인 AbortController

// ---------- 공통 ----------

function emptyProfile() {
  return Object.fromEntries(PROFILE_FIELDS.map((k) => [k, ""]));
}

function now() {
  return new Date().toISOString();
}

function clock() {
  return new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

let toastTimer = null;
function toast(message, { error = false } = {}) {
  clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.className = error ? "toast error" : "toast";
  els.toast.hidden = false;
  if (!error) toastTimer = setTimeout(() => (els.toast.hidden = true), 3000);
}
els.toast.addEventListener("click", () => (els.toast.hidden = true));

function record(kind, text, turn = null) {
  startedAt ??= now();
  entries.push({ kind, turn, text, at: now() });
  unsaved = true;
}

function render() {
  const advising = adviceRequests.size > 0;
  let label = "대기";
  let cls = "";
  if (audioState === "recording") [label, cls] = ["녹음 중", "recording"];
  else if (audioState === "finalizing") [label, cls] = ["인식 마무리 중…", "busy"];
  else if (advising) [label, cls] = ["AI 의견 받는 중…", "busy"];
  else if (turnCount > 0) [label, cls] = ["준비됨", "ready"];
  els.status.textContent = label;
  els.dot.className = `dot ${cls}`;

  const recording = audioState === "recording";
  els.record.classList.toggle("stop", recording);
  els.recordLabel.textContent = recording
    ? "중단"
    : audioState === "finalizing"
      ? "마무리 중"
      : turnCount > 0
        ? "이어서 녹음"
        : "녹음";
  els.record.disabled = audioState === "finalizing";
  els.newSession.disabled = audioState !== "idle";
}

// ---------- 대화 (카톡형) ----------

function nearBottom() {
  const c = els.chat;
  return c.scrollHeight - c.scrollTop - c.clientHeight < STICK_THRESHOLD_PX;
}

// 사용자가 위로 스크롤해 읽고 있으면 끌어내리지 않고 [새 내용 ↓]만 띄운다
function updateChat(mutate) {
  const stick = nearBottom();
  mutate();
  if (stick) els.chat.scrollTop = els.chat.scrollHeight;
  else els.jump.hidden = false;
}

els.chat.addEventListener("scroll", () => {
  if (nearBottom()) els.jump.hidden = true;
});
els.jump.addEventListener("click", () => {
  els.chat.scrollTo({ top: els.chat.scrollHeight, behavior: "smooth" });
});

function appendToChat(node) {
  updateChat(() => {
    els.chat.querySelector(".chat-empty")?.remove();
    els.chat.append(node);
  });
}

function addMessage(kind, meta) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${kind}`;
  const metaEl = document.createElement("div");
  metaEl.className = "meta";
  metaEl.textContent = meta;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrap.append(metaEl, bubble);
  appendToChat(wrap);
  return bubble;
}

function addNote(text) {
  const note = document.createElement("div");
  note.className = "note";
  note.textContent = text;
  appendToChat(note);
}

function resetChat() {
  els.chat.innerHTML = EMPTY_CHAT_HTML;
  els.jump.hidden = true;
}

// ---------- 통화 인식 말풍선 ----------

function openTurn(turnId) {
  turnCount += 1;
  const body = addMessage("call", `통화 · 녹음 ${turnCount} · ${clock()}`);
  currentTurn = { id: turnId, number: turnCount, finals: [], body, partialEl: null };
}

function setPartial(text) {
  const turn = currentTurn;
  if (!turn) return;
  updateChat(() => {
    if (!text) {
      turn.partialEl?.remove();
      turn.partialEl = null;
      return;
    }
    if (!turn.partialEl) {
      turn.partialEl = document.createElement("span");
      turn.partialEl.className = "partial";
      turn.body.append(turn.partialEl);
    }
    turn.partialEl.textContent = (turn.finals.length ? "\n" : "") + text;
  });
}

function appendFinal(text) {
  const turn = currentTurn;
  if (!turn) return;
  updateChat(() => {
    const span = document.createElement("span");
    span.textContent = (turn.finals.length ? "\n" : "") + text;
    turn.finals.push(text);
    if (turn.partialEl) {
      turn.body.insertBefore(span, turn.partialEl);
      turn.partialEl.textContent = turn.partialEl.textContent.replace(/^\n?/, "\n");
    } else {
      turn.body.append(span);
    }
  });
}

// 구간을 닫는다. 확정되지 못한 partial은 지우지 않고 '미확정'으로 남긴다
function closeTurn() {
  const turn = currentTurn;
  if (!turn) return null;
  if (turn.partialEl) {
    turn.partialEl.className = "unconfirmed";
    turn.partialEl = null;
  }
  if (!turn.body.textContent.trim()) {
    turn.body.innerHTML = '<span class="none">(인식된 내용 없음)</span>';
  }
  if (turn.finals.length) record("transcript", turn.finals.join("\n"), turn.number);
  currentTurn = null;
  return turn;
}

// ---------- AI 의견 (SSE) ----------

function parseSseEvent(raw) {
  let event = "message";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  return { event, data: data ? JSON.parse(data) : {} };
}

// EventSource는 끊기면 자동 재연결해 LLM을 중복 호출하므로 fetch로 읽는다 (CLAUDE.md 7장)
async function requestAdvice(turn) {
  const bubble = addMessage("ai", `AI 의견 · 녹음 ${turn.number}`);
  bubble.classList.add("streaming");
  const controller = new AbortController();
  adviceRequests.add(controller);
  render();
  let text = "";
  try {
    const res = await fetch(`/api/turns/${turn.id}/advise`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile: appliedProfile }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `요청 실패 (${res.status})`);
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buf = "";
    let finished = false;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += value;
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const { event, data } = parseSseEvent(buf.slice(0, idx));
        buf = buf.slice(idx + 2);
        if (event === "token") {
          text += data.text;
          updateChat(() => (bubble.textContent = text));
        } else if (event === "done") {
          finished = true;
        } else if (event === "error") {
          throw new Error(data.message);
        }
      }
    }
    if (!finished) throw new Error("답변이 중간에 끊겼습니다");
    record("advice", text, turn.number);
  } catch (e) {
    if (e.name === "AbortError") return; // [신규상담]으로 취소됨
    bubble.classList.add("failed");
    bubble.textContent = `${text ? `${text}\n` : ""}⚠ ${e.message}`;
  } finally {
    bubble.classList.remove("streaming");
    adviceRequests.delete(controller);
    render();
  }
}

// ---------- 상담자 정보 ----------

function readForm() {
  const data = new FormData(els.form);
  return Object.fromEntries(PROFILE_FIELDS.map((k) => [k, String(data.get(k) ?? "").trim()]));
}

function sameProfile(a, b) {
  return PROFILE_FIELDS.every((k) => a[k] === b[k]);
}

function describeProfile(p) {
  const parts = PROFILE_FIELDS.filter((k) => p[k]).map((k) => `${PROFILE_LABELS[k]} ${p[k]}`);
  return parts.length ? parts.join(" · ") : "(비어 있음)";
}

function updateProfileState() {
  const current = readForm();
  const empty = PROFILE_FIELDS.every((k) => !current[k]) && PROFILE_FIELDS.every((k) => !appliedProfile[k]);
  if (empty) {
    els.profileState.textContent = "";
    els.profileState.className = "profile-state";
  } else if (sameProfile(current, appliedProfile)) {
    els.profileState.textContent = "✓ 적용됨";
    els.profileState.className = "profile-state applied";
  } else {
    els.profileState.textContent = "변경됨 · 적용 필요";
    els.profileState.className = "profile-state dirty";
  }
}

els.form.addEventListener("input", updateProfileState);
els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const next = readForm();
  if (sameProfile(next, appliedProfile)) return;
  appliedProfile = next;
  const summary = describeProfile(appliedProfile);
  addNote(`상담자 정보 적용 — ${summary}`);
  record("note", `상담자 정보 적용: ${summary}`);
  updateProfileState();
});

// ---------- 신규상담 / 저장 ----------

els.newSession.addEventListener("click", () => {
  if (unsaved && !confirm("저장하지 않은 내용이 있습니다. 새 상담을 시작할까요?")) return;
  adviceRequests.forEach((c) => c.abort());
  adviceRequests.clear();
  els.form.reset();
  appliedProfile = emptyProfile();
  entries = [];
  unsaved = false;
  savedId = null;
  startedAt = null;
  turnCount = 0;
  currentTurn = null;
  resetChat();
  updateProfileState();
  render();
});

els.save.addEventListener("click", async () => {
  if (!entries.length && PROFILE_FIELDS.every((k) => !readForm()[k])) {
    toast("저장할 내용이 없습니다");
    return;
  }
  els.save.disabled = true;
  els.save.textContent = "정리 중…";
  const hasConversation = entries.some((e) => e.kind !== "note");
  if (hasConversation) toast("대화를 정리해서 저장하고 있습니다…");
  try {
    const res = await fetch("/api/sessions/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: savedId, started_at: startedAt, profile: readForm(), entries }),
    });
    if (!res.ok) throw new Error(`저장 실패 (${res.status})`);
    const result = await res.json();
    savedId = result.id;
    unsaved = false;
    if (result.summary) {
      const bubble = addMessage("summary", `세션 정리 · ${clock()} 저장`);
      bubble.textContent = result.summary;
    }
    if (result.summary_error) {
      toast(`저장했지만 정리는 만들지 못했습니다 — ${result.summary_error}`, { error: true });
    } else {
      toast("저장했습니다");
    }
  } catch (e) {
    toast(e.message, { error: true });
  } finally {
    els.save.disabled = false;
    els.save.textContent = "저장";
  }
});

// ---------- 레벨 미터 ----------

function updateMeter(rms) {
  const db = rms > 0 ? 20 * Math.log10(rms) : -Infinity;
  const pct = Number.isFinite(db) ? Math.max(0, Math.min(100, ((db + 60) / 60) * 100)) : 0;
  els.meterFill.style.width = `${pct}%`;
  els.meterFill.classList.toggle("low", db < -45);
  els.meterFill.classList.toggle("clip", db > -3);
  els.meterDb.textContent = Number.isFinite(db) ? `${db.toFixed(0)} dB` : "-∞ dB";
}

// ---------- 오디오 ----------

async function loadConfig() {
  if (config) return config;
  const res = await fetch("/api/client-config");
  if (!res.ok) throw new Error("설정을 불러오지 못했습니다");
  config = await res.json();
  return config;
}

async function ensureAudio() {
  if (audio) return audio;
  const cfg = await loadConfig();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: cfg.mic.echo_cancellation,
      noiseSuppression: cfg.mic.noise_suppression,
      autoGainControl: cfg.mic.auto_gain_control,
    },
  });
  let ctx;
  try {
    ctx = new AudioContext({ sampleRate: cfg.sample_rate }); // 브라우저 리샘플 우선
  } catch {
    ctx = new AudioContext();
  }
  await ctx.audioWorklet.addModule("audio/pcm-worklet.js");
  const node = new AudioWorkletNode(ctx, "pcm-capture", {
    processorOptions: {
      targetRate: cfg.sample_rate,
      chunkSamples: Math.round((cfg.sample_rate * cfg.chunk_ms) / 1000),
    },
  });
  node.port.onmessage = (e) => onAudioChunk(e.data);
  const mute = ctx.createGain();
  mute.gain.value = 0; // 그래프가 돌도록 destination에 잇되 소리는 내지 않는다
  ctx.createMediaStreamSource(stream).connect(node).connect(mute).connect(ctx.destination);
  await ctx.resume();
  audio = { ctx, stream, node };
  return audio;
}

// 마이크를 완전히 놓는다 — 탭의 녹음 표시가 꺼지고, 다음 녹음 때 다시 연다
function releaseAudio() {
  if (!audio) return;
  audio.node.port.onmessage = null;
  audio.stream.getTracks().forEach((t) => t.stop());
  audio.ctx.close();
  audio = null;
  updateMeter(0);
}

function onAudioChunk({ pcm, rms, flushed }) {
  updateMeter(rms);
  const sending = audioState === "recording" || (audioState === "finalizing" && flushed);
  if (sending && ws?.readyState === WebSocket.OPEN && pcm.byteLength > 0) ws.send(pcm);
  if (flushed && audioState === "finalizing") {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop" }));
    releaseAudio();
  }
}

function audioFail(message) {
  clearTimeout(finalizeTimer);
  // 서버 쪽 녹음 구간을 닫아야 다음 [녹음]이 거절되지 않는다
  if (audioState === "recording" && ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "stop" }));
  }
  releaseAudio();
  closeTurn();
  audioState = "idle";
  toast(message, { error: true });
  render();
}

// ---------- WebSocket ----------

function ensureSocket() {
  if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve(ws);
  return new Promise((resolve, reject) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/ws/audio`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      ws = socket;
      resolve(socket);
    };
    socket.onerror = () => reject(new Error("서버에 연결하지 못했습니다"));
    socket.onmessage = (e) => onServerMessage(JSON.parse(e.data));
    socket.onclose = () => {
      if (ws === socket) ws = null;
      if (audioState !== "idle") audioFail("서버 연결이 끊겼습니다");
    };
  });
}

function onServerMessage(msg) {
  switch (msg.type) {
    case "started":
      openTurn(msg.turn_id);
      break;
    case "partial":
      setPartial(msg.text);
      break;
    case "final":
      appendFinal(msg.text);
      break;
    case "stopped": {
      clearTimeout(finalizeTimer);
      const wasActive = audioState !== "idle";
      const turn = currentTurn?.id === msg.turn_id ? closeTurn() : null;
      audioState = "idle";
      render();
      if (wasActive && turn && turn.finals.length && config.auto_advise) requestAdvice(turn);
      break;
    }
    case "error":
      audioFail(msg.message);
      break;
  }
}

// ---------- 녹음 / 중단 ----------

async function startRecording() {
  els.toast.hidden = true;
  els.record.disabled = true;
  try {
    await ensureAudio();
    await ensureSocket();
  } catch (e) {
    releaseAudio();
    toast(e.name === "NotAllowedError" ? "마이크 권한이 필요합니다" : e.message, { error: true });
    render();
    return;
  }
  ws.send(JSON.stringify({ type: "start" }));
  audioState = "recording";
  render();
}

function stopRecording() {
  audioState = "finalizing";
  render();
  // 남은 오디오를 보낸 뒤 stop을 보내고 마이크를 놓는다 (onAudioChunk)
  audio.node.port.postMessage("flush");
  finalizeTimer = setTimeout(() => audioFail("인식 결과를 받지 못했습니다"), FINALIZE_TIMEOUT_MS);
}

els.record.addEventListener("click", () => {
  if (audioState === "recording") stopRecording();
  else if (audioState === "idle") startRecording();
});

window.addEventListener("beforeunload", (e) => {
  if (unsaved) e.preventDefault();
});

resetChat();
updateProfileState();
render();
