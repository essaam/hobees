import { Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Storage } from './pages/Storage';
import { Studio } from './pages/Studio';
import { TraceExplorer } from './pages/TraceExplorer';
import { Traces } from './pages/Traces';
import { Workbench } from './pages/Workbench';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Workbench />} />
        <Route path="/traces" element={<Traces />} />
        <Route path="/traces/:threadId" element={<TraceExplorer />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/storage" element={<Storage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
