# The PartSmith film

One film, under three minutes, rebuilt from code. Outputs go to `~/Videos/partsmith/` (not committed).

```sh
# start the app in replay mode: API on :8766, web on :3766 (the app the screen flows record)
python3 video/facts.py                            # every number, read from the repo
PY=~/.pyenv/versions/3.10.13/bin/python           # has chatterbox, faster-whisper, soundfile
$PY video/synth.py                                # narration takes, best take kept by Whisper match
for f in calibrate replay job lie knobs fit review registry; do node video/record.mjs $f; done
$PY video/build.py timeline                       # scene starts from the real voice lengths
$PY video/build.py stills
$PY video/build.py gfx                            # graphics.html and three.html scenes, recorded to exact length
python3 video/sfx.py                              # whoosh, click, riser, hit (synthesized with ffmpeg)
$PY video/build.py film                           # final/PartSmith-film.mp4, a phone copy, .srt and chapters
$PY video/build.py check                          # length, loudness, voice gaps, word match
$PY video/build.py storyboard                     # video/storyboard.md
```

- `narration.py`: every line as data (caption, spoken text, voice settings); `voice_of` picks the narrator.
- `story_images.py`: the story's paintings, drawn by Muse Image through the project's providers layer and labelled on screen.
- `record.mjs`: Chrome screencast of the real app. The app's own replay labels stay in frame.
- `graphics.html`, `three.html`: drawn scenes and the 3D "under the hood" stack.
- `music.py`: one piano theme composed in code.
- `FOUNDER_SCRIPT.md`: the founder's lines. A clip in `~/Videos/partsmith/founder/` replaces the narrator for that line.

The narrator references in `refs/` are kept out of git; put your own licensed references there to rebuild. The outside
numbers are sourced on screen and listed in `facts.py`.
