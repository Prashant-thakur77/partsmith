"use client";

export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh", margin: 0 }}>
        <div style={{ textAlign: "center", maxWidth: 420, padding: 24 }}>
          <h1 style={{ fontSize: 22 }}>PartSmith hit an unexpected error</h1>
          <p style={{ color: "#555" }}>Reload the page. If it keeps happening, the backend logs have the details.</p>
          <button type="button" onClick={reset} style={{ padding: "8px 16px", borderRadius: 6, border: "1px solid #ccc", background: "#fff", cursor: "pointer" }}>
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
