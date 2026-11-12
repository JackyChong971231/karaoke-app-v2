import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./phone.css";

const root = document.getElementById("root");
if (root === null) throw new Error("index.html is missing #root");
// No StrictMode: its double render would open a second party socket in development.
createRoot(root).render(<App />);
