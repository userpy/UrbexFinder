import { SharedRouteView } from "@/views/routes/shared";

export default async function SharedRoutePage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string | string[] }>;
}) {
  const { token } = await searchParams;
  return <SharedRouteView token={typeof token === "string" ? token : ""} />;
}
