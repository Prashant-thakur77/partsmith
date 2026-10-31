"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Boxes, Link2, RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, PageHeader } from "@/components/layout/page";
import { PrintItPanel } from "@/components/product/print-it-panel";
import { ProgramPanel } from "@/components/product/program-panel";
import { TemplateAckNotice, TemplateExport } from "@/components/product/template-export";
import { useTemplateBake } from "@/components/product/use-template-bake";
import { KnobPanel } from "@/components/registry/knob-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "@/components/ui/toast";
import { CadViewer } from "@/components/viewer/cad-viewer";
import { artifactUrl } from "@/lib/api";
import { PRODUCT, productApi, type TemplateCard } from "@/lib/api-product";
import { useCapabilities } from "@/lib/capabilities";
import { downloadName } from "@/lib/download-name";
import { useDebounced } from "@/lib/hooks";
import { activePreset, applyPreset, changedValues, playgroundQuery, valuesFromQuery } from "@/lib/playground";
import { cn } from "@/lib/utils";

function Gallery({ cards, onPick }: { cards: TemplateCard[]; onPick: (name: string, preset?: Record<string, number>) => void }) {
  return (
    <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-label="Example parts">
      {cards.map((c) => (
        <li key={c.name} className="group flex flex-col overflow-hidden rounded-xl border border-border bg-surface transition-colors hover:border-border-strong">
          <button type="button" onClick={() => onPick(c.name)} className="flex flex-1 flex-col text-left">
            <div className="aspect-[4/3] border-b border-border bg-surface-2">
              {/* eslint-disable-next-line @next/next/no-img-element -- API-rendered PNG, sized by the card */}
              <img
                src={artifactUrl(c.thumbnail_url)}
                srcSet={`${artifactUrl(c.thumbnail_url)} 1x, ${artifactUrl(c.thumbnail_2x_url)} 2x`}
                alt=""
                loading="lazy"
                width={640}
                height={480}
                className="size-full object-contain p-2 transition-transform group-hover:scale-[1.02]"
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5 p-4">
              <div className="flex items-center justify-between gap-2">
                <h2 id={`tpl-${c.name}`} className="text-[15px] font-semibold tracking-tight">
                  {c.title}
                </h2>
                <Badge tone="neutral" className="font-mono tnum">
                  {c.params.length} knobs
                </Badge>
              </div>
              <p id={`tpl-${c.name}-d`} className="line-clamp-2 text-[13px] leading-5 text-muted">
                {c.summary}
              </p>
            </div>
          </button>
          {c.presets.length ? (
            <div className="flex flex-wrap gap-1.5 px-4 pb-4">
              {c.presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => onPick(c.name, p.values)}
                  className="rounded-full border border-border px-2.5 py-0.5 text-[12px] text-muted transition-colors hover:border-border-strong hover:text-fg"
                  title={p.note}
                >
                  {p.title}
                </button>
              ))}
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function Workbench({ card, initial, onBack }: { card: TemplateCard; initial: Record<string, number>; onBack: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const [values, setValues] = React.useState<Record<string, number>>(initial);
  const [ack, setAck] = React.useState(false);
  const detail = useQuery({ queryKey: ["template", card.name], queryFn: () => productApi.template(card.name), staleTime: Infinity });
  const bake = useTemplateBake(card.name, values);
  const preset = activePreset(card.params, values, card.presets);
  const changed = Object.keys(changedValues(card.params, values)).length > 0;

  // Shareable URL: the template and the changed knobs live in the query string.
  const dv = useDebounced(values, 400);
  React.useEffect(() => {
    const next = `${pathname}?${playgroundQuery(card.name, card.params, dv)}`;
    if (next !== `${window.location.pathname}${window.location.search}`) router.replace(next, { scroll: false });
  }, [dv, card, pathname, router]);

  const share = async () => {
    const url = window.location.href;
    try {
      await navigator.clipboard.writeText(url);
      toast("Link copied", { description: "It opens this part at these knob values.", tone: "ok" });
    } catch {
      toast("Copy this link", { description: url });
    }
  };
  const bakeData = bake.data;
  const reason = bakeData?.ship?.reason ?? "";
  const params = bakeData?.params ?? values;

  return (
    <Container className="space-y-6 py-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="space-y-1.5">
          <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-[12px] text-muted hover:text-fg">
            <ArrowLeft className="size-3.5" aria-hidden /> All examples
          </button>
          <h1 className="text-[24px] leading-tight font-semibold tracking-[-0.025em] sm:text-[28px]">{card.title}</h1>
          <p className="max-w-2xl text-[14px] leading-6 text-muted">{card.summary}</p>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="accent">template · {card.params.length} knobs</Badge>
            <Badge tone="warn">not checked against a real part</Badge>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setValues(Object.fromEntries(card.params.map((p) => [p.name, p.default])))} disabled={!changed}>
            <RotateCcw aria-hidden /> Reset
          </Button>
          <Button variant="outline" size="sm" onClick={() => void share()}>
            <Link2 aria-hidden /> Share link
          </Button>
        </div>
      </div>

      {card.presets.length ? (
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Presets">
          <span className="text-[12px] font-medium text-subtle">Presets</span>
          {card.presets.map((p) => (
            <Button key={p.id} size="sm" variant={preset?.id === p.id ? "solid" : "outline"} aria-pressed={preset?.id === p.id} title={p.note} onClick={() => setValues(applyPreset(card.params, p))}>
              {p.title}
            </Button>
          ))}
        </div>
      ) : null}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <div className="overflow-hidden rounded-xl border border-border bg-surface">
            <CadViewer
              viewUrl={bakeData?.artifacts.view}
              poster={artifactUrl(card.thumbnail_url)}
              poster2x={artifactUrl(card.thumbnail_2x_url)}
              busy={bake.pending}
              className="h-[340px] sm:h-[460px]"
              label={`3D model of ${card.title}`}
              emptyText={bake.isError ? "Bake failed." : "Baking…"}
            />
          </div>
          <section aria-labelledby="program-title" className="space-y-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 id="program-title" className="text-[15px] font-semibold tracking-tight">
                This is the program
              </h2>
              <p className="text-[12.5px] text-muted">Every knob is one line in PARAMS. Highlighted lines are the values you changed.</p>
            </div>
            {detail.data ? (
              <ProgramPanel code={detail.data.code} values={params} title={`${card.name}.py`} />
            ) : detail.isError ? (
              <ErrorState error={detail.error} compact what="the program" />
            ) : (
              <Skeleton className="h-64" />
            )}
          </section>
        </div>
        <div className="space-y-5">
          <Card>
            <CardContent className="pt-4">
              <KnobPanel params={card.params} values={values} onChange={setValues} bake={bakeData} pending={bake.pending} error={bake.error} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle as="h2">Export at these values</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {reason ? <TemplateAckNotice ack={ack} onAck={setAck} reason={reason} /> : null}
              <TemplateExport template={card.name} values={params} ack={ack && !!reason} />
            </CardContent>
          </Card>
          <PrintItPanel
            plan={bakeData?.print_plan}
            title={card.title}
            stlUrl={productApi.templateDownloadUrl(card.name, params, "stl")}
            threemfUrl={productApi.templateDownloadUrl(card.name, params, "3mf")}
            couponUrl={card.coupon ? productApi.templateCouponUrl(card.name, changedValues(card.params, params)) : null}
            family={card.family}
            fileNames={{
              stl: downloadName(card.name, ".stl", params, Object.fromEntries(card.params.map((p) => [p.name, p.default])), card.params.map((p) => p.name)),
              threemf: downloadName(card.name, ".3mf", params, Object.fromEntries(card.params.map((p) => [p.name, p.default])), card.params.map((p) => p.name)),
            }}
            disabled={!ack || !reason}
            note={!ack ? "Tick the box above to unlock the files." : null}
          />
          <p className="text-[12.5px] text-muted">
            Have the broken part?{" "}
            <Link href="/fix" className="font-medium text-accent-text hover:underline">
              Photograph it
            </Link>{" "}
            and PartSmith measures it and checks the model against the photo.
          </p>
        </div>
      </div>
    </Container>
  );
}

export function PlaygroundClient() {
  const caps = useCapabilities();
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const name = sp.get("t");
  const list = useQuery({ queryKey: ["templates"], queryFn: productApi.templates, staleTime: 5 * 60_000, enabled: !caps.ready || caps.has("get", PRODUCT.templates) });
  const card = list.data?.find((c) => c.name === name) ?? null;
  // Seeded once per template from the URL; later URL updates come from the knobs themselves.
  const initial = React.useMemo(() => (card ? valuesFromQuery(card.params, new URLSearchParams(sp.toString())) : null), [card]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (n: string, preset?: Record<string, number>) => {
    const c = list.data?.find((x) => x.name === n);
    const qs = c ? playgroundQuery(n, c.params, preset ? applyPreset(c.params, { values: preset }) : {}) : `t=${encodeURIComponent(n)}`;
    router.push(`${pathname}?${qs}`, { scroll: true });
  };

  if (caps.ready && !caps.has("get", PRODUCT.templates)) {
    return (
      <Container className="py-16">
        <EmptyState icon={Boxes} title="The playground is not on this server yet">
          This PartSmith API has no template routes. Browse the <Link href="/parts" className="text-accent-text hover:underline">registry</Link> instead: every part there has knobs too.
        </EmptyState>
      </Container>
    );
  }
  if (list.isError) {
    return (
      <Container className="py-16">
        <ErrorState error={list.error} what="the examples" onRetry={() => void list.refetch()} />
      </Container>
    );
  }
  if (name && card && initial) return <Workbench key={card.name} card={card} initial={initial} onBack={() => router.push(pathname)} />;
  if (name && list.isSuccess && !card) {
    return (
      <Container className="py-16">
        <EmptyState icon={Boxes} title={`No example called “${name}”`} action={<Button asChild variant="outline" size="sm"><Link href="/playground">All examples</Link></Button>}>
          Pick one of the family templates instead.
        </EmptyState>
      </Container>
    );
  }
  return (
    <>
      <PageHeader
        eyebrow="Playground"
        title="Every part is a program with knobs"
        description="Pick an example. Drag a knob and the part is rebuilt from its CadQuery program in a sandbox; the program below the model shows the same values. Download it at your values, or share the link."
        actions={
          <Button asChild variant="outline">
            <Link href="/describe">
              <Sparkles aria-hidden /> Describe a part instead
            </Link>
          </Button>
        }
      />
      <Container className={cn("py-8", name && "min-h-[60vh]")}>
        {list.isPending || (name && !list.isSuccess) ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="h-72" />
            ))}
          </div>
        ) : (
          <Gallery cards={list.data ?? []} onPick={pick} />
        )}
      </Container>
    </>
  );
}
