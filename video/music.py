"""The film's own piano theme, composed here and rendered from a General MIDI SoundFont: nothing licensed, nothing
a recording could match.

One instrument from start to end. Under the opening it is sparse and leans minor (Am F C G); from "This is
PartSmith" the same melody runs over warmer chords (C G Am F) with moving eighths; under the last scenes the eighths
become sixteenths and the melody doubles an octave up; it resolves on a long C under the end card. The timing follows
timeline.json, so the change of mood lands on the title.

    ~/Videos/debrief/.venv-music/bin/python video/music.py   ->  ~/Videos/partsmith/music/theme.wav
(that venv has tinysoundfont and numpy: python3 -m venv it, then pip install --no-deps tinysoundfont numpy)
"""

from __future__ import annotations

import json
import os
import wave

import numpy as np
import tinysoundfont

SR = 48000
BPM = 84
BEAT = 60 / BPM
BAR = 4 * BEAT
SF2 = os.environ.get("PS_SF2", os.path.expanduser("~/Videos/debrief/sf2-dl/YDP-GrandPiano-SF2-20160804/YDP-GrandPiano-20160804.sf2"))
HOME = os.path.expanduser("~/Videos/partsmith")
SFX = f"-{os.environ['PS_CUT']}" if os.environ.get("PS_CUT") else ""   # the short cut has its own timeline and theme

C, G, Am, F = (48, (60, 64, 67)), (43, (59, 62, 67)), (45, (57, 60, 64)), (41, (57, 60, 65))
NIGHT = [Am, F, C, G]
DAY = [C, G, Am, F]
PHRASE_A = [[(0, 76, 1.5), (1.5, 74, 0.5), (2, 72, 2)], [(0, 72, 1), (1, 71, 1), (2, 67, 2)], [(0, 69, 2), (2, 72, 2)], [(0, 71, 3), (3, 74, 1)]]
PHRASE_B = [[(0, 76, 1), (1, 79, 1), (2, 77, 2)], [(0, 76, 2), (2, 74, 2)], [(0, 72, 1.5), (1.5, 74, 0.5), (2, 76, 2)], [(0, 74, 4)]]


def events(total: float, turn: float, finale: float) -> list[tuple[float, int, float, int]]:
    """(start s, MIDI note, length s, velocity) for the whole piece."""
    out: list[tuple[float, int, float, int]] = []
    end_bar = int((total - 6) / BAR)
    turn_bar = max(1, round(turn / BAR))
    finale_bar = int(finale / BAR)
    for b in range(end_bar + 1):
        t0 = b * BAR
        day = b >= turn_bar
        last = b == end_bar
        bass, triad = (C if last else DAY[(b - turn_bar) % 4]) if day else NIGHT[b % 4]
        soft = 36 if not day else 46
        if last:  # resolve: a low C and a slow rolled chord, left to ring
            out.append((t0, bass - 12, BAR * 2.2, soft + 6))
            for i, n in enumerate((bass, *triad, triad[0] + 12)):
                out.append((t0 + i * 0.2, n, BAR * 2.2, soft + 4))
            break
        big = b >= finale_bar
        if day:  # moving eighths: root, fifth and the chord, up and back (sixteenths, for the finale)
            pattern = [bass, bass + 7, triad[0], triad[1], triad[2], triad[1], triad[0], bass + 7] * (2 if big else 1)
        else:  # the night: a slow broken chord, one note a beat
            pattern = [bass, triad[1], bass + 7, triad[2]]
        step = BAR / len(pattern)
        for i, n in enumerate(pattern):
            out.append((t0 + i * step, n, step * (1.6 if day else 2.4), soft + (14 if big else 0) + (6 if i % 8 == 0 else 0)))
        if b < 1:
            continue
        phrase = PHRASE_A if ((b - (turn_bar if day else 0)) // 4) % 2 == 0 else PHRASE_B
        if not day and (b // 4) % 2 == 1:
            out.append((t0, triad[2] + 12, BAR * 0.9, soft + 2))  # the night answers with one held note
            continue
        for off, n, beats in phrase[b % 4]:
            out.append((t0 + off * BEAT, n, beats * BEAT * 1.05, 70 if big else 56 if day else 44))
            if big:
                out.append((t0 + off * BEAT, n + 12, beats * BEAT * 1.05, 62))
    return out


def render(evts: list[tuple[float, int, float, int]], seconds: float) -> np.ndarray:
    sf = tinysoundfont._tinysoundfont.SoundFont(SF2)
    sf.set_output(tinysoundfont._tinysoundfont.OutputMode.StereoInterleaved, SR, -6.0)
    sf.channel_set_preset_number(0, 0, 0)  # acoustic grand
    sched = sorted([(s, 1, n, v) for s, n, _, v in evts] + [(s + d, 0, n, 0) for s, n, d, _ in evts])
    total = int(seconds * SR)
    out = np.zeros((total, 2), dtype=np.float32)
    pos, i = 0, 0
    while pos < total:
        nxt = min(max(int(sched[i][0] * SR) if i < len(sched) else total, pos), total)
        if nxt > pos:
            buf = np.zeros((nxt - pos) * 2, dtype=np.float32)
            sf.render(memoryview(buf).cast("B"))
            out[pos:nxt] = buf.reshape(-1, 2)
            pos = nxt
        while i < len(sched) and int(sched[i][0] * SR) <= pos:
            _, on, n, v = sched[i]
            if on:
                sf.channel_note_on(0, n, v / 127)
            else:
                sf.channel_note_off(0, n)
            i += 1
        if i >= len(sched) and pos < total:
            buf = np.zeros((total - pos) * 2, dtype=np.float32)
            sf.render(memoryview(buf).cast("B"))
            out[pos:] = buf.reshape(-1, 2)
            pos = total
    return out


def reverb(dry: np.ndarray, decay: float = 2.2, wet: float = 0.3) -> np.ndarray:
    """A soft hall: decorrelated decaying noise per channel, convolved by FFT."""
    rng = np.random.default_rng(7)
    n = int(decay * SR)
    env = np.exp(-6.9 * np.arange(n) / n)
    out = np.empty_like(dry)
    size = 1 << int(np.ceil(np.log2(len(dry) + n)))
    for ch in range(2):
        ir = rng.standard_normal(n) * env
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt((ir ** 2).sum())
        wet_ch = np.fft.irfft(np.fft.rfft(dry[:, ch], size) * np.fft.rfft(ir, size), size)[: len(dry)]
        out[:, ch] = (1 - wet) * dry[:, ch] + wet * wet_ch
    return out


def main() -> None:
    tl = json.load(open(f"{HOME}/build{SFX}/timeline.json"))
    total = tl["total"]
    turn = next(s["start"] for s in tl["scenes"] if s["name"] == "title")
    finale = next((s["start"] for s in tl["scenes"] if s["name"] == "vision"), total)
    evts = events(total, turn, finale)
    seconds = max(s + d for s, _, d, _ in evts) + 3
    audio = reverb(render(evts, seconds))
    audio *= 0.89 / max(1e-6, float(np.abs(audio).max()))
    os.makedirs(f"{HOME}/music", exist_ok=True)
    path = f"{HOME}/music/theme{SFX}.wav"
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    print(f"wrote {path}: {seconds:.1f} s, {len(evts)} notes, film {total:.1f} s, title at {turn:.1f} s")


if __name__ == "__main__":
    main()
