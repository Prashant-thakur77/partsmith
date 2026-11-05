"""The submission kit: form text, video title and description, chapters, X post, bonus claims. Numbers come from facts.json.

    python3 video/facts.py && python3 video/submission_kit.py  ->  ~/Downloads/PartSmith-submission.md
"""

from __future__ import annotations

import json
import os

WORK = os.path.expanduser("~/Videos/partsmith")
OUT = os.path.expanduser("~/Downloads/PartSmith-submission.md")
REPO = "https://github.com/Prashant-thakur77/partsmith"


def kit(f: dict, chapters: str, length: str) -> str:
    run, audit, t = f["run"], f["audit"], f["time"]
    e0, e1, e2 = run["errors"]
    site = f["site"] or "(live link)"
    video = f["video"] or "(your YouTube link)"
    tests = f["tests"]
    backend = tests.get("backend", {}).get("passed")
    web = tests.get("web_unit", {}).get("passed")
    browser = tests.get("browser", {}).get("passed")
    suites = ", ".join(x for x in (f"{backend:,} backend" if backend else "", f"{web} web unit" if web else "", f"{browser} browser" if browser else "") if x)
    sam, spark = f["meta"][0]["calls"], f["meta"][1]["calls"]
    return f"""# PartSmith: everything to paste

## Links
- Live site: {site}
- Judge path: {site}/judges
- Interactive deck: {site}/deck/index.html
- Code: {REPO}
- Video: {video}

## Project name
PartSmith

## One line
Photo of a broken plastic part → a measured, verified, printable replacement. No caliper: your laptop screen is the ruler.

## Track and problem statement
Indie Developer track · Push the Frontier

## About the project
**The problem.** A small plastic part snaps: a remote's battery cover, a cupboard latch, a clip. Nobody sells it, so the whole device gets thrown out. A printer could make the part, but it needs an exact file, and that takes a caliper and CAD skills. Half a millimetre off and it won't fit.

**What it does.** You lay the part on your laptop screen, which draws markers at true size after a one-time match against a bank card, and take a phone photo. SAM 3.1 is asked first for the part's outline, code's own segmenter takes over when it isn't sure, and plain code turns the outline into millimetres. Muse Spark Open writes a real CadQuery program with named knobs, not a mesh. A deterministic verifier lays the model over the photo and reports the gap. The agent reads the gap and fixes the program until it is inside {f['limit_mm']} mm. Only then does the export unlock. Verified parts join an open registry that people and coding agents can search over REST and MCP.

**How Meta's models make it possible.**
- SAM 3.1 is asked first for the part's mask; when it isn't confident, code's threshold segmenter takes over, which has been most runs on rendered photos ({sam} live calls).
- Muse Spark 1.3 names the part, finds the break and points at each hole ({spark} live calls).
- Muse Spark Open writes and fixes the program on open weights ({f['open_calls']} of {f['builder_calls']} builder calls).
- Muse Wonder finds a published spec; code keeps a value only if it is cited.
- Muse Image previews the repair, always labelled as an AI image.
- Muse Voice Transcribe takes edits in Hindi and English mixed, and code clamps them to the knob's range.
Muse Glimmer is written in as an independent judge for the open-weights path but has not yet run live on a GPU, so it is not claimed.

**The rule.** The model proposes; code decides. Only the verifier can mark a part verified, and every download passes one export gate.

**Proof, with the source of each number in the repo.**
- A recorded live run: {e0} → {e1} → {e2} mm, verified, {t['run_minutes']} minutes from photo to file, about {round(run['print_minutes'])} minutes to print and about ₹{round(run['inr'])} of filament by estimate.
- Scripted lying-model attacks on the real verifier: {f['blocked']} of {f['attempts']} blocked.
- Bad or unsuitable photos caught: {f['redteam'][0]} of {f['redteam'][1]}. Intact parts accepted: {f['control'][0]} of {f['control'][1]}.
- Median error, single shot to full loop, on rendered photos with exact ground truth: {f['b1_median_mm']} → {f['synthetic_median_mm']} mm.
- Public photos of real objects, pasted on a rendered mat, against published sizes: {f['public']['median_mm']} mm median, n = {f['public']['n']}.
- Moving one dimension: stretching a mesh shifts holes by a median {f['mesh_shift_mm']} mm; turning a knob shifts them {f['knob_shift_mm']} mm ({f['mesh_parts']} parts).
- Tests passing: {suites}.

**What is not proven yet.** No real phone captures of parts on a laptop screen and no real prints so far: real parts measured is {f['real_parts']}. Of {audit['verified']} verified parts in the stored runs, {audit['within']} were within {f['limit_mm']} mm on every size; of the others, {audit['off_height']} were height, which a top photo cannot see, which is why the side photo matters. The results page and README state all of this.

**Why it matters.** {f['ewaste_bn_kg']} billion kg of e-waste in {f['ewaste_year']} ({f['ewaste_source']}). {f['printers_text']} entry-level 3D printers shipped in {f['printers_period']} ({f['printers_source']}), and {f['repair_law']} stops makers blocking 3D-printed spares. The goal is an open library of verified parts, so the next person with that remote just downloads the fix.

**Built during the hackathon.** First commit {f['first_commit']}; the full history is in the repo.

## Bonus prizes
- **Best Build on Meta Open Weight Models.** Muse Spark Open through partner inference (Baseten) runs the CAD builder and fix agent. Evidence: `eval/reports/latest/open_weights.json`, `/models` on the site.
- **Best Agentic Use-Case.** The fix agent drives PartSmith's own tools (inspect residuals, measure, render, set knobs) until code verifies the part, with every tool call shown on the job page. Evidence: the Agent tab on {site}/jobs/{run['id']}.
- **Best Creative Build.** Muse Image completes the broken region under a code gate, previews the repair and draws install cards; it also painted this film's story scenes. Evidence: the job page and the film.
- **Most Viral Project.** Post on X, then paste the link.
- **Community Vote.** Share the gallery link after submitting.

## YouTube
**Title (under 100 characters):** PartSmith: photo of a broken part to a verified replacement (Meta AI Hackathon)

**Description:**
A small plastic part snaps, nobody sells it, and the whole device gets thrown out. PartSmith turns a phone photo on your laptop screen into a measured, parametric, verified replacement file, using Meta's SAM 3.1 and Muse models, with a code verifier that the model cannot fool.

You'll see: a real recorded live run going from fail to fix to pass, a scripted lying model getting caught, a live Hindi and English voice edit, how six Meta models each do one job, and the test results. Replays, rendered sample photos and scripted attacks are labelled on screen.

Try it, no sign-in: {site}
Code: {REPO}
Built for the Meta Global AI Developer Hackathon, Indie track.

**Length:** {length}. **Visibility:** Public. **Made for kids:** No. **Captions:** already burned into the main file, so don't also upload the .srt unless you use the no-captions copy.

**Chapters:**
{chapters}
**Thumbnail:** PartSmith-youtube-thumbnail.png

## X post
Photo of a broken plastic part → a measured, verified, printable replacement.

No caliper: your laptop screen is the ruler. Meta's SAM 3.1 looks for the part, Muse Spark Open writes the CAD, and code checks it against the photo. A model that lies gets caught: {f['blocked']}/{f['attempts']}.

Built solo for the Meta Global AI Developer Hackathon. Got a broken part? Send it in.

{site}

(Attach the film. Then paste the post link in the submission form.)

## Before you press submit
1. Repo opens in a private window, and the README Credits section is there.
2. The video plays when logged out.
3. The live site opens on your phone.
4. Everyone who worked on it is listed (just you).
5. Save a screenshot of the confirmation page.
"""


def main() -> None:
    f = json.load(open(f"{WORK}/build/facts.json"))
    total = json.load(open(f"{WORK}/build/timeline.json"))["total"]
    chapters = open(f"{WORK}/final/chapters.txt").read()
    open(OUT, "w").write(kit(f, chapters, f"{int(total // 60)}:{int(total % 60):02d}"))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
