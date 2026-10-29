// Replay chip labels (node --test; no browser): names that repeat get their capture preset, then a number.
import assert from "node:assert/strict";
import test from "node:test";
import { distinctTitles } from "../src/lib/format.ts";

test("titles that share a name are told apart by their preset, others stay short", () => {
  const got = distinctTitles([
    "Battery compartment cover (synthetic, clean)",
    "Battery compartment cover (synthetic, white-part)",
    "Spacer / standoff (synthetic, clean) (synthetic sample)",
    "Battery compartment cover (synthetic)",
  ]);
  assert.deepEqual(got, [
    "Battery compartment cover · clean",
    "Battery compartment cover · white-part",
    "Spacer / standoff",
    "Battery compartment cover",
  ]);
});

test("labels that still repeat get a running number", () => {
  assert.deepEqual(distinctTitles(["Hook (synthetic, tilt)", "Hook (synthetic, tilt)"]), ["Hook · tilt (1)", "Hook · tilt (2)"]);
});
