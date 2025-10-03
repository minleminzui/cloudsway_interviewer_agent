import { create } from 'zustand';

type TranscriptEntry = {
  speaker: 'agent' | 'user';
  text: string;
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

type SessionState = {
  sessionId: string;
  topic: string;
  outline: OutlineSection[];
  transcript: TranscriptEntry[];
  pendingQuestion: string;
  stage: string;
  notes: NoteEntry[];
  ttsReady: boolean;
  setSession: (payload: { sessionId: string; topic: string }) => void;
  setOutline: (sections: OutlineSection[]) => void;
  addTranscript: (entry: TranscriptEntry) => void;
  setPendingQuestion: (question: string) => void;
  setStage: (stage: string) => void;
  updateNotes: (notes: NoteEntry[]) => void;
  setTtsReady: (ready: boolean) => void;
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
  setSession: ({ sessionId, topic }) => set(() => ({ sessionId, topic })),
  setOutline: (sections) => set(() => ({ outline: sections })),
  addTranscript: (entry) => set((state) => ({ transcript: [...state.transcript, entry] })),
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
  reset: () =>
    set(() => ({
      sessionId: '0',
      topic: '自动采访演示',
      outline: [],
      transcript: [],
      pendingQuestion: '',
      stage: 'Opening',
      notes: [],
      ttsReady: false
    }))
}));
