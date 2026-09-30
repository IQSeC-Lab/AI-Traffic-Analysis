import { notFound } from "next/navigation";

import { ExperimentTabs } from "@/components/experiments/ExperimentTabs";
import { ButtonLink, PageHeader } from "@/components/ui";
import { availableExperiment, experimentHref } from "@/lib/experiments";

export default async function ExperimentLayout({ children, params }: LayoutProps<"/experiments/[experiment]">) {
  const experiment = availableExperiment((await params).experiment);
  if (!experiment) notFound();
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
