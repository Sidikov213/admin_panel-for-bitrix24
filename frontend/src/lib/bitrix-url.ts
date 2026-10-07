export function bitrixDealUrl(bitrixId: number): string | null {
  const portal = process.env.NEXT_PUBLIC_BITRIX_PORTAL_URL?.replace(/\/$/, "");
  if (!portal) return null;
  return `${portal}/crm/deal/details/${bitrixId}/`;
}
