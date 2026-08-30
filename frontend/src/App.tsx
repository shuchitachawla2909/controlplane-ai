import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import LiveMonitor from "./pages/LiveMonitor";
import TraceDetail from "./pages/TraceDetail";
import ReviewQueue from "./pages/ReviewQueue";
import Policies from "./pages/Policies";
import LearningLoop from "./pages/LearningLoop";
import Benchmark from "./pages/Benchmark";

const NAV = [
  ["/", "Overview"],
  ["/monitor", "Live Monitor"],
  ["/review", "Review Queue"],
  ["/policies", "Policies"],
  ["/learning", "Learning Loop"],
  ["/benchmark", "Performance Benchmark"],
];

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <h1>ControlPlane.ai</h1>
          <p>Adaptive Runtime AI Oversight</p>
        </div>
        <nav className="nav">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="foot">
          Prototype · synthetic data<br />
          Observe · investigate selectively<br />
          act proportionally · learn
        </div>
      </aside>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/monitor" element={<LiveMonitor />} />
          <Route path="/trace/:id" element={<TraceDetail />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/policies" element={<Policies />} />
          <Route path="/learning" element={<LearningLoop />} />
          <Route path="/benchmark" element={<Benchmark />} />
        </Routes>
      </main>
    </div>
  );
}
