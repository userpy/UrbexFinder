import { Explorer } from "@/views/explorer";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ place?: string | string[] }>;
}) {
  const { place } = await searchParams;
  const placeId = Array.isArray(place) ? place[0] : place;
  const initialPlaceId =
    placeId && /^\d+$/.test(placeId) ? placeId : undefined;

  return <Explorer initialPlaceId={initialPlaceId} />;
}
