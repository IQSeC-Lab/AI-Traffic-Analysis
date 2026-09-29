"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

import { buttonClass } from "@/components/ui";

type ConfirmOptions = {
  title: string;
  body?: ReactNode;
  confirmLabel: string;
  danger?: boolean;
};

/**
 * `const [confirm, dialog] = useConfirm()` — render `dialog`, then
 * `if (await confirm({...}))` wherever an action needs a yes/no.
 */
export function useConfirm() {
  const [pending, setPending] = useState<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);

  const confirm = useCallback(
    (options: ConfirmOptions) => new Promise<boolean>((resolve) => setPending({ ...options, resolve })),
    [],
  );

  const close = useCallback(
    (ok: boolean) => {
      pending?.resolve(ok);
      setPending(null);
    },
    [pending],
  );

  const dialog = pending ? <ConfirmDialog {...pending} onClose={close} /> : null;
  return [confirm, dialog] as const;
}

function ConfirmDialog({ title, body, confirmLabel, danger, onClose }: ConfirmOptions & { onClose: (ok: boolean) => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="alertdialog" aria-modal aria-labelledby="confirm-title">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={() => onClose(false)} />
      <div className="relative w-full max-w-md rounded-2xl border border-hairline bg-surface p-5 shadow-2xl">
        <div className="flex gap-4">
          {danger && (
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface-2">
              <AlertTriangle className="h-5 w-5" style={{ color: "var(--critical)" }} />
            </div>
          )}
          <div className="min-w-0">
            <h2 id="confirm-title" className="text-base font-semibold">
              {title}
            </h2>
            {body && <div className="mt-1.5 text-sm text-ink-2">{body}</div>}
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={() => onClose(false)} className={buttonClass("ghost")}>
            Keep it
          </button>
          <button type="button" autoFocus onClick={() => onClose(true)} className={buttonClass(danger ? "danger" : "primary")}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
