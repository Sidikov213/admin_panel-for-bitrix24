import { Suspense } from "react";
import { StalledView } from "@/components/stalled/stalled-view";
import { PageLoading } from "@/components/common/page-states";

export default function StalledPage() {
  return (
    <Suspense fallback={<PageLoading rows={6} />}>
      <StalledView />
    </Suspense>
  );
}
