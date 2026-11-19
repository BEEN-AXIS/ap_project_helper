/**
 * WebAudio synthesiser: oscillators, noise buffers, filters and envelopes. No
 * audio files. A master gain feeds a compressor used as a limiter; three buses
 * (master, effects, music); unlocked on the first user gesture; 8 voices per
 * bus; a sound that repeats within 40 ms of itself is ignored.
 */
import { useSettings } from "../state/settings";

type Bus = "effects" | "music";

class Synth {
  ctx: AudioContext | null = null;
  private master!: GainNode;
  private buses!: Record<Bus, GainNode>;
  private voices: Record<Bus, number> = { effects: 0, music: 0 };
  private lastPlayed = new Map<string, number>();
  private noiseBuf: AudioBuffer | null = null;
  onPlay: ((name: string) => void) | null = null;

  unlock(): void {
    if (this.ctx) {
      void this.ctx.resume();
      return;
    }
    const AC = window.AudioContext || (window as any).webkitAudioContext;
    if (!AC) return;
    this.ctx = new AC();
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -6;
    comp.ratio.value = 20;
    comp.attack.value = 0.002;
    this.master = this.ctx.createGain();
    this.master.connect(comp).connect(this.ctx.destination);
    this.buses = { effects: this.ctx.createGain(), music: this.ctx.createGain() };
    this.buses.effects.connect(this.master);
    this.buses.music.connect(this.master);
    this.applyVolumes();
    const len = this.ctx.sampleRate;
    this.noiseBuf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this.noiseBuf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  }

  applyVolumes(): void {
    if (!this.ctx) return;
    const s = useSettings.getState().s;
    this.master.gain.value = s.muted ? 0 : s.master;
    this.buses.effects.gain.value = s.effects;
    this.buses.music.gain.value = s.music ? 0.5 : 0;
  }

  /** Returns false when the sound is skipped (no context, voice cap, 40 ms repeat). */
  begin(name: string, bus: Bus = "effects"): boolean {
    this.onPlay?.(name);
    if (!this.ctx || this.ctx.state !== "running") return false;
    const now = performance.now();
    if (now - (this.lastPlayed.get(name) ?? -1e9) < 40) return false;
    if (this.voices[bus] >= 8) return false;
    this.lastPlayed.set(name, now);
    return true;
  }

  private track(bus: Bus, node: AudioScheduledSourceNode): void {
    this.voices[bus]++;
    node.onended = () => (this.voices[bus] = Math.max(0, this.voices[bus] - 1));
  }

  tone(opts: { type?: OscillatorType; f0: number; f1?: number; dur: number; gain?: number; delay?: number; bus?: Bus; attack?: number }): void {
    if (!this.ctx) return;
    const c = this.ctx;
    const t = c.currentTime + (opts.delay ?? 0);
    const o = c.createOscillator();
    const g = c.createGain();
    o.type = opts.type ?? "sine";
    o.frequency.setValueAtTime(opts.f0, t);
    if (opts.f1) o.frequency.exponentialRampToValueAtTime(Math.max(1, opts.f1), t + opts.dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(opts.gain ?? 0.3, t + (opts.attack ?? 0.008));
    g.gain.exponentialRampToValueAtTime(0.0001, t + opts.dur);
    o.connect(g).connect(this.buses[opts.bus ?? "effects"]);
    o.start(t);
    o.stop(t + opts.dur + 0.05);
    this.track(opts.bus ?? "effects", o);
  }

  noise(opts: { dur: number; gain?: number; type?: BiquadFilterType; f0?: number; f1?: number; q?: number; delay?: number; bus?: Bus }): void {
    if (!this.ctx || !this.noiseBuf) return;
    const c = this.ctx;
    const t = c.currentTime + (opts.delay ?? 0);
    const src = c.createBufferSource();
    src.buffer = this.noiseBuf;
    const f = c.createBiquadFilter();
    f.type = opts.type ?? "lowpass";
    f.frequency.setValueAtTime(opts.f0 ?? 2000, t);
    if (opts.f1) f.frequency.exponentialRampToValueAtTime(Math.max(20, opts.f1), t + opts.dur);
    f.Q.value = opts.q ?? 0.8;
    const g = c.createGain();
    g.gain.setValueAtTime(opts.gain ?? 0.3, t);
    g.gain.exponentialRampToValueAtTime(0.0001, t + opts.dur);
    src.connect(f).connect(g).connect(this.buses[opts.bus ?? "effects"]);
    src.start(t);
    src.stop(t + opts.dur + 0.05);
    this.track(opts.bus ?? "effects", src);
  }

  arpeggio(notes: number[], step: number, type: OscillatorType = "square", gain = 0.12): void {
    notes.forEach((f, i) => this.tone({ type, f0: f, dur: step * 1.4, gain, delay: i * step }));
  }
}

export const synth = new Synth();

if (typeof window !== "undefined") {
  const unlock = () => synth.unlock();
  window.addEventListener("pointerdown", unlock, { once: false, passive: true });
  window.addEventListener("keydown", unlock, { once: false });
  useSettings.subscribe(() => synth.applyVolumes());
}
