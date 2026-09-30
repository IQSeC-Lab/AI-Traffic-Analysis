import type { Metadata } from "next";

import { RunForm } from "@/components/experiments/RunForm";
import { experimentName } from "@/lib/experiments";

export async function generateMetadata({ params }: PageProps<"/experiments/[experiment]/new">): Promise<Metadata> {
  return { title: `New run · ${experimentName((await params).experiment)}` };
}

export default async function NewRunPage({ params }: PageProps<"/experiments/[experiment]/new">) {
  return <RunForm experiment={(await params).experiment} />;
}
