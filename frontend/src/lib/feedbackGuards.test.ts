/** F47-I02 (feature F47 Contract B) and F51 (Contract H／C scanners): repo-wide guards for "one way to
 * give feedback".
 *
 * 1. A failed response becomes a sentence in one place. A `src/lib/*.ts` file that throws a
 *    「…（狀態碼 N）」 message straight away drops the sentence the server sent (drill-10 V2: the AI
 *    limit and rule-card saves showed 「儲存失敗（狀態碼 400）」 while the server said why). Such a
 *    text may exist only as the fallback handed to `throwIfFailed` / `readJson` /
 *    `errorMessageFromResponse` / `errorMessageFrom` (or a file-local wrapper that passes it on).
 * 2. Copy feedback lives in two components. `navigator.clipboard` outside `CopyIconButton` and
 *    `ads/patterns/CopyField` is a hand-rolled copy that has, every time so far, given no visible
 *    feedback (drill-10 publish step 2, prompts, invite link). Test files may stub it.
 * 3. `envelope` (F51 Contract H): only `lib/http.ts` reads a response (`.json()`, `res.ok`), catches
 *    fetch's `TypeError`, reads `body.error` or calls `errorMessageFrom(Response)(`; no `lib/*Api.ts`
 *    declares its own `Error` class. Drill 11 B8: three different network sentences and 「Failed to fetch」.
 * 4. `message-branch` (F51 Contract C): a component branches on `err.code`／`err.status`／
 *    `err.rejected`, never on message text (`.message ===`, `.message.includes(`, `message === CONST`).
 *
 * Rules 3–4 (and the later F51 rules) are ratchets: comments are blanked before scanning (line numbers
 * kept); a hit in a file no `lib/guards/F51-INN.allow.ts` module lists fails; a listed `(rule, file)`
 * with no hit left fails as stale, naming the issue (that issue deletes its entry, and its module when
 * empty); a legitimate line carries an inline `// <RULE>_OK: <why>` (`{/* … *\/}` in JSX), and an
 * excuse on a line without a hit fails. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const LIB_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = join(LIB_DIR, "..");

/** Calls that take a fallback and read the server's sentence first. `extractError` / `readOrThrow`
 * are file-local wrappers (intakeApi / metaApi) that forward to `errorMessageFromResponse`. */
const ROUTED = /\b(throwIfFailed|readJson|errorMessageFromResponse|errorMessageFrom|extractError|readOrThrow)\(/;

function listFiles(dir: string, recurse: boolean): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (recurse) out.push(...listFiles(full, true));
      continue;
    }
    if (!/\.tsx?$/.test(name) || /\.(test|stories)\.tsx?$/.test(name)) continue;
    out.push(full);
  }
  return out;
}

/** Every `throw new Error(…)` argument in `source`, matched by paren depth (they span lines). */
function thrownArguments(source: string): string[] {
  const out: string[] = [];
  const marker = "throw new Error(";
  let at = source.indexOf(marker);
  while (at !== -1) {
    let depth = 1;
    let i = at + marker.length;
    for (; i < source.length && depth > 0; i++) {
      if (source[i] === "(") depth++;
      else if (source[i] === ")") depth--;
    }
    out.push(source.slice(at + marker.length, i - 1));
    at = source.indexOf(marker, i);
  }
  return out;
}

function directStatusThrows(source: string): number {
  return thrownArguments(source).filter((arg) => arg.includes("狀態碼") && !ROUTED.test(arg)).length;
}

function clipboardOffenders(files: { rel: string; source: string }[]): string[] {
  const allowed = new Set(["components/layout/CopyIconButton.tsx", "components/ads/patterns/CopyField.tsx"]);
  return files.filter((f) => !allowed.has(f.rel) && f.source.includes("navigator.clipboard")).map((f) => f.rel);
}

// ---------------------------------------------------------------------------------------------------
// F51 ratchet rules

/** The source with every comment replaced by spaces (newlines kept, so line numbers hold); a `//`
 * inside a string or template text is not a comment. Same reading as `components/ads/oneRuler.test.ts`. */
function blankComments(text: string): string {
  let out = "";
  let i = 0;
  const keep = (s: string) => { out += s; };
  const blank = (s: string) => { out += s.replace(/[^\n]/g, " "); };
  function code(inTemplate: boolean) {
    let depth = 0;
    while (i < text.length) {
      const c = text[i], n = text[i + 1];
      if (inTemplate && c === "{") depth++;
      if (inTemplate && c === "}" && depth-- === 0) return;
      if (c === "/" && n === "/") {
        const e = text.indexOf("\n", i);
        const stop = e === -1 ? text.length : e;
        blank(text.slice(i, stop));
        i = stop;
      } else if (c === "/" && n === "*") {
        const e = text.indexOf("*/", i + 2);
        const stop = e === -1 ? text.length : e + 2;
        blank(text.slice(i, stop));
        i = stop;
      } else if (c === '"' || c === "'") {
        let j = i + 1;
        while (j < text.length && text[j] !== c && text[j] !== "\n") j += text[j] === "\\" ? 2 : 1;
        keep(text.slice(i, Math.min(j + 1, text.length)));
        i = j + 1;
      } else if (c === "`") {
        keep(c);
        i++;
        template();
      } else {
        keep(c);
        i++;
      }
    }
  }
  function template() {
    while (i < text.length) {
      const c = text[i];
      if (c === "\\") {
        keep(text.slice(i, i + 2));
        i += 2;
      } else if (c === "`") {
        keep(c);
        i++;
        return;
      } else if (c === "$" && text[i + 1] === "{") {
        keep("${");
        i += 2;
        code(true);
        if (i < text.length) { keep("}"); i++; }
      } else {
        keep(c);
        i++;
      }
    }
  }
  code(false);
  return out;
}

type RuleName = "envelope" | "message-branch";

interface Rule {
  /** Which sources the rule reads (path relative to `src/`, `/` separators). */
  applies: (rel: string) => boolean;
  /** Whether one comment-blanked line is a hit, given the file it is in. */
  hit: (line: string, rel: string) => boolean;
  /** The inline excuse marker, e.g. `ENVELOPE_OK:`. */
  excuse: string;
}

const NOT_TRANSLATOR = (rel: string) => rel !== "lib/http.ts" && !rel.startsWith("lib/guards/");

const ENVELOPE_PATTERNS = [
  /\.json\(\)/, // reading a response body
  /\b(?:res|resp|response)\.ok\b/,
  /\binstanceof\s+TypeError\b/, // catching fetch's rejection
  /\berrorMessageFrom(?:Response)?\(/,
  /\bbody\??\.error\b/,
];
const OWN_ERROR_CLASS = /\bclass\s+\w+\s+extends\s+Error\b/;
const API_CLIENT = /^lib\/[^/]+Api\.ts$/;

const MESSAGE_BRANCH_PATTERNS = [
  /(?<!\btypeof\s+[\w$.?]+)\.message\s*[!=]==/, // `err.message === "…"`, not `typeof x.message === "string"`
  /\.message\??\.(?:includes|startsWith)\(/,
  /\bmessage\s*[!=]==\s*[A-Z][A-Z0-9_]+\b/, // `message === SOME_SENTENCE`
];

const RULES: Record<RuleName, Rule> = {
  envelope: {
    applies: (rel) => (rel.startsWith("components/") || rel.startsWith("lib/")) && NOT_TRANSLATOR(rel),
    hit: (line, rel) => ENVELOPE_PATTERNS.some((p) => p.test(line)) || (API_CLIENT.test(rel) && OWN_ERROR_CLASS.test(line)),
    excuse: "ENVELOPE_OK:",
  },
  "message-branch": {
    applies: (rel) => rel.startsWith("components/"),
    hit: (line) => MESSAGE_BRANCH_PATTERNS.some((p) => p.test(line)),
    excuse: "MESSAGE_BRANCH_OK:",
  },
};

/** Line numbers (1-based) of `rule`'s hits in `source`, split into excused and not. An excuse sits on
 * the hit line itself; `strayExcuses` are excuse markers on a line without a hit. */
function scan(rule: RuleName, rel: string, source: string): { hits: number[]; excused: number[]; strayExcuses: number[] } {
  const { hit, excuse } = RULES[rule];
  const raw = source.split("\n");
  const code = blankComments(source).split("\n");
  const out = { hits: [] as number[], excused: [] as number[], strayExcuses: [] as number[] };
  code.forEach((line, index) => {
    const excused = raw[index]?.includes(excuse) ?? false;
    if (hit(line, rel)) (excused ? out.excused : out.hits).push(index + 1);
    else if (excused) out.strayExcuses.push(index + 1);
  });
  return out;
}

interface AllowEntry { rule: string; file: string }
interface Allowed extends AllowEntry { issue: string }

const ALLOW_MODULES = import.meta.glob<{ default: AllowEntry[] }>("./guards/*.allow.ts", { eager: true });

/** Every `{rule, file}` of the per-issue allow modules, with the issue named by the module's file. */
function allowed(): Allowed[] {
  return Object.entries(ALLOW_MODULES).flatMap(([path, mod]) => {
    const issue = /([^/]+)\.allow\.ts$/.exec(path)?.[1] ?? path;
    return mod.default.map((entry) => ({ ...entry, issue }));
  });
}

function sourceFiles(): { rel: string; source: string }[] {
  return listFiles(SRC_DIR, true).map((full) => ({
    rel: relative(SRC_DIR, full).split("\\").join("/"),
    source: readFileSync(full, "utf-8"),
  }));
}

/** Per rule: files with an unexcused hit that no allow module lists, listed entries with no hit left,
 * and excuses on lines without a hit. */
function ratchet(rule: RuleName, files: { rel: string; source: string }[], allow: Allowed[]) {
  const listed = new Map(allow.filter((a) => a.rule === rule).map((a) => [a.file, a.issue]));
  const unlisted: string[] = [];
  const stale: string[] = [];
  const stray: string[] = [];
  const seen = new Set<string>();
  for (const { rel, source } of files) {
    if (!RULES[rule].applies(rel)) continue;
    const { hits, strayExcuses } = scan(rule, rel, source);
    if (hits.length) seen.add(rel);
    if (hits.length && !listed.has(rel)) unlisted.push(`${rel}:${hits.join(",")}`);
    for (const line of strayExcuses) stray.push(`${rel}:${line}`);
  }
  for (const [file, issue] of listed) if (!seen.has(file)) stale.push(`${issue}: ${file}`);
  return { unlisted, stale, stray };
}

describe("feedback guards (F47 Contract B)", () => {
  it("no src/lib/*.ts file throws a 「（狀態碼 N）」 message without routing it through the helper", () => {
    const found: Record<string, number> = {};
    for (const full of listFiles(LIB_DIR, false)) {
      const count = directStatusThrows(readFileSync(full, "utf-8"));
      if (count) found[relative(LIB_DIR, full).split("\\").join("/")] = count;
    }
    expect(found).toEqual({});
  });

  it("navigator.clipboard is only called inside CopyIconButton and CopyField", () => {
    expect(clipboardOffenders(sourceFiles())).toEqual([]);
  });

  it("the detectors see what they are meant to see", () => {
    expect(directStatusThrows("throw new Error(`儲存失敗（狀態碼 ${res.status}）`);")).toBe(1);
    expect(directStatusThrows("throw new Error(\n  a ? \"x\" : `讀取失敗（狀態碼 ${s}）`,\n);")).toBe(1);
    expect(directStatusThrows("throw new Error(await errorMessageFromResponse(res, `處理失敗（狀態碼 ${s}）`));")).toBe(0);
    expect(directStatusThrows("await throwIfFailed(res, `讀取失敗（狀態碼 ${res.status}）`);")).toBe(0);
    expect(clipboardOffenders([{ rel: "components/x/Y.tsx", source: "navigator.clipboard.writeText(t)" }])).toEqual([
      "components/x/Y.tsx",
    ]);
  });
});

describe("feedback guards (F51 Contract H／C ratchets)", () => {
  const files = sourceFiles();
  const allow = allowed();

  for (const rule of ["envelope", "message-branch"] as const) {
    it(`${rule}: every hit is in a file an F51 issue still lists, or excused inline`, () => {
      expect(ratchet(rule, files, allow).unlisted).toEqual([]);
    });
    it(`${rule}: every listed file still hits (the issue that cleaned it deletes its entry)`, () => {
      expect(ratchet(rule, files, allow).stale).toEqual([]);
    });
    it(`${rule}: every inline excuse sits on a hit`, () => {
      expect(ratchet(rule, files, allow).stray).toEqual([]);
    });
  }

  it("allow entries name a known rule and an existing source file", () => {
    const known = new Set([...Object.keys(RULES), "disabled", "zero", "currency", "money-ratio", "roas-format", "href"]);
    const rels = new Set(files.map((f) => f.rel));
    expect(allow.filter((a) => !known.has(a.rule) || !rels.has(a.file)).map((a) => `${a.issue}: ${a.rule} ${a.file}`)).toEqual([]);
  });

  it("comments are not code: blanking keeps line numbers and strings", () => {
    const src = 'const a = "// not a comment"; // res.ok\n/* body.error\n */ const b = `${x /* y */}`;';
    const out = blankComments(src);
    expect(out.split("\n")).toHaveLength(3);
    expect(out).toContain('"// not a comment"');
    expect(out).not.toContain("res.ok");
    expect(out).not.toContain("body.error");
    expect(out).not.toContain("y */");
  });

  it("the envelope scan sees response reads, fetch catches and own error classes, and leaves other .ok/.error alone", () => {
    const lines = (rel: string, src: string) => scan("envelope", rel, src).hits;
    expect(lines("components/x/Y.tsx", "const body = await res.json();")).toEqual([1]);
    expect(lines("components/x/Y.tsx", "if (!res.ok) return;")).toEqual([1]);
    expect(lines("components/x/Y.tsx", "if (!response.ok || resp.ok) return;")).toEqual([1]);
    expect(lines("lib/xApi.ts", "if (error instanceof TypeError) throw x;")).toEqual([1]);
    expect(lines("lib/xApi.ts", "message = errorMessageFrom(data, message);")).toEqual([1]);
    expect(lines("lib/xApi.ts", "return errorMessageFromResponse(res, f);")).toEqual([1]);
    expect(lines("components/x/Y.tsx", "setError(body?.error ?? x);\nconst m = body.error.message;")).toEqual([1, 2]);
    expect(lines("lib/xApi.ts", "export class XRejected extends Error {}")).toEqual([1]);
    expect(lines("lib/format.ts", "export class Odd extends Error {}")).toEqual([]);
    expect(lines("components/x/Y.tsx", "<p>{query.error.message}</p>\nif (item.ok && cell.ok && SWATCH.ok) x();")).toEqual([]);
    expect(lines("components/x/Y.tsx", "// res.json() in a comment\nconst t = JSON.stringify(v);")).toEqual([]);
    expect(scan("envelope", "lib/xApi.ts", "if (!res.ok) x(); // ENVELOPE_OK: a blob read").excused).toEqual([1]);
    expect(scan("envelope", "lib/xApi.ts", "const a = 1; // ENVELOPE_OK: nothing here").strayExcuses).toEqual([1]);
  });

  it("the message-branch scan sees text comparisons and leaves type checks alone", () => {
    const lines = (src: string) => scan("message-branch", "components/x/Y.tsx", src).hits;
    expect(lines('if (err.message === "找不到") x();')).toEqual([1]);
    expect(lines('if (e.message !== "x") x();')).toEqual([1]);
    expect(lines('if (err.message.includes("409")) x();')).toEqual([1]);
    expect(lines('if (error?.message?.startsWith("找不到")) x();')).toEqual([1]);
    expect(lines("if (message === NOT_FOUND) x();")).toEqual([1]);
    expect(lines('if (typeof x.message === "string") y();')).toEqual([]);
    expect(lines("setError(err instanceof Error ? err.message : FALLBACK);")).toEqual([]);
    expect(lines("if (err.code === \"campaign_busy\" || err.status === 404) x();")).toEqual([]);
    expect(scan("message-branch", "lib/x.ts", 'if (err.message === "x") y();').hits).toEqual([1]);
    expect(RULES["message-branch"].applies("lib/x.ts")).toBe(false);
  });
});
