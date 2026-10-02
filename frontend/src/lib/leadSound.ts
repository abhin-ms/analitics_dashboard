/**
 * New-lead chime made with the Web Audio API (no audio file to load).
 * Browsers only allow sound after the user has interacted with the page,
 * so the audio context is unlocked on the first click / key press.
 */
const MUTE_KEY = "bp.leadSound.muted";
let ctx: AudioContext | null = null;
let lastPlayed = 0;

function context(): AudioContext | null {
  try {
    if (!ctx) {
      const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      ctx = new Ctor();
    }
    return ctx;
  } catch {
    return null;
  }
}

export function unlockAudioOnFirstGesture() {
  const unlock = () => {
    context()?.resume().catch(() => undefined);
    window.removeEventListener("pointerdown", unlock);
    window.removeEventListener("keydown", unlock);
  };
  window.addEventListener("pointerdown", unlock);
  window.addEventListener("keydown", unlock);
}

export function isSoundMuted(): boolean {
  try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; }
}

export function setSoundMuted(muted: boolean) {
  try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch { /* private mode */ }
}

/** Two rising notes; a hot lead gets a third, higher one. At most one
 *  chime every 2 seconds so a burst of leads doesn't become noise. */
export function playLeadChime(hot = false) {
  if (isSoundMuted()) return;
  const now = Date.now();
  if (now - lastPlayed < 2000) return;
  lastPlayed = now;
  const ac = context();
  if (!ac || ac.state !== "running") return;
  const notes = hot ? [660, 880, 1175] : [660, 880];
  notes.forEach((freq, i) => {
    const t = ac.currentTime + i * 0.16;
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
    osc.connect(gain).connect(ac.destination);
    osc.start(t);
    osc.stop(t + 0.4);
  });
}
