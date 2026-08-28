"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { ROLE_HOME } from "@/lib/config";
import { Loading } from "@/components/ui";

export default function Home() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (user.force_password_change) {
      router.replace("/change-password");
    } else {
      router.replace(ROLE_HOME[user.role] || "/ask");
    }
  }, [user, loading, router]);

  return <Loading label="Starting KnowledgeDesk…" />;
}
