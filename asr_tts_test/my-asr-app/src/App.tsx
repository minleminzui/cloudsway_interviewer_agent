import React, { useEffect, useRef, useState } from "react";

const WS_URL = "ws://127.0.0.1:8765/asr";
const LANG = "zh-CN";

type Log = { t: string; dir: "⇢" | "⇠"; msg: string };

export default function App() {
  const wsRef = useRef<WebSocket | null>(null);
  const acRef = useRef<AudioContext | null>(null);
  const procRef = useRef<ScriptProcessorNode | null>(null);
  const srcRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [status, setStatus] = useState("未连接");
  const [partial, setPartial] = useState("…");
  const [finalText, setFinalText] = useState("");
  const [handshake, setHandshake] = useState<string>("");
  const [logs, setLogs] = useState<Log[]>([]);
  const logBoxRef = useRef<HTMLDivElement | null>(null);

  function addLog(dir: "⇢" | "⇠", obj: any) {
    const t = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    const msg =
      typeof obj === "string" ? obj : (() => { try { return JSON.stringify(obj); } catch { return String(obj); } })();
    setLogs((prev) => {
      const next = [...prev, { t, dir, msg }];
      return next.length > 500 ? next.slice(-500) : next;
    });
    // 控制台也打印
    if (dir === "⇠") console.info("[IN]", obj);
    else console.info("[OUT]", obj);
  }

  useEffect(() => {
    // 日志自动滚动
    if (logBoxRef.current) {
      logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
    }
  }, [logs]);

  function float32ToPCM16(buf: Float32Array): ArrayBuffer {
    const out = new ArrayBuffer(buf.length * 2);
    const v = new DataView(out);
    for (let i = 0; i < buf.length; i++) {
      let s = Math.max(-1, Math.min(1, buf[i]));
      v.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return out;
    // true = little-endian（和大多数后端一致）
  }

  async function start() {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    // 1) 连接 WS
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = async () => {
      setStatus("已连接");
      addLog("⇢", { type: "start (about to send after mic open)" });

      // 2) 打开麦克风 / 建音频管线
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            noiseSuppression: false,
            echoCancellation: false,
            autoGainControl: false,
          },
        });
        streamRef.current = stream;

        const ac = new (window.AudioContext || (window as any).webkitAudioContext)();
        acRef.current = ac;

        const src = ac.createMediaStreamSource(stream);
        srcRef.current = src;

        const proc = ac.createScriptProcessor(2048, 1, 1);
        procRef.current = proc;

        proc.onaudioprocess = (e) => {
          const ch0 = e.inputBuffer.getChannelData(0); // Float32 [-1,1]
          if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
          const ab = float32ToPCM16(ch0);
          try {
            wsRef.current.send(ab);
          } catch (err) {
            addLog("⇢", `send audio error: ${String(err)}`);
          }
        };

        src.connect(proc);
        proc.connect(ac.destination); // 必须连接到图上（不输出声音）

        // 3) 发送 start（告诉后端真实采样率 & 语言）
        const startMsg = { type: "start", sampleRate: ac.sampleRate, language: LANG };
        ws.send(JSON.stringify(startMsg));
        addLog("⇢", startMsg);
        setStatus(`已连接（采样率 ${ac.sampleRate}Hz）`);
      } catch (err) {
        setStatus("麦克风不可用");
        addLog("⇢", `getUserMedia error: ${String(err)}`);
        ws.close();
      }
    };

    ws.onmessage = (ev) => {
      let obj: any = null;
      try {
        obj = JSON.parse(ev.data);
      } catch {
        // 后端只会发 JSON；若不是，直接记录
        addLog("⇠", ev.data);
        return;
      }
      addLog("⇠", obj);

      const tp = obj?.type;

      if (tp === "handshake") {
        setHandshake(JSON.stringify(obj.payload));
      } else if (tp === "partial") {
        setPartial(obj.text || "");
      } else if (tp === "final") {
        const t = (obj.text || "").trim();
        if (t && t !== finalText) { // 判断是否与当前的 finalText 相同
          setFinalText((p) => (p ? p + " " + t : t));
        }
        setPartial("…");
      } else if (tp === "payload") {
        // 其他原样日志就行
      } else if (tp === "stopped") {
        setStatus("已停止（仍可断开）");
      } else if (tp === "error") {
        setStatus("错误");
      }
    };

    ws.onerror = (e) => {
      setStatus("连接出错");
      addLog("⇠", `ws error: ${String(e)}`);
    };
    ws.onclose = () => {
      setStatus("连接关闭");
    };
  }

  function stop() {
    // 通知后端停止（会触发最终 VAD 收尾）
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      const stopMsg = { type: "stop" };
      wsRef.current.send(JSON.stringify(stopMsg));
      addLog("⇢", stopMsg);
    }
  }

  function disconnect() {
    try {
      procRef.current?.disconnect();
      srcRef.current?.disconnect();
      acRef.current?.close();
    } catch {}
    streamRef.current?.getTracks().forEach((t) => t.stop());
    procRef.current = null;
    srcRef.current = null;
    acRef.current = null;
    streamRef.current = null;

    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }
    setStatus("未连接");
  }

  function resetText() {
    setPartial("…");
    setFinalText("");
    setHandshake("");
  }

  return (
    <div style={{ maxWidth: 960, margin: "40px auto", fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Arial" }}>
      <h1 style={{ fontSize: 28, marginBottom: 12 }}>
        🎤 实时语音转写（Volcengine via Local Relay）
      </h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <button onClick={start} style={btn}>开始</button>
        <button onClick={stop} style={btn}>结束</button>
        <button onClick={disconnect} style={btn}>断开</button>
        <button onClick={resetText} style={btn}>清空文本</button>
      </div>
      <div style={{ marginBottom: 16, color: "#666" }}>状态：{status}</div>

      <Card title="握手信息">
        <pre style={pre}>{handshake || "(等待握手…)"}</pre>
      </Card>

      <Card title="中间结果（partial）">
        <div style={{ minHeight: 28, fontSize: 18 }}>{partial}</div>
      </Card>

      <Card title="最终结果（final，累计）">
        <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{finalText}</div>
      </Card>

      <Card title="调试日志（入⇠/出⇢，自动滚动）">
        <div ref={logBoxRef} style={{ height: 240, overflow: "auto", background: "#0b1020", color: "#bfe1ff", padding: 8, borderRadius: 8 }}>
          {logs.map((l, i) => (
            <div key={i} style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 }}>
              <span style={{ color: "#7dd3fc" }}>{l.t}</span>{" "}
              <span style={{ color: l.dir === "⇢" ? "#86efac" : "#fca5a5" }}>{l.dir}</span>{" "}
              <span>{l.msg}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}


function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ border: "1px solid #eee", borderRadius: 12, padding: 12, marginBottom: 12 }}>
      <div style={{ fontSize: 14, color: "#666", marginBottom: 6 }}>{title}</div>
      {children}
    </div>
  );
}

const btn: React.CSSProperties = {
  padding: "8px 14px",
  borderRadius: 10,
  border: "1px solid #e5e7eb",
  background: "#fff",
  cursor: "pointer",
};

const pre: React.CSSProperties = {
  margin: 0,
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: 12,
};
