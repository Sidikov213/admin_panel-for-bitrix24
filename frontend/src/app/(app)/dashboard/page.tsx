import { Suspense } from "react";
import { PageLoading } from "@/components/common/page-states";
import { DashboardView } from "@/components/dashboard/dashboard-view";

export default function DashboardPage() {
  // Filters are read from the URL (useSearchParams) — needs a Suspense boundary
  return (
    <Suspense fallback={<PageLoading rows={6} />}>
      <DashboardView />
    </Suspense>
  );
}
