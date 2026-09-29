import type { Metadata } from "next";

import { RunsTable } from "@/components/experiments/RunsTable";

export const metadata: Metadata = { title: "Data Collector" };

export default function DataCollectorRunsPage() {
  return <RunsTable />;
}
