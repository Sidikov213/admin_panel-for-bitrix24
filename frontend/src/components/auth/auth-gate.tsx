"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/components/providers/auth-provider";
import { PageLoading } from "@/components/common/page-states";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { isLoading, user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !user && pathname !== "/login") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, user, pathname, router]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center p-8">
        <PageLoading rows={2} />
      </div>
    );
  }

  if (!user) return null;

  return <>{children}</>;
}
