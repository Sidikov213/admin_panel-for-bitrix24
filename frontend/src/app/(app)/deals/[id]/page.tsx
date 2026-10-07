import { DealDetailView } from "@/components/deals/deal-detail-view";

export default async function DealDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DealDetailView id={Number(id)} />;
}
