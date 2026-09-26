/** Скачать файл по адресу или из Blob через временную ссылку. */
export function download(href: string | Blob, name?: string): void {
  const a = document.createElement("a");
  const url = typeof href === "string" ? href : URL.createObjectURL(href);
  a.href = url;
  if (name) a.download = name;
  else a.download = "";
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    if (typeof href !== "string") URL.revokeObjectURL(url);
    a.remove();
  }, 1000);
}
