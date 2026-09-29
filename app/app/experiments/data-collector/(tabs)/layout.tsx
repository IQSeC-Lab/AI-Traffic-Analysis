import { Plus } from "lucide-react";

import { ExperimentTabs } from "@/components/experiments/ExperimentTabs";
import { ButtonLink, PageHeader } from "@/components/ui";
import { EXPERIMENTS, experimentHref } from "@/lib/experiments";

const experiment = EXPERIMENTS.find((e) => e.slug === "data-collector")!;

export default function DataCollectorLayout({ children }: LayoutProps<"/experiments/data-collector">) {
  const base = experimentHref(experiment.slug);
  return (
    <>
      <PageHeader
        eyebrow="Experiment"
        title={experiment.name}
        description={experiment.description}
        icon={experiment.icon}
        actions={
          <ButtonLink href={`${base}/new`}>
            <Plus className="h-4 w-4" /> New run
          </ButtonLink>
        }
      />
      <ExperimentTabs base={base} />
      {children}
    </>
  );
}
