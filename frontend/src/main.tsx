import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Application root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

if ("serviceWorker" in navigator) {
  if (import.meta.env.DEV) {
    navigator.serviceWorker.getRegistrations().then((registrations) => registrations.forEach((registration) => void registration.unregister()));
  } else {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  }
}
