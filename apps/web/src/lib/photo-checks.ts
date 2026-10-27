/**
 * Instant client-side photo checks (before upload). Cheap heuristics only — the server's capture gate is the authority.
 * Resolution comes from the decoded image; brightness and sharpness from a downscaled greyscale copy.
 */
export type ClientCheck = { name: string; ok: boolean; level: "ok" | "warn" | "fail"; text: string };
export type PhotoInfo = { width: number; height: number; url: string; checks: ClientCheck[] };

const MAX_BYTES = 25 * 1024 * 1024;

async function decode(file: File): Promise<{ img: CanvasImageSource; width: number; height: number }> {
  if ("createImageBitmap" in window) {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { img: bmp, width: bmp.width, height: bmp.height };
    } catch {
      /* fall back to <img> */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return { img, width: img.naturalWidth, height: img.naturalHeight };
  } finally {
    URL.revokeObjectURL(url);
  }
}

function stats(img: CanvasImageSource, w: number, h: number): { luma: number; clipped: number; sharp: number } {
  const W = 320;
  const H = Math.max(1, Math.round((h / w) * W));
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const ctx = c.getContext("2d", { willReadFrequently: true });
  if (!ctx) return { luma: 128, clipped: 0, sharp: 100 };
  ctx.drawImage(img, 0, 0, W, H);
  const d = ctx.getImageData(0, 0, W, H).data;
  const g = new Float32Array(W * H);
  let sum = 0;
  let clipped = 0;
  for (let i = 0, p = 0; i < d.length; i += 4, p++) {
    const y = 0.2126 * d[i]! + 0.7152 * d[i + 1]! + 0.0722 * d[i + 2]!;
    g[p] = y;
    sum += y;
    if (y > 250) clipped++;
  }
  // variance of the 4-neighbour Laplacian: low values mean a blurred photo
  let n = 0;
  let mean = 0;
  let m2 = 0;
  for (let y = 1; y < H - 1; y++) {
    for (let x = 1; x < W - 1; x++) {
      const i = y * W + x;
      const lap = g[i - 1]! + g[i + 1]! + g[i - W]! + g[i + W]! - 4 * g[i]!;
      n++;
      const delta = lap - mean;
      mean += delta / n;
      m2 += delta * (lap - mean);
    }
  }
  return { luma: sum / (W * H), clipped: clipped / (W * H), sharp: n > 1 ? m2 / (n - 1) : 0 };
}

export async function checkPhoto(file: File): Promise<PhotoInfo> {
  const checks: ClientCheck[] = [];
  if (!file.type.startsWith("image/")) {
    return { width: 0, height: 0, url: "", checks: [{ name: "type", ok: false, level: "fail", text: "Not an image file." }] };
  }
  if (file.size > MAX_BYTES) checks.push({ name: "size", ok: false, level: "fail", text: "File is over 25 MB — export a smaller JPEG." });
  const { img, width, height } = await decode(file);
  const long = Math.max(width, height);
  checks.push(
    long >= 1600
      ? { name: "resolution", ok: true, level: "ok", text: `${width} × ${height} px` }
      : { name: "resolution", ok: false, level: "warn", text: `${width} × ${height} px — under 1600 px; small features may not measure well.` },
  );
  const s = stats(img, width, height);
  if (s.luma < 60) checks.push({ name: "exposure", ok: false, level: "warn", text: "Looks dark — raise screen brightness or add light." });
  else if (s.clipped > 0.25) checks.push({ name: "exposure", ok: false, level: "warn", text: "Large blown-out areas — likely glare on the screen." });
  else checks.push({ name: "exposure", ok: true, level: "ok", text: "Exposure looks fine" });
  checks.push(
    s.sharp >= 40
      ? { name: "sharpness", ok: true, level: "ok", text: "Looks sharp" }
      : { name: "sharpness", ok: false, level: "warn", text: "May be blurred — hold still and tap to focus on the part." },
  );
  if ("close" in img && typeof img.close === "function") img.close();
  return { width, height, url: URL.createObjectURL(file), checks };
}
