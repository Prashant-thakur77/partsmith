import assert from "node:assert/strict";
import { test } from "node:test";
import { fmtDate } from "../src/lib/format.ts";

test("fmtDate prints the same text in every time zone", () => {
  const seen = new Set();
  for (const tz of ["UTC", "Asia/Kolkata", "America/New_York"]) {
    process.env.TZ = tz;
    seen.add(fmtDate(1793284591));
  }
  assert.equal(seen.size, 1);
  assert.match([...seen][0], /UTC$/);
});
