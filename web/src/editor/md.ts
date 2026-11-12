// Minimal Markdown renderer: headings, bold, inline code, lists, table rows; escape before replacing to prevent injection.
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const inline = (s: string) => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
export function md(src: string) {
  const out: string[] = []; let list = false;
  for (const raw of (src || '').split('\n')) {
    const line = raw.trimEnd();
    const li = line.match(/^\s*(?:[-*]|\d+[.\u3001)])\s+(.*)$/);
    if (li) { if (!list) { out.push('<ul>'); list = true; } out.push(`<li>${inline(li[1])}</li>`); continue; }
    if (list) { out.push('</ul>'); list = false; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) out.push(`<div class="mh">${inline(h[2])}</div>`);
    else if (/^\|.*\|$/.test(line)) { if (!/^\|[\s:|-]+\|$/.test(line)) out.push(`<div class="mt">${line.slice(1, -1).split('|').map((c) => `<span>${inline(c.trim())}</span>`).join('')}</div>`); }
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push('</ul>');
  return out.join('');
}
