// frontend/src/utils/setupAudioUnlock.ts
export function setupGlobalAudioUnlock() {
  if ((window as any).__tts_global_unlocked__) return;

  const createAndUnlock = async () => {
    try {
      const ctx = new AudioContext();
      const buffer = ctx.createBuffer(1, 1, 22050);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.connect(ctx.destination);
      src.start(0);
      await ctx.resume();

      (window as any).__tts_ctx__ = ctx;
      (window as any).__tts_global_unlocked__ = true;
      console.info("[tts] ✅ global AudioContext unlocked");

      // 移除监听器，避免重复触发
      ["click", "keydown", "touchstart"].forEach((ev) =>
        document.removeEventListener(ev, createAndUnlock)
      );
    } catch (err) {
      console.warn("[tts] ⚠️ Audio unlock failed:", err);
    }
  };

  ["click", "keydown", "touchstart"].forEach((ev) =>
    document.addEventListener(ev, createAndUnlock, { once: true })
  );
}
