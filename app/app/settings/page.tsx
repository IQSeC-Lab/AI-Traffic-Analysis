import type { Metadata } from "next";

import { AppearanceCard } from "@/components/settings/AppearanceCard";
import { HfTokenCard } from "@/components/settings/HfTokenCard";
import { ModelDownloader } from "@/components/settings/ModelDownloader";
import { SamplingCard } from "@/components/settings/SamplingCard";
import { StorageCard } from "@/components/settings/StorageCard";
import { PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Appearance, sampling, storage, credentials and the models every experiment can use." />
      <div className="grid max-w-4xl items-start gap-6 2xl:max-w-none 2xl:grid-cols-2">
        <div className="space-y-6">
          <AppearanceCard />
          <SamplingCard />
          <StorageCard />
          <HfTokenCard />
        </div>
        <ModelDownloader />
      </div>
    </>
  );
}
