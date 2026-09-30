
import { ExperimentTabs } from "@/components/experiments/ExperimentTabs";
import { ButtonLink, PageHeader } from "@/components/ui";
import { EXPERIMENTS, experimentHref } from "@/lib/experiments";

const experiment = EXPERIMENTS.find((e) => e.slug === "data-collector")!;

export default function DataCollectorLayout({ children }: LayoutProps<"/experiments/data-collector">) {
  const base = experimentHref(experiment.slug);
  return (
    <>
      <PageHeader
        title={experiment.name}
        description={experiment.description}
        actions={
          <ButtonLink href={`${base}/new`}>
            New run
          </ButtonLink>
        }
      />
      <ExperimentTabs base={base} />
      {children}
    </>
  );
}
