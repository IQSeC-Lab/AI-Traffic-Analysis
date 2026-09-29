"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  FolderPlus,
  Lock,
  MessagesSquare,
  Pencil,
  Plus,
  Search,
  Tags,
  Trash2,
  UserRound,
} from "lucide-react";

import { api, type Prompt, type PromptLibrary } from "@/lib/api";
import { Alert, EmptyState, Loading, PageHeader, StatTile, buttonClass, inputClass } from "@/components/ui";
import { useConfirm } from "@/components/ConfirmDialog";
import { PromptDialog } from "./PromptDialog";

type DialogState = { prompt?: Prompt; category?: string } | null;

export function PromptLibraryView() {
  const [library, setLibrary] = useState<PromptLibrary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  // Categories start collapsed; searching or filtering opens the ones that match.
  const [openCategories, setOpenCategories] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<DialogState>(null);
  const [confirm, confirmDialog] = useConfirm();

  const refresh = useCallback(() => {
    api<PromptLibrary>("/prompts")
      .then(setLibrary)
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(refresh, [refresh]);

  const groups = useMemo(() => {
    if (!library) return [];
    const q = query.trim().toLowerCase();
    return library.categories
      .filter((c) => !filter || c.name === filter)
      .map((c) => ({
        ...c,
        prompts: library.prompts.filter(
          (p) =>
            p.category === c.name &&
            (!q || p.text.toLowerCase().includes(q) || `#${p.number}` === q || String(p.number) === q),
        ),
      }))
      .filter((g) => g.prompts.length > 0);
  }, [library, query, filter]);

  async function remove(prompt: Prompt) {
    const ok = await confirm({
      title: `Delete prompt #${prompt.number}?`,
      body: "It is removed from the library. Past runs keep their own copy, so their results are unaffected.",
      confirmLabel: "Delete prompt",
      danger: true,
    });
    if (!ok) return;
    try {
      await api(`/prompts/${prompt.number}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function toggle(number: number) {
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(number)) next.delete(number);
      else next.add(number);
      return next;
    });
  }

  const isOpen = (name: string) => openCategories.has(name) || query.trim() !== "" || filter === name;
  const allOpen = groups.length > 0 && groups.every((g) => isOpen(g.name));

  function toggleCategory(name: string) {
    setOpenCategories((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const custom = library?.prompts.filter((p) => !p.builtin).length ?? 0;
  const customCategories = library?.categories.filter((c) => !c.builtin).length ?? 0;

  return (
    <>
      <PageHeader
        title="Prompts"
        description="The prompts experiments send to the model. Add your own and group them in your own categories."
        icon={MessagesSquare}
        actions={
          <button type="button" onClick={() => setDialog({})} className={buttonClass()}>
            <Plus className="h-4 w-4" /> New prompt
          </button>
        }
      />

      {error && (
        <div className="mb-6">
          <Alert>{error}</Alert>
        </div>
      )}
      {!library && !error && <Loading />}

      {library && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Prompts" value={library.prompts.length} icon={MessagesSquare} />
            <StatTile
              label="Yours"
              value={custom}
              hint={`${library.prompts.length - custom} built in`}
              icon={UserRound}
            />
            <StatTile
              label="Categories"
              value={library.categories.length}
              hint={`${customCategories} of yours`}
              icon={Tags}
            />
            <button
              type="button"
              onClick={() => setDialog({})}
              className="flex flex-col items-start justify-between rounded-2xl border border-dashed border-hairline p-4 text-left transition-colors hover:border-accent hover:bg-accent-wash/40"
            >
              <FolderPlus className="h-5 w-5 text-accent" strokeWidth={1.75} />
              <span>
                <span className="block text-sm font-medium">Add a prompt</span>
                <span className="block text-xs text-ink-3">In any category, new or existing</span>
              </span>
            </button>
          </div>

          <div className="flex flex-col gap-3 rounded-2xl border border-hairline bg-surface p-3 shadow-[0_1px_2px_rgba(0,0,0,0.04)] md:flex-row md:items-center">
            <div className="relative md:w-72">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-ink-3" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search prompts…"
                className={`${inputClass} pl-9`}
              />
            </div>
            <div className="flex flex-wrap gap-1.5">
              {[
                {
                  name: null as string | null,
                  count: library.prompts.length,
                  builtin: true,
                },
                ...library.categories,
              ].map((c) => (
                <button
                  key={c.name ?? "all"}
                  type="button"
                  onClick={() => setFilter(c.name)}
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors ${
                    filter === c.name
                      ? "bg-accent-strong font-medium text-white"
                      : "bg-surface-2 text-ink-2 hover:text-ink"
                  }`}
                >
                  {c.name ?? "All"}
                  <span className={filter === c.name ? "text-white/70" : "text-ink-3"}>{c.count}</span>
                </button>
              ))}
            </div>
            {groups.length > 1 && !query.trim() && (
              <button
                type="button"
                onClick={() => setOpenCategories(allOpen ? new Set() : new Set(groups.map((g) => g.name)))}
                className={`${buttonClass("ghost", "sm")} shrink-0 md:ml-auto`}
              >
                {allOpen ? <ChevronsDownUp className="h-3.5 w-3.5" /> : <ChevronsUpDown className="h-3.5 w-3.5" />}
                {allOpen ? "Collapse all" : "Expand all"}
              </button>
            )}
          </div>

          {groups.length === 0 && (
            <EmptyState icon={Search} title="No prompts match">
              Try another search or category.
            </EmptyState>
          )}

          {groups.map((g) => {
            const open = isOpen(g.name);
            const yours = g.prompts.filter((p) => !p.builtin).length;
            return (
              <section
                key={g.name}
                className="overflow-hidden rounded-2xl border border-hairline bg-surface shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
              >
                <div
                  className={`flex items-center justify-between gap-3 px-3 py-2 ${open ? "border-b border-hairline" : ""}`}
                >
                  <button
                    type="button"
                    onClick={() => toggleCategory(g.name)}
                    aria-expanded={open}
                    className="flex min-w-0 flex-1 items-center gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-surface-2/60"
                  >
                    <ChevronRight
                      className={`h-4 w-4 shrink-0 text-ink-3 transition-transform ${open ? "rotate-90" : ""}`}
                    />
                    <h2 className="truncate text-sm font-semibold">{g.name}</h2>
                    <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-ink-3 tabular-nums">
                      {query.trim() ? `${g.prompts.length} of ${g.count}` : g.count}
                    </span>
                    <span className="hidden items-center gap-1 text-[11px] text-ink-3 sm:inline-flex">
                      {g.builtin ? <Lock className="h-3 w-3" /> : <UserRound className="h-3 w-3" />}
                      {g.builtin ? "Built-in category" : "Your category"}
                      {g.builtin && yours > 0 && ` · ${yours} yours`}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setDialog({ category: g.name })}
                    className={buttonClass("ghost", "sm")}
                  >
                    <Plus className="h-3.5 w-3.5" /> Add here
                  </button>
                </div>
                {open && (
                  <ul className="divide-y divide-[var(--hairline)]">
                    {g.prompts.map((p) => {
                      const open = expanded.has(p.number);
                      return (
                        <li key={p.number} className="group flex items-start gap-4 px-5 py-3">
                          <span
                            className={`mt-0.5 inline-flex h-6 min-w-9 shrink-0 items-center justify-center rounded-md px-1.5 text-xs font-medium tabular-nums ${
                              p.builtin ? "bg-surface-2 text-ink-2" : "bg-accent-wash text-accent"
                            }`}
                          >
                            #{p.number}
                          </span>
                          <button type="button" onClick={() => toggle(p.number)} className="min-w-0 flex-1 text-left">
                            <p
                              className={`text-sm leading-relaxed text-ink-2 ${open ? "whitespace-pre-wrap" : "line-clamp-2"}`}
                            >
                              {p.text}
                            </p>
                            {!p.builtin && (
                              <span className="mt-1 inline-block text-[11px] text-ink-3">Added by you</span>
                            )}
                          </button>
                          {!p.builtin && (
                            <div className="flex shrink-0 gap-1 opacity-100 transition-opacity md:opacity-0 md:group-hover:opacity-100">
                              <button
                                type="button"
                                onClick={() => setDialog({ prompt: p })}
                                className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink"
                                aria-label={`Edit prompt ${p.number}`}
                              >
                                <Pencil className="h-4 w-4" />
                              </button>
                              <button
                                type="button"
                                onClick={() => remove(p)}
                                className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-critical-text"
                                aria-label={`Delete prompt ${p.number}`}
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            );
          })}
        </div>
      )}

      {dialog && library && (
        <PromptDialog
          prompt={dialog.prompt}
          defaultCategory={dialog.category}
          categories={library.categories.map((c) => c.name)}
          onSaved={refresh}
          onClose={() => setDialog(null)}
        />
      )}
      {confirmDialog}
    </>
  );
}
