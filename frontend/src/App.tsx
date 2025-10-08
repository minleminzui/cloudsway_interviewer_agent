// frontend/src/App.tsx
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import MainConsole from './pages/MainConsole';
import TtsDemoPage from './pages/TtsDemoPage';

const router = createBrowserRouter([
  { path: '/', element: <MainConsole /> },
  { path: '/tts-demo', element: <TtsDemoPage /> }
]);

export function App() {
  return <RouterProvider router={router} />;
}

export default App;
