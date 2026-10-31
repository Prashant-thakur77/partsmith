// Replay chip labels (node --test; no browser): names that repeat get their capture preset, then a number.
import assert from "node:assert/strict";
import test from "node:test";
import { distinctTitles, fmtErr } from "../src/lib/format.ts";

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

test("a max error within 0.01 mm of its limit shows 3 decimals, so both sides of the line never read 0.50", () => {
  assert.equal(fmtErr(0.4958), "0.496"); // verified
  assert.equal(fmtErr(0.4985), "0.499"); // best effort (another check failed)
  assert.equal(fmtErr(0.4262), "0.43");
  assert.equal(fmtErr(4.696), "4.70");
  assert.equal(fmtErr(1.004, 1.0), "1.004");
});
