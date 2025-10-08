// src/hooks/useAudioUnlock.ts
import { useEffect } from "react";

/**
 * ✅ 全局 Hook：在用户第一次交互后自动解锁浏览器音频播放权限
 * Chrome / Safari 都会阻止 autoplay，必须在交互后调用 play()
 */
export function useAudioUnlock() {
  useEffect(() => {
    let unlocked = false;

    const unlock = () => {
      if (unlocked) return;
      unlocked = true;

      try {
        // 创建一个 1ms 的静音音频，播放一次即可解锁 AudioContext
        const audio = new Audio();
        (audio as any).playsInline = true;
        audio.muted = true;
        audio.src = "data:audio/mp3;base64,//uQxAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCA...";
        void audio.play().catch(() => {});
        console.info("[🔊] Audio context unlocked by user interaction");
      } catch (err) {
        console.warn("[🔇] Failed to unlock audio context", err);
      }

      document.removeEventListener("click", unlock);
      document.removeEventListener("keydown", unlock);
      document.removeEventListener("touchstart", unlock);
    };

    document.addEventListener("click", unlock, { once: true });
    document.addEventListener("keydown", unlock, { once: true });
    document.addEventListener("touchstart", unlock, { once: true });

    return () => {
      document.removeEventListener("click", unlock);
      document.removeEventListener("keydown", unlock);
      document.removeEventListener("touchstart", unlock);
    };
  }, []);
}
