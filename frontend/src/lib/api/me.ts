"use client";

import { apiFetch } from "./client";
import type { ActivityEntry, ActivityFilter } from "@/lib/types";

/** The caller's own activity trail — sessions, documents their questions
 *  retrieved, admin surfaces they opened. Self-scoped on the server. */
export function getMyActivity(filter: ActivityFilter = {}) {
  const sp = new URLSearchParams();
  sp.set("limit", String(filter.limit ?? 50));
  if (filter.prefix) sp.set("action_prefix", filter.prefix);
  if (filter.category) sp.set("category", filter.category);
  if (filter.since) sp.set("since", filter.since);
  if (filter.until) sp.set("until", filter.until);
  if (filter.before_id) sp.set("before_id", String(filter.before_id));
  return apiFetch<ActivityEntry[]>(`/me/activity?${sp.toString()}`);
}
