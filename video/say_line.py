"""The spoken edit fed to the fake microphone for the voice-edit take: a Hindi-English line in the narrator's voice.

    ~/.pyenv/versions/3.10.13/bin/python video/say_line.py  ->  ~/Videos/partsmith/voiceedit/say.wav (48 kHz mono)

The film labels it as a synthesised test line; the transcription and the knob change in that take are live.
"""

from __future__ import annotations

import os
import subprocess

import soundfile as sf
import torch
from chatterbox.tts import ChatterboxTTS

OUT = os.path.expanduser("~/Videos/partsmith/voiceedit")
LINE = "Cover ko ek millimeter lamba karo."


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    torch.manual_seed(11)
    wav = model.generate(LINE, audio_prompt_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs/male.wav"), exaggeration=0.6, cfg_weight=0.4, temperature=0.7)
    sf.write(f"{OUT}/raw.wav", wav.squeeze(0).numpy(), model.sr)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-t", "0.8", "-i", "anullsrc=r=48000:cl=mono", "-i", f"{OUT}/raw.wav", "-f", "lavfi", "-t", "2.5", "-i", "anullsrc=r=48000:cl=mono",
                    "-filter_complex", "[1:a]aresample=48000,aformat=channel_layouts=mono[a];[0:a][a][2:a]concat=n=3:v=0:a=1,alimiter=limit=0.8", "-ar", "48000", "-ac", "1", f"{OUT}/say.wav"], check=True)
    print("wrote", f"{OUT}/say.wav", sf.info(f"{OUT}/say.wav").duration)


if __name__ == "__main__":
    main()
