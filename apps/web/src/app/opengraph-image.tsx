import { ImageResponse } from "next/og";

export const alt = "PartSmith — photo to verified replacement part";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", background: "#111", color: "#fafafa", padding: 72, fontFamily: "sans-serif" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div style={{ width: 56, height: 56, borderRadius: 12, background: "#fafafa", display: "flex", alignItems: "flex-end", justifyContent: "flex-end", padding: 8 }}>
            <div style={{ width: 16, height: 16, borderRadius: 8, background: "#f26a21" }} />
          </div>
          <div style={{ fontSize: 36, fontWeight: 600 }}>PartSmith</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <div style={{ fontSize: 68, fontWeight: 600, lineHeight: 1.05, letterSpacing: -2 }}>A broken plastic part in.</div>
          <div style={{ fontSize: 68, fontWeight: 600, lineHeight: 1.05, letterSpacing: -2, color: "#f26a21" }}>A proven replacement out.</div>
        </div>
        <div style={{ fontSize: 26, color: "#a3a3a3" }}>Measured from a photo · parametric CAD · verified by code, not by the model</div>
      </div>
    ),
    size,
  );
}
