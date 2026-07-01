import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const dashboardDataRoot = path.join(repoRoot, "data", "dashboard");

function localDashboardDataPlugin() {
  const useDashboardData = (server) => {
    server.middlewares.use((request, response, next) => {
      const requestPath = decodeURIComponent((request.url || "").split("?", 1)[0]);
      if (!requestPath.startsWith("/data/dashboard/")) {
        next();
        return;
      }

      const relativePath = requestPath.replace(/^\/data\/dashboard\//, "");
      const target = path.resolve(dashboardDataRoot, relativePath);
      const isInsideDataRoot = target === dashboardDataRoot || target.startsWith(`${dashboardDataRoot}${path.sep}`);
      if (!isInsideDataRoot) {
        response.statusCode = 403;
        response.end("Forbidden");
        return;
      }

      fs.readFile(target, (error, data) => {
        if (error) {
          next();
          return;
        }
        response.setHeader("Content-Type", "application/json; charset=utf-8");
        response.end(data);
      });
    });
  };

  return {
    name: "local-dashboard-data",
    configureServer(server) {
      useDashboardData(server);
    },
    configurePreviewServer(server) {
      useDashboardData(server);
    },
  };
}

export default defineConfig({
  plugins: [react(), localDashboardDataPlugin()],
  server: {
    host: "127.0.0.1",
  },
  preview: {
    host: "127.0.0.1",
  },
});
