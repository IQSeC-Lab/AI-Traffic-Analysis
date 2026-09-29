import type { Metadata } from "next";

import { PromptLibraryView } from "@/components/prompts/PromptLibraryView";

export const metadata: Metadata = { title: "Prompts" };

export default function PromptsPage() {
  return <PromptLibraryView />;
}
