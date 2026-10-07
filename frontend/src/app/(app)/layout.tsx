import { AuthProvider } from "@/components/providers/auth-provider";
import { AuthGate } from "@/components/auth/auth-gate";
import { AppShell } from "@/components/layout/app-shell";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <AuthGate>
        <AppShell>{children}</AppShell>
      </AuthGate>
    </AuthProvider>
  );
}
