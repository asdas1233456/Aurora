import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "@xyflow/react/dist/style.css";

import { App } from "@/app/app";
import { Providers } from "@/app/providers";
import "@/styles/globals.css";


const container = document.getElementById("root");

if (!container) {
  throw new Error("Missing #root container");
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <Providers>
        <App />
      </Providers>
    </BrowserRouter>
  </StrictMode>,
);
