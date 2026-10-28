// Unit tests for the fit-test coupon feedback helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { SESSION_RE, couponDownloaded, couponFeatures, deviceId, markCouponDownloaded, newDeviceId, reportBody } from "../src/lib/coupon-fit.ts";

function memory() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), m };
}

test("coupon features follow the coupon's rule: holes, slots, D-bores, identical sizes once, at most 4", () => {
  const spec = [
    { kind: "outline", id: "body" },
    { kind: "through_hole", id: "hole_1", diameter: { value: 3.4 } },
    { kind: "through_hole", id: "hole_2", diameter: { value: 3.4 } },
    { kind: "blind_hole", id: "pin", diameter: { value: 2 } },
    { kind: "slot", id: "slot_a", width: { value: 4 }, length: { value: 10 } },
    { kind: "d_shaft_bore", id: "shaft", diameter: { value: 6 } },
    { kind: "through_hole", id: "hole_3", diameter: { value: 5 } },
  ];
  const f = couponFeatures(spec);
  assert.deepEqual(f.map((x) => x.id), ["hole_1", "pin", "slot_a", "shaft"]);
  assert.match(f[0].label, /hole 3\.4 mm/);
});

test("without a PartSpec the part's internal-fit knobs are the features; nothing at all gives one overall row", () => {
  const params = [
    { name: "outer_d", label: "Outer diameter", unit: "mm", affects_fit: true, topology: false },
    { name: "bore_d", label: "Bore diameter", unit: "mm", affects_fit: true, topology: false },
    { name: "hole_count", label: "Holes", unit: "", affects_fit: true, topology: true },
  ];
  assert.deepEqual(couponFeatures(null, params), [{ id: "bore_d", label: "Bore diameter" }]);
  assert.deepEqual(couponFeatures([], []), [{ id: "fit", label: "coupon overall" }]);
});

test("device id is random, valid for the server and stable per browser", () => {
  assert.match(newDeviceId(), SESSION_RE);
  const s = memory();
  const a = deviceId(s);
  assert.ok(a && SESSION_RE.test(a));
  assert.equal(deviceId(s), a);
  assert.equal(deviceId(null), null);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => {} };
  assert.equal(deviceId(broken), null);
});

test("coupon download flag", () => {
  const s = memory();
  assert.equal(couponDownloaded(s), false);
  markCouponDownloaded(s, 123);
  assert.equal(couponDownloaded(s), true);
  assert.equal(couponDownloaded(null), false);
});

test("report body keeps answered features only and drops 'how much' for a good fit", () => {
  const body = reportBody("pla-fdm-0.4", "d-abcdefghij", {
    hole_1: { fit: "tight", amount: "very" },
    slot_a: { fit: "ok", amount: "barely" },
    pin: {},
  }, { jobId: "j_1" });
  assert.deepEqual(body, {
    preset: "pla-fdm-0.4",
    session: "d-abcdefghij",
    features: [
      { feature: "hole_1", fit: "tight", amount: "very" },
      { feature: "slot_a", fit: "ok", amount: null },
    ],
    job_id: "j_1",
  });
  assert.equal("slug" in body, false);
});
