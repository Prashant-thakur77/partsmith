"""The film's lines, as data, with every number read from facts.json (video/facts.py).

Each line: (scene, id, caption, spoken, exaggeration, cfg_weight). The caption is what the screen shows; the spoken text
is what the voice reads (numbers in words, names spelled for the voice). `voice_of` picks the narrator. Ids starting with "f" are the founder's: when a
clip is in ~/Videos/partsmith/founder/<id>.* (see FOUNDER_SCRIPT.md) it replaces the narrator for that line.
"""

from __future__ import annotations

import json
import math
import os

WORK = os.path.expanduser("~/Videos/partsmith")
FACTS = f"{WORK}/build/facts.json"

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

STORY = (0.6, 0.35)
PRODUCT = (0.7, 0.4)
LIFT = (0.9, 0.32)
STORY_FAST = (0.7, 0.4)


def words(n: int) -> str:
    """A whole number from 0 to 9999 as the voice should say it."""
    if n >= 1000:
        rest = n % 1000
        return ONES[n // 1000] + " thousand" + ("" if rest == 0 else " " + words(rest))
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    rest = n % 100
    return ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + words(rest))


def decimal(x: float) -> str:
    """2.69 -> two point six nine; 0.51 -> zero point five one."""
    whole, frac = f"{x:.2f}".split(".")
    return f"{words(int(whole))} point " + " ".join(ONES[int(d)] for d in frac)


def decimal1(x: float) -> str:
    """7.5 -> seven point five."""
    whole, frac = f"{x:.1f}".split(".")
    return f"{words(int(whole))} point {ONES[int(frac)]}"


def half_mm(limit: float) -> str:
    if limit != 0.5:
        raise ValueError(f"the script says half a millimetre but the limit is {limit} mm")
    return "half a millimetre"


def tested(f: dict) -> tuple[str, str]:
    """The spoken test count, from the last `make proof` run; until one exists the line stays about the bench."""
    passed = f["tests"].get("backend", {}).get("passed")
    if passed:
        return f"And {passed:,} backend tests pass.", f"And {words(passed)} backend tests pass."
    return f"And {f['control'][0]} of {f['control'][1]} intact parts accepted.", f"And {words(f['control'][0])} of {words(f['control'][1])} intact parts accepted."


def voice_of(scene: str, lid: str) -> str:
    """Two narrators: the warm voice tells the story, the testing and the aim, the other walks through the product."""
    return "female" if scene in ("open", "title", "test", "market", "vision", "close") else "male"


def lines(f: dict) -> list[tuple[str, str, str, str, float, float]]:
    run, audit = f["run"], f["audit"]
    e0, e1, e2 = run["errors"]
    half = half_mm(f["limit_mm"])
    knob = f["knob_shift_mm"] if f["knob_shift_mm"] else "zero"
    minutes, rupees, cents = round(run["print_minutes"]), round(run["inr"]), round(run["usd"] * 100)
    out = [
        ("open", "n01", "It's nine at night. Your father reaches for the TV remote.", "It's nine at night. Your father reaches for the T V remote.", *STORY),
        ("open", "n02", "For years, he has held it together with a rubber band.", "For years, he has held it together with a rubber band.", *STORY),
        ("open", "n03", "One small plastic cover snapped.", "One small plastic cover snapped.", *STORY),
        ("open", "n04", "Nobody makes it now.", "Nobody makes it now.", *STORY),
        ("open", "n05", f"A print shop could make one. But {half} off, and it won't click shut.", f"A print shop could make one. But {half} off, and it won't click shut.", *STORY),
        ("open", "n07", f"Every home has one: {f['ewaste_bn_kg']} billion kilos of electronics thrown out in {f['ewaste_year']}.", f"Every home has one. {words(f['ewaste_bn_kg'])} billion kilos of electronics thrown out in twenty twenty two.", *STORY),
        ("title", "n08", f"This is PartSmith. A photo goes in. A part checked to {half} comes out.", f"This is Part Smith. A photo goes in. A part checked to {half} comes out.", *STORY),
        ("founder", "f1", "Hi, I'm Prashant, and I built this solo, during this hackathon, on Meta's models.", "Hi, I'm Prashant, and I built this solo, during this hackathon, on Meta's models.", *PRODUCT),
        ("flow", "w2", "Photo. Outline. A program that draws the part.", "Photo. Outline. A program that draws the part.", *PRODUCT),
        ("flow", "w3", "A check against the photo. A fix when it fails.", "A check against the photo. A fix when it fails.", *PRODUCT),
        ("flow", "w4", "A person's review. Then a file you can print.", "A person's review. Then a file you can print.", *PRODUCT),
        ("mat", "n09", "No caliper. Your laptop screen is the ruler.", "No caliper. Your laptop screen is the ruler.", *PRODUCT),
        ("photo", "n11", "Match a bank card once, lay the part on the markers, take one photo.", "Match a bank card once, lay the part on the markers, take one photo.", *PRODUCT),
        ("see", "v2", "Markers give true scale.", "Markers give true scale.", *PRODUCT),
        ("see", "v3", "SAM 3.1 is asked for the part's mask first.", "Sam three point one is asked for the part's mask first.", *PRODUCT),
        ("see", "v4", "If it isn't sure, code's own segmenter takes over.", "If it isn't sure, code's own segmenter takes over.", *PRODUCT),
        ("loop0", "n13", "Muse Spark Open writes a CadQuery program.", "Mewz Spark Open writes a cad query program.", *PRODUCT),
        ("loop", "n14", f"First build: {e0} millimetres off. Failed.", f"First build. {decimal(e0)} millimetres off. Failed.", *PRODUCT),
        ("loop", "n15", f"The agent reads the gap, and fixes it: {e1}.", f"The agent reads the gap, and fixes it. {decimal(e1)}.", *PRODUCT),
        ("loop", "n16", f"Third round: {e2}. Verified.", f"Third round. {decimal(e2)}. Verified.", *PRODUCT),
        ("export", "n16b", f"Only now does export unlock. About {minutes} minutes to print, ₹{rupees} of filament.", f"Only now does export unlock. About {words(minutes)} minutes to print, {words(rupees)} rupees of filament.", *PRODUCT),
        ("lie", "n18", "What if the model simply lies?", "What if the model simply lies?", *PRODUCT),
        ("lie", "n19", f"We scripted attacks that claim verified. {f['blocked']} of {f['attempts']} blocked.", f"We scripted attacks that claim verified. {words(f['blocked'])} of {words(f['attempts'])} blocked.", *PRODUCT),
        ("lie", "n20", "The model proposes. Code decides.", "The model proposes. Code decides.", *PRODUCT),
        ("knobs", "n21", "Need a change? Drag a knob.", "Need a change? Drag a knob.", *PRODUCT),
        ("say0", "s0", "Or say it, in Hindi and English.", "Or say it, in Hindi and English.", *PRODUCT),
        ("say", "say1", "cover ko ek millimeter lamba karo", "Cover ko ek millimeter lamba karo.", 0.6, 0.4),
        ("say", "s2", "Muse Voice Transcribe hears it, and the length moves one millimetre.", "Mewz Voice Transcribe hears it, and the length moves one millimetre.", *PRODUCT),
        ("fit", "n22", "Check it at true size on your screen.", "Check it at true size on your screen.", *PRODUCT),
        ("review", "n23", "A reviewer can pin what the photo missed.", "A reviewer can pin what the photo missed.", *PRODUCT),
        ("registry", "n24", "Verified parts join an open registry, for people and coding agents.", "Verified parts join an open registry, for people and coding agents.", *PRODUCT),
        ("others", "c2", "Today, AI image-to-3D guesses the size.", "Today, A I image to three D guesses the size.", *PRODUCT),
        ("others", "c3", "Scans are rough. Text-to-CAD needs your numbers.", "Scans are rough. Text to cad needs your numbers.", *PRODUCT),
        ("others", "c4", "And we found none that check your part before you print.", "And we found none that check your part before you print.", *PRODUCT),
        ("before", "b2", f"Stretch a mesh to fit, and the holes move {f['mesh_shift_mm']} millimetres. Turn a knob: {knob}.", f"Stretch a mesh to fit, and the holes move {decimal(f['mesh_shift_mm'])} millimetres. Turn a knob. {'zero' if f['knob_shift_mm'] == 0 else decimal(f['knob_shift_mm'])}.", *PRODUCT),
        ("hood", "m1", f"{len(f['meta'])} Meta models make this possible.", f"{words(len(f['meta']))} Meta models make this possible.", *PRODUCT),
        ("hood", "m2", "SAM 3.1 looks for the part.", "Sam three point one looks for the part.", *PRODUCT),
        ("hood", "m3", "Muse Spark 1.3 names the part and finds the break.", "Mewz Spark one point three names the part and finds the break.", *PRODUCT),
        ("hood", "m4", "Muse Spark Open, on open weights, writes and fixes it.", "Mewz Spark Open, on open weights, writes and fixes it.", *PRODUCT),
        ("hood", "m7", "None can approve a part. Only the verifier can.", "None can approve a part. Only the verifier can.", *PRODUCT),
        ("meta", "m5", "Muse Wonder cites specs. Muse Image previews repairs.", "Mewz Wonder cites specs. Mewz Image previews repairs.", *PRODUCT),
        ("saves", "e1", f"Photo to checked file: {f['time']['run_minutes']} minutes.", f"Photo to checked file. {decimal1(f['time']['run_minutes'])} minutes.", *PRODUCT),
        ("saves", "e3", f"The next person: about {f['time']['rebake_ms']} milliseconds.", f"The next person. About {words(f['time']['rebake_ms'])} milliseconds.", *PRODUCT),
        ("saves", "e4", "The screen replaces the caliper. The agent replaces CAD. The verifier replaces trial prints.", "The screen replaces the caliper. The agent replaces cad. The verifier replaces trial prints.", *PRODUCT),
        ("test", "t1", f"In {f['scale']['done']} live runs, the loop passed {f['scale']['ps_pass']} of {f['scale']['pairs']} paired photos. A single shot: {f['scale']['b1_pass']}.", f"In {words(f['scale']['done'])} live runs, the loop passed {words(f['scale']['ps_pass'])} of {words(f['scale']['pairs'])} paired photos. A single shot, {words(f['scale']['b1_pass'])}.", *STORY_FAST),
        ("test", "t2", f"A side photo cut wrong passes from {f['scale']['top_off']} of {f['scale']['top_n']} to {f['scale']['side_off']} of {f['scale']['side_n']}.", f"A side photo cut wrong passes from {words(f['scale']['top_off'])} of {words(f['scale']['top_n'])} to {words(f['scale']['side_off'])} of {words(f['scale']['side_n'])}.", *STORY_FAST),
        ("test", "t3", *tested(f), *STORY_FAST),
        ("market", "k1", "Over a million entry-level 3D printers shipped in one quarter.", "Over a million entry level three D printers shipped in one quarter.", *STORY_FAST),
        ("market", "k2", "And Europe's repair law says makers can't block printed spares.", "And Europe's repair law says makers can't block printed spares.", *STORY_FAST),
        ("vision", "v9", "Our vision: one snapped piece of plastic should never mean throwing out the whole thing.", "Our vision. One snapped piece of plastic should never mean throwing out the whole thing.", *STORY_FAST),
        ("vision", "f3", "The goal: an open library of verified parts, so the next person with that remote just downloads the fix.", "The goal. An open library of verified parts, so the next person with that remote just downloads the fix.", *STORY_FAST),
        ("close", "n37", "Nine at night. He doesn't need a new remote.", "Nine at night. He doesn't need a new remote.", *STORY),
        ("close", "n38", "He needs one small part. Now you can ask for it with a photo.", "He needs one small part. Now you can ask for it with a photo.", *STORY),
        ("end", "f2", "If you have a broken part at home, send it in. The most wanted parts get modelled first.", "If you have a broken part at home, send it in. The most wanted parts get modelled first.", *PRODUCT),
    ]
    return out


def load() -> list[tuple[str, str, str, str, float, float]]:
    return lines(json.load(open(FACTS)))


if __name__ == "__main__":
    total = 0
    for s, i, c, sp, *_ in load():
        total += len(sp.split())
        print(i, s, c)
    print("spoken words:", total)
