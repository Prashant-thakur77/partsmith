// The site's outside links match docs/links.json, and the film's player address uses the privacy-enhanced host.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { LINKS, filmEmbedUrl, youtubeId } from "../src/lib/site-links.ts";

const source = JSON.parse(readFileSync(new URL("../../../docs/links.json", import.meta.url), "utf8"));

test("site links are the same as docs/links.json", () => {
  assert.equal(LINKS.repo, source.repo);
  assert.equal(LINKS.video, source.video);
});

test("youtubeId reads short and long links and refuses anything else", () => {
  assert.equal(youtubeId("https://youtu.be/abc123"), "abc123");
  assert.equal(youtubeId("https://www.youtube.com/watch?v=abc123"), "abc123");
  assert.equal(youtubeId("https://example.com/abc123"), null);
  assert.equal(youtubeId("not a url"), null);
});

test("the player address uses YouTube's privacy-enhanced host", () => {
  assert.match(filmEmbedUrl("https://youtu.be/abc123"), /^https:\/\/www\.youtube-nocookie\.com\/embed\/abc123\?/);
  assert.equal(filmEmbedUrl("https://example.com"), null);
});
