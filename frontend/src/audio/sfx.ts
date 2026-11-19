/** Named sound effects built from the synth. Every sound has a visual twin. */
import type { DamageClass } from "../vfx/timings";
import { synth } from "./synth";

const CLASS_IDX: Record<DamageClass, number> = { light: 0, heavy: 1, massive: 2, nuke: 3 };
const ELEMENT_PITCH: Record<string, number> = { fire: 1, bluefire: 1.35, ice: 1.8, lightning: 1.6, void: 0.6, bits: 2, gold: 1.5, glitch: 1.2, magma: 0.7, handheld: 1.4 };

export const sfx = {
  windup(ms: number, element = "fire") {
    if (!synth.begin("windup")) return;
    const p = ELEMENT_PITCH[element] ?? 1;
    synth.noise({ dur: ms / 1000, type: "bandpass", f0: 300 * p, f1: 1200 * p, q: 2, gain: 0.18 });
    synth.tone({ f0: 120 * p, f1: 240 * p, dur: ms / 1000, gain: 0.15 });
  },
  launch(ms: number) {
    if (!synth.begin("launch")) return;
    synth.noise({ dur: ms / 1000, type: "lowpass", f0: 4000, f1: 600, gain: 0.22 });
    synth.tone({ type: "triangle", f0: 520, f1: 260, dur: ms / 1000, gain: 0.08 });
  },
  impact(cls: DamageClass) {
    if (!synth.begin(`impact`)) return;
    const k = CLASS_IDX[cls];
    synth.tone({ f0: 60, f1: 30, dur: 0.15 + k * 0.15, gain: 0.5 });
    synth.noise({ dur: 0.12 + k * 0.26, type: "lowpass", f0: 1800, f1: 200, gain: 0.35 });
    for (let i = 0; i < 3 + k * 3; i++) synth.noise({ dur: 0.02, type: "highpass", f0: 3000, gain: 0.12, delay: Math.random() * 0.3 });
    if (cls === "nuke") {
      synth.tone({ f0: 45, f1: 20, dur: 1.2, gain: 0.5, delay: 0.05 });
      synth.noise({ dur: 1.4, type: "lowpass", f0: 900, f1: 80, gain: 0.15, delay: 0.1 });
    }
  },
  crit() {
    if (!synth.begin("crit")) return;
    synth.arpeggio([880, 1760], 0.07, "square", 0.12);
  },
  shieldUp() {
    if (!synth.begin("shield")) return;
    synth.tone({ type: "sawtooth", f0: 200, f1: 900, dur: 0.4, gain: 0.1 });
  },
  block() {
    if (!synth.begin("block")) return;
    for (const f of [523, 538, 1046]) synth.tone({ type: "triangle", f0: f, dur: 0.5, gain: 0.12 });
    synth.noise({ dur: 0.4, type: "highpass", f0: 2500, gain: 0.2, delay: 0.05 });
  },
  backfire() {
    if (!synth.begin("backfire")) return;
    synth.tone({ type: "sawtooth", f0: 400, f1: 60, dur: 0.45, gain: 0.2 });
    synth.noise({ dur: 0.15, type: "lowpass", f0: 1200, gain: 0.3, delay: 0.35 });
  },
  crackle() {
    if (!synth.begin("crackle")) return;
    for (let i = 0; i < 6; i++) synth.noise({ dur: 0.02, type: "highpass", f0: 4000, gain: 0.1, delay: i * 0.05 });
  },
  bell() {
    if (!synth.begin("bell")) return;
    for (const f of [880, 1320, 1760]) synth.tone({ f0: f, dur: 1.6, gain: 0.12 });
  },
  victory() {
    if (!synth.begin("victory")) return;
    synth.arpeggio([523, 659, 784, 1046, 784, 1046], 0.11);
  },
  defeat() {
    if (!synth.begin("defeat")) return;
    synth.arpeggio([392, 330, 262, 196], 0.16, "square", 0.1);
  },
  rankUp() {
    if (!synth.begin("rankup")) return;
    synth.arpeggio([523, 659, 784, 1046, 1318, 1568], 0.08);
  },
  click() {
    if (synth.begin("click")) synth.tone({ type: "square", f0: 1200, dur: 0.03, gain: 0.05 });
  },
  hover() {
    if (synth.begin("hover")) synth.tone({ type: "sine", f0: 1800, dur: 0.02, gain: 0.02 });
  },
  deal() {
    if (synth.begin("deal")) synth.noise({ dur: 0.06, type: "bandpass", f0: 2500, q: 3, gain: 0.08 });
  },
  testTick() {
    if (synth.begin("tick")) synth.tone({ type: "square", f0: 1500, dur: 0.025, gain: 0.04 });
  },
  testPass() {
    if (synth.begin("pass")) synth.arpeggio([988, 1318], 0.05, "square", 0.06);
  },
  testFail() {
    if (synth.begin("fail")) synth.tone({ type: "square", f0: 220, f1: 140, dur: 0.18, gain: 0.08 });
  },
  countdown() {
    if (synth.begin("countdown")) synth.tone({ type: "square", f0: 660, dur: 0.06, gain: 0.06 });
  },
  heartbeat() {
    if (!synth.begin("heartbeat")) return;
    synth.tone({ f0: 70, f1: 50, dur: 0.12, gain: 0.35 });
    synth.tone({ f0: 70, f1: 50, dur: 0.12, gain: 0.28, delay: 0.22 });
  },
};
