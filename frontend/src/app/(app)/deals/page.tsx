import { Suspense } from "react";
import { DealsView } from "@/components/deals/deals-view";
import { PageLoading } from "@/components/common/page-states";

export default function DealsPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <DealsView />
    </Suspense>
  );
}
