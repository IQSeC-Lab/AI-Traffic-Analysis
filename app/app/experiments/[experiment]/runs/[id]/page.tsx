import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { RunPage } from "@/components/experiments/RunPage";
import { availableExperiment, experimentName } from "@/lib/experiments";

export async function generateMetadata({ params }: PageProps<"/experiments/[experiment]/runs/[id]">): Promise<Metadata> {
  return { title: `Run · ${experimentName((await params).experiment)}` };
}

export default async function ExperimentRunPage({
  params,
  searchParams,
}: PageProps<"/experiments/[experiment]/runs/[id]">) {
  const { experiment, id } = await params;
  const { tab } = await searchParams;
  if (!availableExperiment(experiment)) notFound();
  return <RunPage experiment={experiment} id={id} initialTab={tab === "monitor" || tab === "results" ? tab : undefined} />;
}
