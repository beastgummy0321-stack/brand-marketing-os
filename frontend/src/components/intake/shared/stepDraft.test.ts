import {renderHook} from "@testing-library/react";
import {afterEach, expect, it} from "vitest";
import {brandDraftKey, productDraftKey, readStepDraft, useStepDraft} from "./stepDraft";
const shape = (v: unknown): v is {text:string} => !!v && typeof v === "object" && "text" in v && typeof v.text === "string";
afterEach(() => sessionStorage.clear());
it("isolates brand drafts by user, brand and step and leaves product keys stable", () => {
  const key=brandDraftKey("u:o","b","identity");
  expect(key).toBe("intake-draft:u:o:b:identity");
  sessionStorage.setItem(key, JSON.stringify({text:"draft"}));
  expect(readStepDraft(brandDraftKey("v:o","b","identity"),shape)).toBeNull();
  expect(readStepDraft(brandDraftKey("u:o","c","identity"),shape)).toBeNull();
  expect(readStepDraft(brandDraftKey("u:o","b","evidence"),shape)).toBeNull();
  expect(productDraftKey("b","p","what")).toBe("intake-draft:b:p:what");
});
it("waits for load, restores valid changes, and removes a confirmed baseline", () => {
 const key=brandDraftKey("u:o","new","start");
 const {rerender}=renderHook(({ready,current})=>useStepDraft(key,ready,current,{text:"saved"}), {initialProps:{ready:false,current:{text:"draft"}}});
 expect(readStepDraft(key,shape)).toBeNull();
 rerender({ready:true,current:{text:"draft"}});
 expect(readStepDraft(key,shape)).toEqual({text:"draft"});
 rerender({ready:true,current:{text:"saved"}});
 expect(readStepDraft(key,shape)).toBeNull();
 sessionStorage.setItem(key,"broken"); expect(readStepDraft(key,shape)).toBeNull();
 sessionStorage.setItem(key,'{"text":42}'); expect(readStepDraft(key,shape)).toBeNull();
});
