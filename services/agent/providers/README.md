# `services/agent/providers` — every model call

All model traffic goes through this package. With zero keys every stage runs as a labelled deterministic mock.
Adding a key to `.env` switches the stages that use it to live, with no code changes.

## Modes

| Setting | Effect |
|---|---|
| `PROVIDER_MODE` unset | live where the stage's key/URL exists, mock otherwise (one warning per stage, shown on `/status`) |
| `PROVIDER_MODE=mock` | every stage is a deterministic mock (labelled `mode="mock"` everywhere) |
| `PROVIDER_MODE=replay` | serve `$PARTSMITH_HOME/recordings/<hash>.json`; a miss falls back to the mock with a warning |
| `PROVIDER_RECORD=1` | save every successful live call (agent loops: every turn) for replay |
| `OPEN_WEIGHTS_ONLY=1` | route every stage to open-weight models; stages with none run as mocks |
| `PROVIDER_FALLBACK_TO_MOCK=1` | when every live provider fails, answer with a labelled mock instead of raising |
| `PARTSMITH_DAILY_USD_CAP=5` | daily spend cap (UTC day) for live calls: once reached, live calls raise `BudgetExceeded` with a clear message until midnight UTC; spend is kept in `$PARTSMITH_HOME/spend/` (`budget.py`) |
| `PROVIDER_MAX_RETRIES`, `PROVIDER_TIMEOUT_S` | retries on 429/5xx/timeouts (default 3), request timeout (default 180 s) |

## Stage routing (`routing.py`, first route with a key wins)

| Stage | Role | Default chain | `OPEN_WEIGHTS_ONLY=1` |
|---|---|---|---|
| `understand` | Understander | muse-spark-1.3 | Glimmer (Modal → Together) |
| `plan` / `build` / `fix` | Planner / Builder / Fixer | Spark Open: Baseten → Fireworks → Together → muse-spark-1.3 | Spark Open chain |
| `fix_agent` | Fixer agent (tool loop) | Spark Open: Baseten → Fireworks → Together → muse-spark-1.3 | Spark Open chain |
| `judge`, `capture_triage` | Judge, Capture triage | Glimmer 30B: llama.cpp on Modal → Together | same |
| `voice_map`, `variant` | Voice editor, Variant mapper | muse-spark-1.3 | Spark Open chain |
| `steer_plan` | Factory planner | muse-wonder-1.0 | Spark Open chain |
| `describe_plan` | Describer (words + numbers → one template part) | muse-spark-1.3 | Spark Open chain |
| `spec_lookup` | Spec finder | muse-wonder-1.0 + `web_search` | mock |
| `segment` | Segmenter (text prompt) | sam-3.1 → SAM 3 on Modal | SAM 3 on Modal |
| `mate_points` | Mate pointer (where it fits: points, never sizes) | muse-spark-1.3 | Glimmer chain |
| `segment_points` | Feature cutter (points/box) | sam-3.1 | mock |
| `segment_video` | Orbit tracker | sam-3.1 video → SAM 3.1 multiplex on Modal | SAM 3.1 on Modal |
| `image` | Previews, edits, install cards | muse-image-1.0 | mock |
| `reconstruct` | Region completer | muse-image-1.0 | mock |
| `transcribe` | Transcriber (file) | muse-voice-transcribe-1.0 | mock |
| `transcribe_stream` | Live voice (WebSocket) | muse-voice-transcribe-1.0 realtime, file endpoint as fallback | mock |

## Public API

```python
from services.agent import providers as P

P.complete(stage, P.ModelRequest(...)) -> P.Completion
P.run_agent(stage, req, tools: Sequence[P.ToolSpec], call_tool: Callable[[str, dict], P.ToolResult], *,
            max_turns=12, keep_images=4) -> P.AgentResult
P.segment(image_png, prompt) -> list[(bool mask, score)]
P.segment_points(image_png, points_pos, points_neg=(), box=None) -> list[(bool mask, score)]
P.segment_video(video_bytes, mime, prompt, *, fps=5) -> list[P.FrameMask]
P.lookup_spec(query, want, *, fixture=None) -> P.SpecLookup
P.generate_image(prompt, reference_images=(), *, editable=False) -> P.ImageResult
P.reconstruct(rectified_png, keep_mask_png, instruction="") -> P.ImageResult
P.edit_image(previous_id, instruction) -> P.ImageResult
P.install_card(photo_png, render_png, steps) -> list[P.ImageResult]
P.transcribe(audio, mime, language_hint=None) -> P.Transcript
P.transcribe_stream(chunks, *, keywords=(), language_bias=("English", "Hindi"), pace=True, mock_text=None)
    -> Iterator[P.VoiceEvent]
P.status(); P.overall_mode(); P.warnings(); P.stage_mode(stage); P.open_weights_summary(events=None)
P.job_context(job_id, emit, ctx="")    # model_call, thought and tool_call events go to `emit`
P.register_mock(stage, handler)        # agent stages: handler(req, history) -> {"tool", "args"} | {"final"}
```

## Rules the code enforces

- **Model proposes, code decides.**
  - Agent tool calls run through our `call_tool`.
  - Spec-lookup values are accepted only if a web search really ran and the cited URL is one the search returned.
  - Muse Image completions keep every intact pixel identical. Whether a completion is accepted is decided by metrology.
- **Meta API specifics:**
  - Strict JSON goes through `text.format` on Responses and `response_format` on Chat Completions.
  - `tool_choice` is always `"auto"`.
  - Reasoning effort `"none"` is mapped to `"minimal"`.
  - Long calls are streamed.
  - Bodies over 1 MiB move their images and videos to the Files API.
  - SAM takes one noun phrase per text call. Its masks are box-local and get pasted into a full frame.
  - Muse Image reference images are wrapped in a `role:user` message.
  - The realtime voice key travels in the first WebSocket frame.
- **Glimmer on llama.cpp:**
  - `reasoning_effort` is not supported, so reasoning goes through `chat_template_kwargs.reasoning_strength`.
  - Several images per message work. Each one is downscaled to at most 1,024 px, and a request takes at most 12.
  - Images share a 65,536-token slot with the reasoning.
- **Slow routes go last (`health.py`):** the chains move on when a provider fails, and also when it is slow.
  - A text route whose last 6 calls for a stage average more than 40 s is tried after the other ready routes for that stage, for 15 minutes.
  - Windows are per stage: vision calls in understand are slow by nature and say nothing about fixer turns.
  - This only applies when another route is ready. Every call still emits its `model_call` event with the model that served it.
- **Cost:** every call reports `usd` from `pricing.py`.
  - Meta per-token, per-image, per-video-frame (minimum 50 frames), per-search and per-audio-hour rates come from the published price list.
  - Self-hosted Modal calls report $0, because the cost is GPU time.
  - Fireworks and Together Spark Open rates are assumed equal to Baseten's (flagged in code).
  - Mock and replay calls cost $0.

## Tests

`uv run pytest services/agent/providers -q` runs with no network. Fake OpenAI clients, `httpx.MockTransport` and a
fake WebSocket check the exact request shapes. The mocks run on real pixels and real tools.
