import { create } from 'zustand';

export type TranscriptEntry = {
  speaker: 'user' | 'agent';
  text: string;
  audioUrl?: string;     // 新增
  durationMs?: number;   // 可选：展示时长
};

type State = {
  sessionId: string;
  topic: string;
  transcript: TranscriptEntry[];
  micStatus: 'idle' | 'starting' | 'recording' | 'error';
  micError: string | null;

  addTranscript: (entry: TranscriptEntry) => void;
  setMicStatus: (s: State['micStatus']) => void;
  setMicError: (e: string | null) => void;

  // 你原先就有的 TTS 相关：
  setTtsFallbackRetry: (fn: (() => void) | null) => void;
};

type OutlineSection = {
  stage: string;
  questions: string[];
};


type NoteEntry = {
  category: string;
  content: string;
  requiresClarification: boolean;
  confidence?: number;
};

type TtsMode = 'stream' | 'fallback' | 'error';

type MicStatus = 'idle' | 'starting' | 'recording' | 'error';

type SessionState = {
  sessionId: string;
  topic: string;
  outline: OutlineSection[];
  transcript: TranscriptEntry[];
  pendingQuestion: string;
  stage: string;
  notes: NoteEntry[];
  ttsReady: boolean;
  ttsMode: TtsMode;
  ttsError: string | null;
  ttsFallbackText: string | null;
  ttsFallbackNeedUserAction: boolean;
  ttsFallbackRetry: (() => void) | null;
  micStatus: MicStatus;
  micError: string | null;
  setSession: (payload: { sessionId: string; topic: string }) => void;
  setOutline: (sections: OutlineSection[]) => void;
  addTranscript: (entry: TranscriptEntry) => void;
  setPendingQuestion: (question: string) => void;
  setStage: (stage: string) => void;
  updateNotes: (notes: NoteEntry[]) => void;
  setTtsReady: (ready: boolean) => void;
  setTtsMode: (mode: TtsMode) => void;
  setTtsError: (error: string | null) => void;
  setTtsFallbackText: (text: string | null) => void;
  setTtsFallbackNeedUserAction: (need: boolean) => void;
  setTtsFallbackRetry: (handler: (() => void) | null) => void;
  setMicStatus: (status: MicStatus) => void;
  setMicError: (error: string | null) => void;
  reset: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  sessionId: '0',
  topic: '自动采访演示',
  outline: [],
  transcript: [],
  pendingQuestion: '',
  stage: 'Opening',
  notes: [],
  ttsReady: false,
  ttsMode: 'stream',
  ttsError: null,
  ttsFallbackText: null,
  ttsFallbackNeedUserAction: false,
  ttsFallbackRetry: null,
  micStatus: 'idle',
  micError: null,
  setSession: ({ sessionId, topic }) => set(() => ({ sessionId, topic })),
  setOutline: (sections) => set(() => ({ outline: sections })),
  addTranscript: (entry: TranscriptEntry) => set((state) => ({ transcript: [...state.transcript, entry] })),
  setPendingQuestion: (question) => set(() => ({ pendingQuestion: question })),
  setStage: (stage) => set(() => ({ stage })),
  updateNotes: (incoming) =>
    set((state) => {
      const map = new Map(state.notes.map((note) => [note.content, note]));
      for (const note of incoming) {
        const existing = map.get(note.content);
        if (existing) {
          existing.requiresClarification = existing.requiresClarification || note.requiresClarification;
          existing.confidence = Math.max(existing.confidence ?? 0, note.confidence ?? 0);
        } else {
          map.set(note.content, { ...note });
        }
      }
      return { notes: Array.from(map.values()) };
    }),
  setTtsReady: (ready) => set(() => ({ ttsReady: ready })),
  setTtsMode: (mode) => set(() => ({ ttsMode: mode })),
  setTtsError: (error) => set(() => ({ ttsError: error })),
  setTtsFallbackText: (text) => set(() => ({ ttsFallbackText: text })),
  setTtsFallbackNeedUserAction: (need) => set(() => ({ ttsFallbackNeedUserAction: need })),
  setTtsFallbackRetry: (handler) => set(() => ({ ttsFallbackRetry: handler })),
  setMicStatus: (status) => set(() => ({ micStatus: status })),
  setMicError: (error) => set(() => ({ micError: error })),
  reset: () =>
    set(() => ({
      sessionId: '0',
      topic: '自动采访演示',
      outline: [],
      transcript: [],
      pendingQuestion: '',
      stage: 'Opening',
      notes: [],
      ttsReady: false,
      ttsMode: 'stream',
      ttsError: null,
      ttsFallbackText: null,
      ttsFallbackNeedUserAction: false,
      ttsFallbackRetry: null,
      micStatus: 'idle',
      micError: null
    }))
}));
