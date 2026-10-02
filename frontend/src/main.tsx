import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Fonts ship with the app (no font CDN request), so it works offline next to a local model.
import "@fontsource-variable/red-hat-text";
import "@fontsource-variable/red-hat-display";
import "@fontsource-variable/red-hat-mono";
import "./styles/global.css";

import App from "./App";
import { AppStateProvider } from "./lib/AppState";
import { ServerProvider } from "./lib/server";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ServerProvider>
      <AppStateProvider>
        <App />
      </AppStateProvider>
    </ServerProvider>
  </StrictMode>,
);
