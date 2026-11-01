/** Identifiers remain identifiers; only explicit public web URLs are links. */
export function SourceReference({ reference }: { reference: string }) {
  let href: string | null = null;
  try {
    const url = new URL(reference);
    if ((url.protocol === "https:" || url.protocol === "http:") && !url.username && !url.password) {
      href = url.href;
    }
  } catch { /* Source IDs are not necessarily URLs. */ }
  return href
    ? <a href={href} target="_blank" rel="noopener noreferrer">{reference}</a>
    : <span>{reference}</span>;
}
