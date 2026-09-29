import type { Metadata } from "next";

import { RunPage } from "@/components/experiments/RunPage";

export const metadata: Metadata = { title: "Run · Data Collector" };

export default async function DataCollectorRunPage({
  params,
  searchParams,
}: PageProps<"/experiments/data-collector/runs/[id]">) {
  const { id } = await params;
  const { tab } = await searchParams;
  return <RunPage id={id} initialTab={tab === "monitor" || tab === "results" ? tab : undefined} />;
}
