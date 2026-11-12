// Control page (control.html): the phone remote laid out for the laptop screen and a mouse.
// Same screens and commands as a phone; it is one more singer.

import { createRoot } from "react-dom/client";
import { App } from "../phone/App";
import "../phone/phone.css";

const root = document.getElementById("root");
if (root === null) throw new Error("control.html is missing #root");
createRoot(root).render(<App desk />);
