# Your lines for the film

The film is complete without these: a narrator reads each line until your clip exists. Recording them makes it better, and it takes about 10 minutes.

## How to record

- Phone in landscape, on a stand at eye level, 1080p 30 fps. Face a window or lamp, so the light is in front of you. Quiet room, fan off.
- Look at the lens, not the screen. Leave 2 seconds of silence before and after each line.
- Do each line twice, and keep the better take. One breath per line, in your normal voice. Don't rush.
- Send the files as files (USB, Drive, or Telegram as File), not as WhatsApp videos.

## The lines

Say them exactly, or change the words if yours sound more natural. Tell me if a fact is wrong.

| File name | Where it goes | Say this |
|---|---|---|
| `f1.mp4` | On camera, right after the title | "Hi, I'm Prashant, and I built this solo, during this hackathon, on Meta's models." |
| `f3.mp4` | In a bubble over the vision scene | "The goal: an open library of verified parts, so the next person with that remote just downloads the fix." |
| `f2.mp4` | In a bubble over the end card | "If you have a broken part at home, send it in. The most wanted parts get modelled first. And be part of PartSmith in its journey to become the next automated CAD software." |

## After recording

Put the files in `~/Videos/partsmith/founder/` and run:

```sh
python3 video/facts.py
~/.pyenv/versions/3.10.13/bin/python video/synth.py f1 f2 f3
~/.pyenv/versions/3.10.13/bin/python video/build.py timeline
~/.pyenv/versions/3.10.13/bin/python video/build.py gfx
~/.pyenv/versions/3.10.13/bin/python video/build.py film
```

The clip replaces the narrator for that line, and the film's timing recomputes from your real lengths.
