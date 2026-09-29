import type { Metadata } from "next";

import { DataCollectorForm } from "@/components/experiments/DataCollectorForm";

export const metadata: Metadata = { title: "New run · Data Collector" };

export default function NewRunPage() {
  return <DataCollectorForm />;
}
