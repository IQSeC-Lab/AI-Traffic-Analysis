import type { Metadata } from "next";
import { Settings } from "lucide-react";

import { AppearanceCard } from "@/components/settings/AppearanceCard";
import { HfTokenCard } from "@/components/settings/HfTokenCard";
import { ModelDownloader } from "@/components/settings/ModelDownloader";
import { StorageCard } from "@/components/settings/StorageCard";
import { PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Appearance, storage, credentials and the models every experiment can use." icon={Settings} />
      <div className="space-y-6">
        <AppearanceCard />
        <StorageCard />
        <HfTokenCard />
        <ModelDownloader />
      </div>
    </>
  );
}
