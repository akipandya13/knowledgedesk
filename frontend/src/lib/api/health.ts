"use client";

import { apiFetch } from "./client";
import type { HealthStatus } from "@/lib/types";

export function getHealth() {
  return apiFetch<HealthStatus>("/health");
}

export function seedDemo() {
  return apiFetch<{ queued: number; note?: string }>("/demo/seed", { method: "POST" });
}
