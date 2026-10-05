import { Button } from "@/components/layout/ui/button";
import { useEffect, useRef, useState } from "react";
import { SidePanel } from "@/components/layout/SidePanel";
import { Skeleton } from "@/components/layout/Skeleton";
import { fetchPersonas, regeneratePersonas, updatePersona, type Persona, type PersonaBundle } from "@/lib/intakeT2Api";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { PanelSaveButton } from "./shared/PanelSaveButton";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PersonaBundle };

/** 顧客原話籤頂部的人物誌（T2 條文 4.1–4.3）；人物誌失敗不影響下方原話清單。 */
export function PersonaSection({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [starting, setStarting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Persona | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  function applyBundle(data: PersonaBundle) {
    setState({ status: "ready", data });
    if (data.generation.status !== "running") stopPolling();
  }

  function load() {
    setState((previous) => previous.status === "ready" ? previous : { status: "loading" });
    fetchPersonas(brandId)
      .then((data) => {
        applyBundle(data);
        if (data.generation.status === "running") startPolling();
      })
      .catch((err: unknown) => {
        setState({ status: "error", message: err instanceof Error ? err.message : "人物誌現在讀不到，請再試一次。" });
      });
  }

  function startPolling() {
    if (pollRef.current) return;
    pollRef.current = setInterval(() => {
      fetchPersonas(brandId)
        .then((data) => applyBundle(data))
        .catch(() => undefined);
    }, 1000);
  }

  useEffect(() => {
    load();
    return stopPolling;
  }, [brandId]);

  async function generate() {
    setStarting(true);
    setActionError(null);
    try {
      const generation = await regeneratePersonas(brandId);
      setState((previous) => previous.status === "ready" ? { status: "ready", data: { ...previous.data, generation } } : previous);
      if (generation.status === "running") startPolling();
      else load();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "人物誌暫時產生不了，請再試一次。");
    } finally {
      setStarting(false);
    }
  }

  if (state.status === "loading") {
    return <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]"><Skeleton className="h-6 w-32" /><Skeleton className="h-24" /></section>;
  }
  if (state.status === "error") {
    return (
      <section className="flex flex-col gap-3 rounded-lg border border-danger/40 bg-danger/5 p-5 text-sm">
        <p className="font-medium text-danger">人物誌暫時讀不到</p>
        <p className="text-muted-foreground">{state.message}</p>
        <div><button type="button" onClick={load} className="rounded-md border border-border px-3 py-1.5 font-medium text-foreground hover:border-primary hover:text-primary">重新讀取</button></div>
      </section>
    );
  }

  const { data } = state;
  const running = data.generation.status === "running";
  const failed = data.generation.status === "failed";
  const empty = data.personas.length === 0;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-lg text-foreground">👥 典型客人</h2>
          <p className="text-sm text-muted-foreground">依已確認資料和顧客原話整理。</p>
        </div>
        <Button variant="outline" size="sm" type="button" busy={starting || running} onClick={() => {
          if (empty || window.confirm("會重新產生並取代現有人物誌（含你手動改過的）")) void generate();
        }} className="rounded-md border border-primary px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50">
          {starting ? "開始整理中…" : running ? "正在整理…" : empty ? "產生人物誌" : "🔄 重新產生"}
        </Button>
      </div>

      {running && <p role="status" aria-live="polite" className="rounded-md border border-dashed border-border bg-muted/40 p-3 text-sm text-muted-foreground">AI 正在整理典型客人中…好了會通知你，也可以先看下面的顧客原話。</p>}
      {failed && <div className="rounded-md border border-danger/40 bg-danger/5 p-3 text-sm"><p className="font-medium text-danger">人物誌這次沒有整理好</p><p className="mt-1 text-muted-foreground">{data.generation.error ?? "不影響下面的顧客原話，按重新產生可以再試。"}</p></div>}
      {!running && !failed && empty && <p className="rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">還沒有人物誌；建檔完成後會自動產生，也可以現在按產生人物誌。</p>}

      {data.personas.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,460px))] gap-3">
          {data.personas.map((persona) => (
            <article key={persona.id} className="flex flex-col gap-2 rounded-md border border-border p-4 text-sm">
              <div className="flex items-start justify-between gap-3">
                <h3 className="font-medium text-foreground">{persona.title}</h3>
                <Button variant="outline" size="sm" type="button" busy={running} onClick={() => setEditing(persona)} className="rounded-md border border-border px-2 py-1 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50">改</Button>
              </div>
              <p className="text-muted-foreground">什麼時候需要：{persona.when_needed}</p>
              <p className="text-muted-foreground">在意：{persona.care_about}</p>
              <p className="text-muted-foreground">猶豫：{persona.hesitation}</p>
              <p className="text-muted-foreground">去哪找他：{persona.where_to_find}</p>
            </article>
          ))}
        </div>
      )}
      {actionError && <p role="alert" className="text-sm text-danger">{actionError}</p>}
      {editing && <PersonaEditor brandId={brandId} persona={editing} onClose={() => setEditing(null)} onSaved={() => {
        setEditing(null);
        load();
      }} />}
    </section>
  );
}

function PersonaEditor({
  brandId,
  persona,
  onClose,
  onSaved,
}: {
  brandId: string;
  persona: Persona;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(persona.title);
  const [whenNeeded, setWhenNeeded] = useState(persona.when_needed);
  const [careAbout, setCareAbout] = useState(persona.care_about);
  const [hesitation, setHesitation] = useState(persona.hesitation);
  const [whereToFind, setWhereToFind] = useState(persona.where_to_find);
  const form = useFormSubmit(async () => {
    await updatePersona(brandId, persona.id, {
      title, when_needed: whenNeeded, care_about: careAbout, hesitation, where_to_find: whereToFind,
    });
    onSaved();
  });

  const fields = [
    ["這位典型客人怎麼稱呼？", title, setTitle],
    ["通常什麼時候需要？", whenNeeded, setWhenNeeded],
    ["他在意什麼？", careAbout, setCareAbout],
    ["他會猶豫什麼？", hesitation, setHesitation],
    ["可以去哪裡找到他？", whereToFind, setWhereToFind],
  ] as const;
  return (
    <SidePanel ariaLabel="修改典型客人" onClose={onClose}>
      <div className="flex items-start justify-between gap-3 border-b border-border pb-4">
        <h2 className="font-display text-lg text-foreground">修改典型客人</h2>
        <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary">關閉</button>
      </div>
      <form className="flex flex-col gap-4" onSubmit={(event) => {
        event.preventDefault();
        void form.submit();
      }}>
        {fields.map(([label, value, setValue]) => (
          <label key={label} className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">{label}</span>
            <textarea value={value} onChange={(event) => setValue(event.target.value)} required rows={3} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />
          </label>
        ))}
        {form.error && <p role="alert" className="text-sm text-danger">{form.error}</p>}
        <div><PanelSaveButton saving={form.saving} label="儲存修改" /></div>
      </form>
    </SidePanel>
  );
}
