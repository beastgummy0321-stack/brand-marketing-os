import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui 慣用的 class 合併 helper：後續票加 shadcn 元件時直接複用。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
