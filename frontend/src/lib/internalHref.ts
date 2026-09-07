/** API action URLs already include /app; router Links must not prepend it again. */
export function internalHref(href: string): string {
  return href === "/app" || href === "/app/"
    ? "/"
    : href.startsWith("/app/")
      ? href.slice(4)
      : href;
}
