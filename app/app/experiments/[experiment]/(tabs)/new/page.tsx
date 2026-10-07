import type { Metadata } from "next";

import { AgenticRunForm } from "@/components/experiments/AgenticRunForm";
import { RunForm } from "@/components/experiments/RunForm";
import { experimentName, isAgentic } from "@/lib/experiments";

export async function generateMetadata({ params }: PageProps<"/experiments/[experiment]/new">): Promise<Metadata> {
  return { title: `New run · ${experimentName((await params).experiment)}` };
}

export default async function NewRunPage({ params }: PageProps<"/experiments/[experiment]/new">) {
  const { experiment } = await params;
  return isAgentic(experiment) ? <AgenticRunForm experiment={experiment} /> : <RunForm experiment={experiment} />;
}
