"use client";

import { useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;

export default function Home() {
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");

  async function send() {
    alert("clicked");
    if (!API_BASE) {
      alert("Missing NEXT_PUBLIC_API_BASE_URL in frontend/.env.local");
      return;
    }

    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, city: "St Pete" }),
    });

    const data = await res.json();
    setReply(data.reply ?? JSON.stringify(data));
  }

  return (
    <main style={{ padding: 40, fontFamily: "Arial" }}>
      <h1>St Pete Tour Guide</h1>

      <p>Ask for date spots, rooftop drinks, sports bars, etc.</p>

      <textarea
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        placeholder="Best rooftop drinks in downtown St Pete?"
        style={{ width: "100%", height: 110, padding: 10 }}
      />

      <div style={{ marginTop: 10 }}>
        <button onClick={send} style={{ padding: "10px 16px" }}>
          Ask
        </button>
      </div>

      <div style={{ marginTop: 20 }}>
        <strong>Reply:</strong>
        <p>{reply}</p>
      </div>
    </main>
  );
}
