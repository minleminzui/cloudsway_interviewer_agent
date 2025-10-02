import { create } from 'zustand';

type TranscriptEntry = {
  speaker: 'agent' | 'user';
  text: string;
};

type OutlineSection = {
  stage: string;
  questions: string[];
};

type SessionState = {
  sessionId: string;
  topic: string;
  outline: OutlineSection[];
  transcript: TranscriptEntry[];
  pendingQuestion: string;
  stage: string;
  notes: { category: string; content: string; requiresClarification: boolean }[];
  setSession: (payload: { sessionId: string; topic: string }) => void;
  setOutline: (sections: OutlineSection[]) => void;
  addTranscript: (entry: TranscriptEntry) => void;
  setPendingQuestion: (question: string) => void;
  setStage: (stage: string) => void;
  updateNotes: (notes: SessionState['notes']) => void;
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
  setSession: ({ sessionId, topic }) => set(() => ({ sessionId, topic })),
  setOutline: (sections) => set(() => ({ outline: sections })),
  addTranscript: (entry) => set((state) => ({ transcript: [...state.transcript, entry] })),
  setPendingQuestion: (question) => set(() => ({ pendingQuestion: question })),
  setStage: (stage) => set(() => ({ stage })),
  updateNotes: (notes) => set(() => ({ notes })),
  reset: () =>
    set(() => ({
      sessionId: '0',
      topic: '自动采访演示',
      outline: [],
      transcript: [],
      pendingQuestion: '',
      stage: 'Opening',
      notes: []
    }))
}));
