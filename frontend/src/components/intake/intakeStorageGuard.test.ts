import ts from "typescript";
import {expect,it} from "vitest";
const files=import.meta.glob("./**/*.{ts,tsx}",{query:"?raw",import:"default",eager:true}) as Record<string,string>;
function storageHits(source:string):string[] {
 const hits:string[]=[];
 const tree=ts.createSourceFile("input.tsx",source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
 function walk(n:ts.Node) {
  if(ts.isIdentifier(n) && ["localStorage","sessionStorage"].includes(n.text)) hits.push(n.text);
  if((ts.isStringLiteral(n)||ts.isNoSubstitutionTemplateLiteral(n)||ts.isTemplateHead(n)) && /intake-(draft|start|view):/.test(n.text)) hits.push(n.text);
  ts.forEachChild(n,walk);
 }
 walk(tree); return hits;
}
it("only stepDraft owns intake storage and keys",()=>{
 const found=Object.entries(files).filter(([p])=>!p.includes(".test.") && p!=="./shared/stepDraft.ts").flatMap(([p,s])=>storageHits(s).map(h=>`${p}: ${h}`));
 expect(found).toEqual([]);
});
it("detects direct storage and duplicated keys while ignoring prose",()=>{
 expect(storageHits('window.localStorage.setItem("intake-start:x", "a")')).toHaveLength(2);
 expect(storageHits('sessionStorage.getItem(`intake-view:${id}`)')).toHaveLength(2);
 expect(storageHits('const key=`intake-draft:${scope}:${brand}`')).toHaveLength(1);
 expect(storageHits('// sessionStorage intake-view: legacy')).toEqual([]);
});
