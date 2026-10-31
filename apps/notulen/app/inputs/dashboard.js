// ── State ────────────────────────────────────────────────────────────────────

let mediaRecorder = null;
let audioStream = null;
let analyserNode = null;
let animFrameId = null;
let recordingStartTime = null;
let timerInterval = null;
let pollingInterval = null;
let expandedJobId = null;
let expandedJobStatus = null;
let activeTab = 'notulen';
let wakeLock = null;
let watchdogInterval = null;
let recorderDead = false;
let uploadDead = false;   // server rejected the session mid-recording (410)
let micSilentSecs = 0;    // consecutive seconds of near-silent mic input
let micWarning = false;
let activeMicName = '';   // " via AirPods ...": which device iOS is recording from
let stopRequested = false; // distinguishes a user stop from a dying recorder

// Audio bitrate the recorder asks for. Speech at 32 kbps opus reads the same to
// whisper as the browser default of roughly 200 kbps, at about a quarter of the
// bytes: a three-hour meeting lands near 43 MB instead of 260 MB.
const SPEECH_BITS_PER_SECOND = 32000;

// Chunked-upload session state. session.id is the server-assigned job_id;
// session.nextSeq is the seq number we'll attach to the next chunk MediaRecorder
// emits. session.draining is the in-progress drain promise (serialises uploads).
let session = null;

// ── IndexedDB queue ──────────────────────────────────────────────────────────
//
// Chunks are written here *before* they're POSTed. Surviving an iOS tab
// eviction is the whole point: when the page is reopened, the recovery banner
// drains anything left behind.
//
// Two stores:
//   sessions: keyPath 'id': { id, title, meeting_date, attendees, agenda,
//                              mime_type, started_at }
//   chunks:   keyPath '[session_id, seq]': { session_id, seq, blob }

const IDB_NAME = 'notulen-uploads';
const IDB_VERSION = 1;
let _idbPromise = null;

function idb() {
  if (_idbPromise) return _idbPromise;
  _idbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, IDB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('sessions')) {
        db.createObjectStore('sessions', { keyPath: 'id' });
      }
      if (!db.objectStoreNames.contains('chunks')) {
        const cs = db.createObjectStore('chunks', { keyPath: ['session_id', 'seq'] });
        cs.createIndex('by_session', 'session_id');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror  = () => reject(req.error);
  });
  return _idbPromise;
}

async function idbTx(store, mode, fn) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(store, mode);
    const result = fn(tx.objectStore(store));
    tx.oncomplete = () => resolve(result);
    tx.onerror    = () => reject(tx.error);
    tx.onabort    = () => reject(tx.error);
  });
}

async function idbPutSession(s)        { return idbTx('sessions', 'readwrite', os => os.put(s)); }
async function idbDeleteSession(id)    { return idbTx('sessions', 'readwrite', os => os.delete(id)); }
async function idbAllSessions() {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('sessions', 'readonly');
    const req = tx.objectStore('sessions').getAll();
    req.onsuccess = () => resolve(req.result || []);
    req.onerror   = () => reject(req.error);
  });
}
async function idbPutChunk(sessionId, seq, blob) {
  return idbTx('chunks', 'readwrite', os => os.put({ session_id: sessionId, seq, blob }));
}
async function idbDeleteChunk(sessionId, seq) {
  return idbTx('chunks', 'readwrite', os => os.delete([sessionId, seq]));
}
async function idbChunksForSession(sessionId) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('chunks', 'readonly');
    const req = tx.objectStore('chunks').index('by_session').getAll(sessionId);
    req.onsuccess = () => resolve((req.result || []).sort((a, b) => a.seq - b.seq));
    req.onerror   = () => reject(req.error);
  });
}
async function idbDeleteAllChunks(sessionId) {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('chunks', 'readwrite');
    const store = tx.objectStore('chunks');
    const req = store.index('by_session').openKeyCursor(IDBKeyRange.only(sessionId));
    req.onsuccess = () => {
      const cur = req.result;
      if (cur) { store.delete(cur.primaryKey); cur.continue(); }
    };
    tx.oncomplete = () => resolve();
    tx.onerror    = () => reject(tx.error);
  });
}

// ── People ───────────────────────────────────────────────────────────────────
//
// The chips are the people the dashboard knows: the signed-in person (from the
// single sign-on headers) plus the NOTULEN_ATTENDEES list, both served by
// /api/people. Anyone else goes in the free-text field.

const selectedMembers = new Set();

async function initChips() {
  const container = document.getElementById('team-chips');
  let people = [];
  try {
    const resp = await fetch('/api/people');
    if (resp.ok) people = (await resp.json()).people || [];
  } catch (e) { /* no chips; the free-text field still works */ }
  container.innerHTML = '';
  for (const name of people) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = name;
    chip.onclick = () => toggleChip(chip, name);
    container.appendChild(chip);
  }
}

function toggleChip(el, name) {
  if (selectedMembers.has(name)) {
    selectedMembers.delete(name);
    el.classList.remove('selected');
  } else {
    selectedMembers.add(name);
    el.classList.add('selected');
  }
}

function getAttendees() {
  const extra = document.getElementById('attendees-extra').value.trim();
  const extraList = extra ? extra.split(',').map(s => s.trim()).filter(Boolean) : [];
  return [...selectedMembers, ...extraList].join(', ');
}

// ── Init ─────────────────────────────────────────────────────────────────────

document.getElementById('meeting-date').value = new Date().toISOString().slice(0, 10);
initChips();
loadJobs();
loadHealth();
setInterval(loadHealth, 120000);  // every 2 min

async function loadHealth() {
  try {
    const resp = await fetch('/api/health/notulen/full');
    const h = await resp.json();
    const el = document.getElementById('health-banner');
    if (h.status === 'ok') {
      el.classList.remove('visible', 'degraded', 'broken');
      return;
    }
    const failing = (h.checks || []).filter(c => !c.ok).map(c => c.name).join(', ');
    el.textContent = '';
    const strong = document.createElement('strong');
    strong.textContent = h.status === 'broken' ? '⚠️ Pipeline down' : '⚠️ Pipeline degraded';
    el.appendChild(strong);
    el.append(': ' + (failing || 'see logs'));
    el.classList.remove('degraded', 'broken');
    el.classList.add('visible', h.status === 'broken' ? 'broken' : 'degraded');
  } catch (e) { /* silent */ }
}

// ── Recording ────────────────────────────────────────────────────────────────

async function toggleRecording() {
  // Session-based, not recorder-based: while the self-heal path is
  // retrying, the recorder is dead but the session is live: the button
  // must stop+finalize, never start a second recording on top.
  if (session) {
    stopRecording();
  } else {
    await startRecording();
  }
}

async function startRecording() {
  const title = document.getElementById('title').value.trim();
  if (!title) {
    document.getElementById('title').focus();
    document.getElementById('title').style.borderColor = 'var(--red)';
    setTimeout(() => document.getElementById('title').style.borderColor = '', 1500);
    return;
  }

  // The minutes are filed under who was in the meeting, so an empty list
  // would land this recording under its title instead.
  if (!getAttendees()) {
    const extra = document.getElementById('attendees-extra');
    extra.focus();
    extra.style.borderColor = 'var(--red)';
    setTimeout(() => extra.style.borderColor = '', 1500);
    return;
  }

  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    document.getElementById('rec-status').textContent = 'Microphone not available';
    return;
  }

  const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus'
    : MediaRecorder.isTypeSupported('audio/mp4')
      ? 'audio/mp4'
      : '';

  // Open a recording session on the server. The job_id is what every chunk
  // POST hangs off; we persist it to IndexedDB so an evicted tab can resume.
  const startForm = new FormData();
  startForm.append('title', title);
  startForm.append('meeting_date', document.getElementById('meeting-date').value);
  startForm.append('attendees', getAttendees());
  startForm.append('agenda', document.getElementById('agenda').value.trim());

  let startResp;
  try {
    startResp = await fetch('/api/upload/start', { method: 'POST', body: startForm });
  } catch (err) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
    document.getElementById('rec-status').textContent = 'No connection to the server';
    return;
  }
  if (!startResp.ok) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
    let detail = 'The server refused the recording';
    try { detail = (await startResp.json()).detail || detail; } catch (e) {}
    document.getElementById('rec-status').textContent = detail;
    return;
  }
  const startData = await startResp.json();

  session = {
    id: startData.job_id,
    title,
    meeting_date: document.getElementById('meeting-date').value,
    attendees: getAttendees(),
    agenda: document.getElementById('agenda').value.trim(),
    mime_type: mimeType || 'application/octet-stream',
    started_at: Date.now(),
    nextSeq: 1,
    draining: null,
  };
  await idbPutSession({
    id: session.id,
    title: session.title,
    meeting_date: session.meeting_date,
    attendees: session.attendees,
    agenda: session.agenda,
    mime_type: session.mime_type,
    started_at: session.started_at,
  });

  attachRecorder(audioStream);
  recordingStartTime = Date.now();
  recorderDead = false;
  uploadDead = false;
  micSilentSecs = 0;
  micWarning = false;
  stopRequested = false;
  ensureAlarmAudio();  // create under this user gesture so later beeps work
  acquireWakeLock();
  startRecorderWatchdog();

  document.getElementById('rec-btn').classList.add('recording');
  // Name the active input device: iOS routes the mic to a connected
  // Bluetooth headset even with the phone on the table (a paired headset
  // in a pocket records near-silence).
  // Seeing "via AirPods" at a glance is the fix for the wrong-mic case.
  const micTrack = audioStream.getAudioTracks()[0];
  activeMicName = micTrack && micTrack.label ? ` via ${micTrack.label}` : '';
  document.getElementById('rec-status').textContent =
    `Recording${activeMicName} (keep the screen on, do not press the power button)`;
  document.getElementById('rec-status').classList.add('active');
  document.getElementById('timer').classList.add('visible');
  document.getElementById('waveform').classList.add('visible');

  startTimer();
}

// Recorder + waveform wiring for a mic stream. Called on start and again by
// the self-heal path when a replacement stream is acquired.
function attachRecorder(stream) {
  const mimeType = session && session.mime_type !== 'application/octet-stream'
    ? session.mime_type : '';
  const options = mimeType ? { mimeType } : {};
  // Speech, not music: the browser default is roughly 200 kbps, so an hour of
  // talking would be over 100 MB. Opus at 32 kbps
  // is the usual speech setting and is what whisper transcribes from. Browsers
  // that ignore the hint, or fall back to audio/mp4, still record.
  options.audioBitsPerSecond = SPEECH_BITS_PER_SECOND;
  mediaRecorder = new MediaRecorder(stream, options);

  mediaRecorder.ondataavailable = async (e) => {
    if (!session || !e.data || e.data.size === 0) return;
    const seq = session.nextSeq++;
    try {
      await idbPutChunk(session.id, seq, e.data);
    } catch (err) {
      console.warn('IndexedDB put failed', err);
    }
    drainChunks(session.id);
  };

  // A stop we did not ask for is a dying recorder (mic permission revoked,
  // OS suspension), not the end of the meeting: hand it to the self-heal
  // path instead of finalizing a truncated recording.
  mediaRecorder.onstop = () => {
    if (stopRequested) {
      finalizeAndResetUI();
    } else {
      handleRecorderDeath();
    }
  };
  mediaRecorder.onerror = (e) => {
    console.warn('MediaRecorder error', e.error || e);
    handleRecorderDeath();
  };

  // Waveform visualization
  const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(stream);
  analyserNode = audioCtx.createAnalyser();
  analyserNode.fftSize = 256;
  source.connect(analyserNode);
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  drawWaveform();

  // 5-second chunks keep request overhead low while limiting blast-radius
  // for any single failed POST. ~30KB opus per chunk at 64kbps.
  mediaRecorder.start(5000);
}

function startTimer() {
  if (timerInterval) cancelAnimationFrame(timerInterval);
  function timerTick() {
    if (!recordingStartTime) return;
    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
    const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
    const s = String(elapsed % 60).padStart(2, '0');
    document.getElementById('timer').textContent = `${m}:${s}`;
    timerInterval = requestAnimationFrame(timerTick);
  }
  timerInterval = requestAnimationFrame(timerTick);
}

function stopRecording() {
  stopRequested = true;
  stopFailureAlarm();
  stopRecorderRestartLoop();
  // Recorder may already be dead (OS suspended it). Skip .stop() in that case
  // and finalize whatever chunks reached the server.
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();  // fires onstop → finalizeAndResetUI
  } else if (session) {
    finalizeAndResetUI();
  }
  stopRecorderWatchdog();
  releaseWakeLock();
  if (audioStream) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
  if (timerInterval) {
    cancelAnimationFrame(timerInterval);
    timerInterval = null;
  }
  recordingStartTime = null;

  document.getElementById('rec-btn').classList.remove('recording');
  document.getElementById('rec-status').textContent = '';
  document.getElementById('rec-status').classList.remove('active');
  document.getElementById('rec-status').classList.remove('dead');
  document.getElementById('timer').classList.remove('visible');
  document.getElementById('waveform').classList.remove('visible');
}

// ── Wake lock + dead-recorder watchdog ───────────────────────────────────────
//
// Mobile browsers suspend MediaRecorder when the screen sleeps. Screen Wake
// Lock keeps the screen on so capture stays alive; the watchdog catches the
// case where it dies anyway (Wake Lock API absent, OS overrode it, mic track
// ended, etc.) so the UI doesn't show a ghost timer + dead stop button.

async function acquireWakeLock() {
  if (!('wakeLock' in navigator)) return;
  try {
    wakeLock = await navigator.wakeLock.request('screen');
    wakeLock.addEventListener('release', () => { wakeLock = null; });
  } catch (err) {
    console.warn('Wake lock request failed', err);
  }
}

function releaseWakeLock() {
  if (!wakeLock) return;
  try { wakeLock.release(); } catch (e) { /* best effort */ }
  wakeLock = null;
}

// Browsers auto-release wake locks when the tab goes hidden. Re-acquire when
// the user brings the tab back while a session is still active.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && session && !wakeLock) {
    acquireWakeLock();
  }
});

function startRecorderWatchdog() {
  stopRecorderWatchdog();
  watchdogInterval = setInterval(() => {
    if (!session || recorderDead) return;
    const stateOk = mediaRecorder && mediaRecorder.state === 'recording';
    const track = audioStream && audioStream.getAudioTracks()[0];
    const trackOk = track && track.readyState === 'live';
    if (!stateOk || !trackOk) {
      handleRecorderDeath();
      return;
    }
    checkMicLevel();
  }, 2000);
}

// A live mic whose input level has collapsed (an iOS audio-session
// interruption can leave it recording near-silence) looks identical to a
// working recording. Sample the analyser; sustained
// near-silence gets a visible warning instead of a lost recording. Five minutes, not 30 s: a
// quiet stretch on a working mic must not trip it.
const MIC_SILENT_DB = -55;
const MIC_WARN_AFTER_SECS = 300;

function checkMicLevel() {
  if (!analyserNode || typeof analyserNode.getFloatTimeDomainData !== 'function') return;
  const buf = new Float32Array(analyserNode.fftSize);
  analyserNode.getFloatTimeDomainData(buf);
  let sumSquares = 0;
  for (let i = 0; i < buf.length; i++) sumSquares += buf[i] * buf[i];
  const rms = Math.sqrt(sumSquares / buf.length);
  const db = 20 * Math.log10(rms || 1e-8);

  if (db < MIC_SILENT_DB) {
    micSilentSecs += 2;  // watchdog ticks every 2s
    if (micSilentSecs >= MIC_WARN_AFTER_SECS && !micWarning && !uploadDead) {
      micWarning = true;
      const live = document.getElementById('rec-status');
      live.classList.add('dead');
      live.textContent =
        `The microphone seems silent (almost no sound for ${micSilentSecs}s). ` +
        'Check the microphone or restart the recording.';
      startFailureAlarm();
    }
    return;
  }
  micSilentSecs = 0;
  if (micWarning) {
    micWarning = false;
    if (!uploadDead) stopFailureAlarm();
    const live = document.getElementById('rec-status');
    live.classList.remove('dead');
    live.textContent =
      `Recording${activeMicName} (keep the screen on, do not press the power button)`;
  }
}

function stopRecorderWatchdog() {
  if (watchdogInterval) {
    clearInterval(watchdogInterval);
    watchdogInterval = null;
  }
}

// Recorder died while we still thought we were recording. Alarm loudly,
// keep retrying the microphone, and offer a manual finalize against
// the chunks that did reach the server. The wake lock is kept: a lit
// screen is what lets the retry loop and a human intervene.
function handleRecorderDeath() {
  if (recorderDead || !session) return;
  recorderDead = true;
  stopRecorderWatchdog();

  if (timerInterval) {
    cancelAnimationFrame(timerInterval);
    timerInterval = null;
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }

  const status = document.getElementById('rec-status');
  status.classList.add('dead');
  status.innerHTML = '';
  const msg = document.createElement('span');
  msg.textContent =
    'Recording stopped (microphone lost). Trying to resume automatically... ';
  status.appendChild(msg);
  const finBtn = document.createElement('button');
  finBtn.textContent = 'Finish with what we have';
  finBtn.className = 'recovery-action';
  finBtn.onclick = () => finalizeAndResetUI();
  status.appendChild(finBtn);

  startFailureAlarm();
  startRecorderRestartLoop();
}

// ── Self-heal + failure alarm ─────────────────────────────────────────
//
// A dead mic no longer ends the recording quietly: the restart loop keeps
// re-asking for the microphone and resumes into the same session (the server
// stitches the extra container header at finalize), while the alarm makes
// the phone impossible to ignore: a mic permission revoked mid-meeting with
// only a banner to show for it goes unseen, and the minutes are lost.

let restartInterval = null;
let restartAttemptInFlight = false;

function startRecorderRestartLoop() {
  if (restartInterval) return;
  restartInterval = setInterval(attemptRecorderRestart, 3000);
  attemptRecorderRestart();
}

function stopRecorderRestartLoop() {
  if (restartInterval) {
    clearInterval(restartInterval);
    restartInterval = null;
  }
}

async function attemptRecorderRestart() {
  if (!session || !recorderDead || finalizing || restartAttemptInFlight) return;
  restartAttemptInFlight = true;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    restartAttemptInFlight = false;
    return; // mic still unavailable: keep alarming, retry next tick
  }
  restartAttemptInFlight = false;
  if (!session || !recorderDead || finalizing) {
    // Finalized or stopped while we waited for permission.
    stream.getTracks().forEach(t => t.stop());
    return;
  }
  if (audioStream) audioStream.getTracks().forEach(t => t.stop());
  audioStream = stream;
  attachRecorder(stream);
  recorderDead = false;
  micSilentSecs = 0;
  micWarning = false;
  stopRecorderRestartLoop();
  stopFailureAlarm();
  acquireWakeLock();
  startRecorderWatchdog();
  startTimer();
  const micTrack = stream.getAudioTracks()[0];
  activeMicName = micTrack && micTrack.label ? ` via ${micTrack.label}` : '';
  const status = document.getElementById('rec-status');
  status.classList.remove('dead');
  status.innerHTML = '';
  status.textContent =
    `Recording resumed${activeMicName} (keep the screen on, do not press the power button)`;
}

let alarmInterval = null;
let alarmAudioCtx = null;

// Created during startRecording (a user gesture), so later beeps are allowed
// even when the failure happens minutes into the meeting.
function ensureAlarmAudio() {
  if (alarmAudioCtx) return;
  try {
    alarmAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
  } catch (e) { /* no audio alarm; vibration still fires */ }
}

function soundFailureAlarm() {
  if (navigator.vibrate) {
    try { navigator.vibrate([300, 120, 300]); } catch (e) { /* best effort */ }
  }
  if (!alarmAudioCtx) return;
  try {
    if (alarmAudioCtx.state === 'suspended') alarmAudioCtx.resume();
    const base = alarmAudioCtx.currentTime;
    for (const offset of [0, 0.5]) {
      const osc = alarmAudioCtx.createOscillator();
      const gain = alarmAudioCtx.createGain();
      // A soft sine at a low gain: a square wave at 0.25 hurts in a headset.
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.05;
      osc.connect(gain);
      gain.connect(alarmAudioCtx.destination);
      osc.start(base + offset);
      osc.stop(base + offset + 0.35);
    }
  } catch (e) { /* alarm is best-effort */ }
}

function startFailureAlarm() {
  if (alarmInterval) return;
  soundFailureAlarm();
  alarmInterval = setInterval(soundFailureAlarm, 4000);
}

function stopFailureAlarm() {
  if (alarmInterval) {
    clearInterval(alarmInterval);
    alarmInterval = null;
  }
}

// Shared finalize+reset path. Called from mediaRecorder.onstop (normal stop)
// and from handleRecorderDeath → user clicks "Finish with what we have".
let finalizing = false;
async function finalizeAndResetUI() {
  if (!session || finalizing) return;
  finalizing = true;
  const sid = session.id;
  showProcessing('Uploading...');
  try {
    await drainChunks(sid);
    // drainChunks swallows network errors and stops on rejects; finalizing
    // anyway would silently truncate the recording AND delete the local
    // chunks below. Only the explicit "Finish with what we have" path
    // (recorderDead) may finalize partial.
    const remaining = await idbChunksForSession(sid);
    if (remaining.length && !recorderDead) {
      throw new Error(
        `${remaining.length} chunks not uploaded yet. Reload the page and use "Resume upload"`);
    }
    await finalizeSession(sid);
  } catch (err) {
    showProcessing('Upload failed: ' + (err.message || err), 5000);
    finalizing = false;
    return;
  }
  await idbDeleteAllChunks(sid);
  await idbDeleteSession(sid);
  session = null;
  finalizing = false;
  recorderDead = false;
  stopRecorderWatchdog();
  stopRecorderRestartLoop();
  stopFailureAlarm();
  releaseWakeLock();
  showProcessing('Processing... this can take a few minutes');
  startPolling(sid);
  document.getElementById('title').value = '';
  document.getElementById('attendees-extra').value = '';
  document.getElementById('agenda').value = '';
  document.getElementById('timer').textContent = '00:00';
  const status = document.getElementById('rec-status');
  status.classList.remove('dead', 'active');
  status.innerHTML = '';
  selectedMembers.clear();
  document.querySelectorAll('.chip.selected').forEach(c => c.classList.remove('selected'));
}

function drawWaveform() {
  const canvas = document.getElementById('waveform-canvas');
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.offsetWidth * 2;
  const h = canvas.height = canvas.offsetHeight * 2;

  function draw() {
    if (!analyserNode) return;
    animFrameId = requestAnimationFrame(draw);
    const data = new Uint8Array(analyserNode.frequencyBinCount);
    analyserNode.getByteFrequencyData(data);

    ctx.fillStyle = '#1e1e1e';
    ctx.fillRect(0, 0, w, h);

    const barW = (w / data.length) * 1.5;
    let x = 0;
    for (let i = 0; i < data.length; i++) {
      const barH = (data[i] / 255) * h;
      ctx.fillStyle = `hsl(210, 80%, ${40 + (data[i] / 255) * 30}%)`;
      ctx.fillRect(x, h - barH, barW - 1, barH);
      x += barW;
    }
  }
  draw();
}

// ── Upload ───────────────────────────────────────────────────────────────────

function showProcessing(message, autoHideMs) {
  const proc = document.getElementById('processing');
  const label = document.getElementById('processing-label');
  proc.classList.add('visible');
  label.textContent = message;
  if (autoHideMs) {
    setTimeout(() => proc.classList.remove('visible'), autoHideMs);
  }
}

// Serialise chunk uploads per session. Multiple ondataavailable events can
// arrive while a POST is still in flight; we want strict in-order delivery
// to avoid 409s on the server, so we chain on the last drain promise.
const _drainPromises = new Map();
function drainChunks(sessionId, onProgress) {
  const prev = _drainPromises.get(sessionId) || Promise.resolve();
  const next = prev.then(() => _drainChunksOnce(sessionId, onProgress)).catch((err) => {
    console.warn('drain error', err);
  });
  _drainPromises.set(sessionId, next);
  return next;
}

async function _drainChunksOnce(sessionId, onProgress) {
  while (true) {
    const pending = await idbChunksForSession(sessionId);
    if (!pending.length) return;
    if (onProgress) onProgress(pending.length);
    const head = pending[0];
    const form = new FormData();
    form.append('chunk', head.blob, `c${head.seq}.webm`);
    const url = `/api/upload/chunk?job=${encodeURIComponent(sessionId)}&seq=${head.seq}`;
    let resp;
    try {
      resp = await fetch(url, { method: 'POST', body: form });
    } catch (netErr) {
      // Network blip: leave chunk queued, retry next drain.
      throw netErr;
    }
    if (resp.status === 409 || resp.status === 410) {
      // Server says: out-of-order or session gone. Stop draining; recovery
      // banner on next load can attempt explicit recovery. A 410 during a
      // live recording means the server lost the session (e.g. mid-recording
      // redeploy): warn loudly instead of freezing the
      // "sent up to" text while retrying forever.
      const detail = await resp.text();
      console.warn('chunk rejected', resp.status, detail);
      if (resp.status === 410 && session && session.id === sessionId
          && mediaRecorder && mediaRecorder.state === 'recording') {
        uploadDead = true;
        const live = document.getElementById('rec-status');
        live.classList.add('dead');
        live.textContent =
          'The server refused the upload. The recording carries on and is kept ' +
          'on this phone. Stop as usual and then use "Resume upload".';
        startFailureAlarm();
      }
      return;
    }
    if (!resp.ok) {
      throw new Error(`Server ${resp.status} on chunk ${head.seq}`);
    }
    await idbDeleteChunk(sessionId, head.seq);
    if (session && session.id === sessionId && !uploadDead && !micWarning) {
      const live = document.getElementById('rec-status');
      if (live && mediaRecorder && mediaRecorder.state === 'recording') {
        // Display as mm:ss so the number maps to the recording timer instead
        // of an opaque seq counter (chunks are 5s each).
        const sentSec = head.seq * 5;
        const mm = String(Math.floor(sentSec / 60)).padStart(2, '0');
        const ss = String(sentSec % 60).padStart(2, '0');
        live.textContent =
          `Recording${activeMicName} (sent up to ${mm}:${ss}). Keep the screen on, do not press the power button`;
      }
    }
  }
}

async function finalizeSession(sessionId) {
  const url = `/api/upload/finalize?job=${encodeURIComponent(sessionId)}`;
  const resp = await fetch(url, { method: 'POST' });
  if (!resp.ok) {
    let detail = `Server ${resp.status}`;
    try { detail = (await resp.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return resp.json();
}

// pagehide / visibilitychange are the only events iOS reliably fires before
// suspending the tab. sendBeacon is fire-and-forget but survives suspension.
function flushPendingOnHide() {
  if (!session) return;
  // Pull the most recent chunk synchronously-ish from IndexedDB and beacon it.
  idbChunksForSession(session.id).then((pending) => {
    if (!pending.length) return;
    // Only the oldest pending chunk is the next in seq order; sendBeacon
    // posts to /chunk where it's idempotent on duplicates.
    const head = pending[0];
    const form = new FormData();
    form.append('chunk', head.blob, `c${head.seq}.webm`);
    const url = `/api/upload/chunk?job=${encodeURIComponent(session.id)}&seq=${head.seq}`;
    try { navigator.sendBeacon(url, form); } catch (e) { /* best effort */ }
  });
}
window.addEventListener('pagehide', flushPendingOnHide);
window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') flushPendingOnHide();
});

// ── Recovery ────────────────────────────────────────────────────────────────
//
// On page load, walk the sessions store. For each one:
//   - if the server says it's still recording → offer to resume + finalize
//   - if the server has moved on (pending/transcribing/complete/failed) →
//     drop the local copy silently
//   - if the server returns 404 → drop the local copy silently
// Anything older than 24h is dropped unconditionally (stale browser state).

const RECOVERY_MAX_AGE_MS = 24 * 60 * 60 * 1000;

async function scanForRecovery() {
  let sessions;
  try { sessions = await idbAllSessions(); } catch (e) { return; }
  if (!sessions.length) return;
  for (const s of sessions) {
    if (Date.now() - (s.started_at || 0) > RECOVERY_MAX_AGE_MS) {
      await idbDeleteAllChunks(s.id);
      await idbDeleteSession(s.id);
      continue;
    }
    let serverState;
    try {
      const resp = await fetch(`/api/upload/state?job=${encodeURIComponent(s.id)}`);
      if (resp.status === 404) {
        await idbDeleteAllChunks(s.id);
        await idbDeleteSession(s.id);
        continue;
      }
      if (!resp.ok) continue;
      serverState = await resp.json();
    } catch (e) {
      continue; // try again next page load
    }
    if (serverState.status !== 'recording') {
      // Server already moved past this session.
      await idbDeleteAllChunks(s.id);
      await idbDeleteSession(s.id);
      continue;
    }
    const pending = await idbChunksForSession(s.id);
    showRecoveryBanner(s, pending.length);
    return; // one at a time
  }
}

function showRecoveryBanner(s, pendingCount) {
  const banner = document.getElementById('recovery-banner');
  if (!banner) return;
  const when = new Date(s.started_at).toLocaleString(undefined, {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  });
  banner.innerHTML = '';
  const text = document.createElement('span');
  text.textContent = `Unfinished recording "${s.title}" from ${when}` +
    (pendingCount ? ` (${pendingCount} chunks on this device)` : '') + ': ';
  banner.appendChild(text);
  const resumeBtn = document.createElement('button');
  resumeBtn.textContent = 'Resume upload';
  resumeBtn.className = 'recovery-action';
  resumeBtn.onclick = () => resumeRecovery(s);
  banner.appendChild(resumeBtn);
  const dropBtn = document.createElement('button');
  dropBtn.textContent = 'Discard';
  dropBtn.className = 'recovery-action recovery-drop';
  dropBtn.onclick = () => dropRecovery(s);
  banner.appendChild(dropBtn);
  banner.classList.add('visible');
}

async function resumeRecovery(s) {
  const banner = document.getElementById('recovery-banner');
  // The drain can take minutes for a long recording; iOS pauses the page on
  // tab switch / screen lock, so keep the screen awake and say so.
  acquireWakeLock();
  const setProgress = (remaining) => {
    const sec = remaining * 5;  // chunks are 5s each
    const mm = String(Math.floor(sec / 60)).padStart(2, '0');
    const ss = String(sec % 60).padStart(2, '0');
    banner.textContent =
      `Resuming "${s.title}"... ${mm}:${ss} of audio left to upload. ` +
      'Keep this tab open and the screen on.';
  };
  try {
    const pending = await idbChunksForSession(s.id);
    setProgress(pending.length);
    await drainChunks(s.id, setProgress);
    const remaining = await idbChunksForSession(s.id);
    if (remaining.length) {
      throw new Error(
        `${remaining.length} chunks not uploaded yet. Please try again`);
    }
    banner.textContent = `Finishing "${s.title}"...`;
    await finalizeSession(s.id);
    await idbDeleteAllChunks(s.id);
    await idbDeleteSession(s.id);
    banner.classList.remove('visible');
    showProcessing('Processing... this can take a few minutes');
    startPolling(s.id);
    loadJobs();
  } catch (err) {
    banner.textContent = `Resume failed: ${err.message || err}`;
  } finally {
    releaseWakeLock();
  }
}

async function dropRecovery(s) {
  if (!confirm(`Discard the recording "${s.title}" for good?`)) return;
  try { await fetch(`/api/upload/abort?job=${encodeURIComponent(s.id)}`, { method: 'POST' }); }
  catch (e) {}
  await idbDeleteAllChunks(s.id);
  await idbDeleteSession(s.id);
  document.getElementById('recovery-banner').classList.remove('visible');
}

scanForRecovery();

// ── Polling ──────────────────────────────────────────────────────────────────

function startPolling(jobId) {
  if (pollingInterval) clearInterval(pollingInterval);

  pollingInterval = setInterval(async () => {
    try {
      const resp = await fetch(`/api/jobs/${jobId}`);
      const job = await resp.json();

      const label = document.getElementById('processing-label');
      if (job.status === 'transcribing') {
        label.textContent = 'Transcribing...';
      } else if (job.status === 'structuring') {
        label.textContent = 'Writing the minutes...';
      } else if (job.status === 'committing') {
        // Markdown is done; awaiting the git commit. Keep polling: the
        // git_writer_loop flips it to complete within ~30s.
        label.textContent = 'Committing to the repository...';
      } else if (job.status === 'complete') {
        label.textContent = 'Done!';
        clearInterval(pollingInterval);
        pollingInterval = null;
        setTimeout(() => {
          document.getElementById('processing').classList.remove('visible');
        }, 2000);
        loadJobs();
        expandedJobId = jobId;
      } else if (job.status === 'too_short') {
        label.textContent = 'Shorter than five minutes, so no minutes. The transcript is kept.';
        clearInterval(pollingInterval);
        pollingInterval = null;
        setTimeout(() => {
          document.getElementById('processing').classList.remove('visible');
        }, 6000);
        loadJobs();
      } else if (job.status === 'no_speech') {
        // Nobody spoke, which is a normal thing for a call to be. Say so; it
        // is not a fault and there is nothing to retry.
        label.textContent = 'Nobody can be heard in this recording, so there are no minutes.';
        clearInterval(pollingInterval);
        pollingInterval = null;
        setTimeout(() => {
          document.getElementById('processing').classList.remove('visible');
        }, 6000);
        loadJobs();
      } else if (job.status === 'failed') {
        label.textContent = 'Failed: ' + (job.error || 'unknown error');
        clearInterval(pollingInterval);
        pollingInterval = null;
        setTimeout(() => {
          document.getElementById('processing').classList.remove('visible');
        }, 5000);
        loadJobs();
      }
    } catch (err) {
      // Ignore polling errors
    }
  }, 3000);
}

// ── Jobs list ────────────────────────────────────────────────────────────────

async function loadJobs() {
  try {
    const resp = await fetch('/api/jobs');
    const data = await resp.json();
    renderJobs(data.jobs || []);
  } catch (err) {
    // Silent fail
  }
}

// Heuristic: a job whose audio is shorter than ~3 min while wall-clock from
// /start (created_at) to completion is >10 min likely got cut off by mobile
// standby. Tag complete jobs only; in-flight ones can still grow. False
// positives are fine: the hint is informational, not blocking.
function looksTruncated(job) {
  if (job.status !== 'complete') return false;
  if (!job.duration_secs || !job.created_at || !job.completed_at) return false;
  const wallClockSec = (new Date(job.completed_at) - new Date(job.created_at)) / 1000;
  if (wallClockSec < 600) return false;       // 10 min wall clock
  if (job.duration_secs > 180) return false;  // 3 min audio
  return true;
}

function renderJobs(jobs) {
  const container = document.getElementById('jobs-list');

  if (!jobs.length) {
    container.innerHTML = '<div class="empty">No recordings yet</div>';
    return;
  }

  container.innerHTML = jobs.map(job => {
    const dur = job.duration_secs
      ? `${Math.floor(job.duration_secs / 60)}m ${job.duration_secs % 60}s`
      : '';
    const att = (job.attendees || []).join(', ');
    const isExpanded = expandedJobId === job.id;
    const truncated = looksTruncated(job);

    return `
      <div class="job-card" onclick="toggleJob('${job.id}')">
        <div class="job-header">
          <span class="job-title">${esc(job.title)}</span>
          <span class="badge badge-${job.status}">${job.status === 'no_speech' ? 'no speech' : job.status === 'too_short' ? 'too short' : job.status}</span>
        </div>
        <div class="job-meta">
          ${job.meeting_date || ''}${dur ? ' · ' + dur : ''}${att ? ' · ' + att : ''}
        </div>
        ${truncated ? '<div class="truncation-hint">Possibly cut off by phone standby. Check that this is the whole meeting.</div>' : ''}
        ${job.error ? `<div class="error-msg">${esc(job.error)}</div>` : ''}
        ${job.status === 'failed' ? `<button class="recovery-action" style="margin-top:8px" onclick="event.stopPropagation(); retryJob('${job.id}')">Retry</button><button class="delete-btn" style="margin-top:8px" onclick="event.stopPropagation(); deleteJob('${job.id}')">Delete</button>` : ''}
        <div class="job-detail${isExpanded ? ' open' : ''}" id="detail-${job.id}">
          <div id="detail-content-${job.id}">
            ${isExpanded ? '' : '<div class="empty">Loading...</div>'}
          </div>
        </div>
      </div>
    `;
  }).join('');

  // Auto-load expanded job detail
  if (expandedJobId) {
    loadJobDetail(expandedJobId);
  }
}

async function toggleJob(jobId) {
  const detail = document.getElementById(`detail-${jobId}`);
  if (!detail) return;

  if (detail.classList.contains('open')) {
    detail.classList.remove('open');
    expandedJobId = null;
    expandedJobStatus = null;
    return;
  }

  // Close others
  document.querySelectorAll('.job-detail.open').forEach(el => el.classList.remove('open'));
  detail.classList.add('open');
  expandedJobId = jobId;
  expandedJobStatus = null;
  activeTab = 'notulen';  // reset to default on fresh open

  await loadJobDetail(jobId);
}

async function loadJobDetail(jobId) {
  const container = document.getElementById(`detail-content-${jobId}`);
  if (!container) return;

  try {
    const resp = await fetch(`/api/jobs/${jobId}`);
    const job = await resp.json();
    expandedJobStatus = job.status;

    // `committing` already has the full notulen + transcript (only the git
    // sync is pending), so show it like `complete`.
    if (job.status !== 'complete' && job.status !== 'committing') {
      container.innerHTML = `<div class="empty">${
        job.status === 'failed' ? 'Processing failed'
          : job.status === 'no_speech' ? 'Nobody can be heard in this recording, so there are no minutes.'
          : job.status === 'too_short' ? 'Shorter than five minutes, so no minutes. The transcript is kept.'
          : 'Not ready yet...'
      }</div>`;
      return;
    }

    // The committed file is the true version once anyone has corrected it;
    // `job.notulen` is the machine's first draft and never changes. Show the
    // file wherever the dashboard knows where it put it.
    let minutes = job.notulen || '';
    if (job.editable) {
      const loaded = await loadMinutes(jobId);
      if (loaded) minutes = loaded.markdown;
    }

    const isTranscript = activeTab === 'transcript';
    container.innerHTML = `
      <div class="tab-bar">
        <button class="tab${isTranscript ? '' : ' active'}" onclick="event.stopPropagation(); switchTab('${jobId}', 'notulen', this)">Minutes</button>
        <button class="tab${isTranscript ? ' active' : ''}" onclick="event.stopPropagation(); switchTab('${jobId}', 'transcript', this)">Transcript</button>
      </div>
      <div class="tab-content${isTranscript ? '' : ' active'}" id="tab-notulen-${jobId}" onclick="event.stopPropagation()">${esc(minutes)}</div>
      <div class="tab-content${isTranscript ? ' active' : ''}" id="tab-transcript-${jobId}" onclick="event.stopPropagation()">${esc(job.transcript || '')}</div>
      <div class="minutes-actions" id="actions-${jobId}">${minutesActions(jobId, job)}</div>
      <div class="minutes-note" id="note-${jobId}"></div>
      <a class="download-btn" href="/api/jobs/${jobId}/download" download onclick="event.stopPropagation()">Download .md</a>
      <button class="delete-btn" onclick="event.stopPropagation(); deleteJob('${jobId}')">Delete</button>
    `;
  } catch (err) {
    container.innerHTML = '<div class="empty">Could not load the details</div>';
  }
}

// ── Correcting the minutes, and handing them to the assistant ─────────────
// The machine gets things wrong and the team fixes them here. Saving writes
// the committed file, which is then the true version; the send button hands
// that corrected version to the assistant, once.

// The blob sha of the file each open editor was given, so a save can prove
// which version it is replacing and two people cannot silently overwrite
// each other.
const minutesShas = {};
let editingJobId = null;

async function loadMinutes(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/minutes`);
    if (!resp.ok) return null;
    const data = await resp.json();
    minutesShas[jobId] = data.sha;
    return data;
  } catch (err) {
    return null;
  }
}

function minutesActions(jobId, job) {
  if (!job.editable) {
    return '<span class="minutes-hint">The dashboard does not know where these minutes were committed; edit them in the repository.</span>';
  }
  if (editingJobId === jobId) {
    return `
      <button class="save-btn" onclick="event.stopPropagation(); saveMinutes('${jobId}')">Save</button>
      <button class="cancel-btn" onclick="event.stopPropagation(); cancelEdit('${jobId}')">Cancel</button>
    `;
  }
  const sent = job.sent_to_assistant;
  const opened = (job.board_issues || []).map(n => '#' + n).join(', ');
  return `
    <button class="edit-btn" onclick="event.stopPropagation(); startEdit('${jobId}')">Edit</button>
    <button class="assistant-btn" ${sent ? 'disabled' : ''} onclick="event.stopPropagation(); sendToAssistant('${jobId}')">
      ${sent ? (opened ? `Sent to the assistant: ${opened}` : 'Already sent to the assistant') : 'Send to the assistant'}
    </button>
  `;
}

function noteOn(jobId, message) {
  const note = document.getElementById(`note-${jobId}`);
  if (note) note.textContent = message;
}

function startEdit(jobId) {
  const pane = document.getElementById(`tab-notulen-${jobId}`);
  if (!pane) return;
  editingJobId = jobId;
  const current = pane.textContent;
  pane.innerHTML = '';
  const box = document.createElement('textarea');
  box.className = 'minutes-editor';
  box.id = `editor-${jobId}`;
  box.value = current;
  box.onclick = ev => ev.stopPropagation();
  pane.appendChild(box);
  document.getElementById(`actions-${jobId}`).innerHTML =
    minutesActions(jobId, { editable: true });
  noteOn(jobId, '');
}

async function cancelEdit(jobId) {
  editingJobId = null;
  await loadJobDetail(jobId);
}

async function saveMinutes(jobId) {
  const box = document.getElementById(`editor-${jobId}`);
  if (!box) return;
  const sha = minutesShas[jobId];
  if (!sha) {
    noteOn(jobId, 'Cannot save: unknown which version you are editing. Reload the page.');
    return;
  }
  noteOn(jobId, 'Saving...');
  try {
    const resp = await fetch(`/api/jobs/${jobId}/minutes`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown: box.value, sha }),
    });
    if (!resp.ok) {
      let detail = `Server ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (e) {}
      noteOn(jobId, 'Save failed: ' + detail);
      return;
    }
    editingJobId = null;
    await loadJobDetail(jobId);
    noteOn(jobId, 'Saved.');
  } catch (err) {
    noteOn(jobId, 'Save failed: ' + (err.message || err));
  }
}

async function sendToAssistant(jobId) {
  if (!confirm('The assistant reads these minutes and puts the work on the board right away. Continue?')) return;
  const button = document.querySelector(`#actions-${jobId} .assistant-btn`);
  if (button) button.disabled = true;   // no second press while this one runs
  noteOn(jobId, 'The assistant is reading the minutes; this takes a while.');
  try {
    const resp = await fetch(`/api/jobs/${jobId}/send-to-assistant`, { method: 'POST' });
    let payload = {};
    try { payload = await resp.json(); } catch (e) {}
    if (!resp.ok) {
      noteOn(jobId, 'Did not work: ' + (payload.detail || `Server ${resp.status}`));
      await loadJobDetail(jobId);
      return;
    }
    const opened = (payload.issues || []).map(n => '#' + n).join(', ');
    noteOn(jobId, opened ? `The assistant opened: ${opened}` : 'The assistant found nothing to put on the board.');
    await loadJobDetail(jobId);
  } catch (err) {
    noteOn(jobId, 'Did not work: ' + (err.message || err));
    await loadJobDetail(jobId);
  }
}

function switchTab(jobId, tab, btn) {
  activeTab = tab;  // remember across polling re-renders

  // Update tab buttons
  btn.parentElement.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  btn.classList.add('active');

  // Update content
  document.getElementById(`tab-notulen-${jobId}`).classList.toggle('active', tab === 'notulen');
  document.getElementById(`tab-transcript-${jobId}`).classList.toggle('active', tab === 'transcript');
}

// Re-run the pipeline for a failed job (audio already in S3).
async function retryJob(jobId) {
  try {
    const resp = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
    if (!resp.ok) {
      let detail = `Server ${resp.status}`;
      try { detail = (await resp.json()).detail || detail; } catch (e) {}
      showProcessing('Retry failed: ' + detail, 5000);
      return;
    }
    showProcessing('Processing... this can take a few minutes');
    startPolling(jobId);
    loadJobs();
  } catch (err) {
    showProcessing('Retry failed: ' + (err.message || err), 5000);
  }
}

async function deleteJob(jobId) {
  if (!confirm('Are you sure you want to delete this recording?')) return;
  try {
    const resp = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
    if (resp.ok) {
      expandedJobId = null;
      loadJobs();
    }
  } catch (err) {
    // Silent fail
  }
}

function esc(str) {
  const el = document.createElement('span');
  el.textContent = str;
  return el.innerHTML;
}

// Refresh jobs list periodically if any are in progress.
// Skip while the user is reading a completed job: the full re-render
// nukes scroll position in the transcript tab and makes it unreadable.
setInterval(() => {
  if (expandedJobId && expandedJobStatus === 'complete') return;
  const badges = document.querySelectorAll('.badge-pending, .badge-transcribing, .badge-structuring, .badge-committing');
  if (badges.length > 0) loadJobs();
}, 5000);
