import type { Metadata } from "next";

import { RunsTable } from "@/components/experiments/RunsTable";
import { experimentName } from "@/lib/experiments";

export async function generateMetadata({ params }: PageProps<"/experiments/[experiment]">): Promise<Metadata> {
  return { title: experimentName((await params).experiment) };
}

export default async function ExperimentRunsPage({ params }: PageProps<"/experiments/[experiment]">) {
  return <RunsTable experiment={(await params).experiment} />;
}
