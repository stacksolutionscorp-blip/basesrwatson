import { Fragment, type ReactNode } from "react";

/** Markdown mínimo (títulos, parágrafos, listas, **negrito**) sem HTML bruto — o texto vem do servidor. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part}</Fragment>,
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks = text.split(/\n\s*\n/);
  return (
    <div className="space-y-3 text-sm leading-relaxed text-slate-700">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (b.startsWith("# ")) return <h2 key={i} className="text-lg font-semibold text-slate-900">{b.slice(2)}</h2>;
        if (lines.some((l) => l.startsWith("- "))) {
          const intro = lines.filter((l) => !l.startsWith("- ") && !l.startsWith("  "));
          const items: string[] = [];
          for (const l of lines) {
            if (l.startsWith("- ")) items.push(l.slice(2));
            else if (l.startsWith("  ") && items.length) items[items.length - 1] += " " + l.trim();
          }
          return (
            <div key={i}>
              {intro.length > 0 && <p>{inline(intro.join(" "))}</p>}
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {items.map((it, j) => (
                  <li key={j}>{inline(it)}</li>
                ))}
              </ul>
            </div>
          );
        }
        return <p key={i}>{inline(lines.join(" "))}</p>;
      })}
    </div>
  );
}
