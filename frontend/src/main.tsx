import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import "./faro_collector.jsx"

createRoot(document.getElementById("root")!).render(<App />);
