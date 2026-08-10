import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Telling you something happened while you were not looking.
 *
 * A run takes minutes and nobody watches it. Without this, "ask me about
 * everything" is unusable in practice: the crew stops at a gate and waits for
 * a person who has no idea they are being waited on.
 *
 * Three channels, deliberately in increasing order of intrusiveness — the tab
 * title always, a browser notification once permitted, a sound only if asked
 * for. None of them fires while the tab is focused: you are already looking.
 */

const SOUND_KEY = "adc-sound";
const BASE_TITLE = "Agent Dev Crew";

export type Urgency = "waiting" | "finished";

function playChime(urgency: Urgency): void {
  // Synthesised rather than shipped as a file: two sine tones need no asset,
  // no fetch, and no licence.
  try {
    const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
    if (!Ctor) return;
    const ctx = new Ctor();
    const now = ctx.currentTime;
    const notes = urgency === "waiting" ? [660, 880] : [880, 660];
    notes.forEach((frequency, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, now + i * 0.16);
      gain.gain.exponentialRampToValueAtTime(0.12, now + i * 0.16 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.16 + 0.15);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + i * 0.16);
      osc.stop(now + i * 0.16 + 0.16);
    });
    setTimeout(() => ctx.close(), 800);
  } catch {
    // Audio is a nicety; a browser that refuses it must not break the app.
  }
}

export interface Notifier {
  /** Unread things that happened while you were away. */
  pending: number;
  soundOn: boolean;
  setSoundOn: (on: boolean) => void;
  permission: NotificationPermission | "unsupported";
  requestPermission: () => void;
  notify: (urgency: Urgency, title: string, body: string) => void;
  clear: () => void;
}

export function useNotifier(): Notifier {
  const [pending, setPending] = useState(0);
  const [soundOn, setSound] = useState(() => localStorage.getItem(SOUND_KEY) === "1");
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(() =>
    typeof Notification === "undefined" ? "unsupported" : Notification.permission,
  );
  const focused = useRef(true);

  useEffect(() => {
    const onVisibility = () => {
      focused.current = document.visibilityState === "visible";
      if (focused.current) setPending(0);
    };
    document.addEventListener("visibilitychange", onVisibility);
    onVisibility();
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  // The tab title is the one channel that needs no permission and no sound,
  // so it is the one that always works.
  useEffect(() => {
    document.title = pending > 0 ? `(${pending}) ${BASE_TITLE}` : BASE_TITLE;
  }, [pending]);

  const setSoundOn = useCallback((on: boolean) => {
    localStorage.setItem(SOUND_KEY, on ? "1" : "0");
    setSound(on);
  }, []);

  const requestPermission = useCallback(() => {
    if (typeof Notification === "undefined") return;
    Notification.requestPermission().then(setPermission);
  }, []);

  // `notify` must keep the same identity for the life of the component. The
  // SSE subscription depends on it, and a callback that changed whenever
  // `soundOn` did — or whenever anything else here re-rendered — tore the
  // event stream down and reopened it on *every* event. Nothing broke, because
  // the stream backfills from its sequence number, which is exactly why it
  // went unnoticed: a reconnect per event, all of them invisible.
  const sound = useRef(soundOn);
  useEffect(() => {
    sound.current = soundOn;
  }, [soundOn]);

  const notify = useCallback((urgency: Urgency, title: string, body: string) => {
    if (focused.current) return;
    setPending((n) => n + 1);
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      try {
        // Tagged per urgency so a run that stops twice replaces its own
        // notification instead of stacking two of them.
        new Notification(title, { body, tag: `adc-${urgency}` });
      } catch {
        /* some browsers refuse outside a service worker; the badge remains */
      }
    }
    if (sound.current) playChime(urgency);
  }, []);

  const clear = useCallback(() => setPending(0), []);

  return { pending, soundOn, setSoundOn, permission, requestPermission, notify, clear };
}
