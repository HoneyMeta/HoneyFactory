// Shared state for the app-wide AI Assistant: pages populate aiCtx; any button can call askAssistant() to send tasks to the bottom-right assistant.
import { reactive } from 'vue';
import { session } from './api';

export const aiCtx = reactive<{
  plant: string; page: string; view: string; selection: string[]; names: string[]; replayTime: string;
  getModel: null | (() => any);                       // Provided by Workbench: current draft
  apply: null | ((ops: any[], label: string) => void); // Provided by Workbench: apply changes as one undoable draft step
  highlight: null | ((ids: string[]) => void);
  navigate: null | ((nav: any) => void);               // Provided by Workbench: switch views / select / jump to a replay time
}>({ plant: '', page: '', view: '', selection: [], names: [], replayTime: '', getModel: null, apply: null, highlight: null, navigate: null });

export function askAssistant(prompt: string) {
  window.dispatchEvent(new CustomEvent('vf:assistant-ask', { detail: { prompt } }));
}

/** POST a message and invoke callbacks per SSE frame (fetch streaming; EventSource does not support POST). */
export async function streamEvents(url: string, body: any, on: (kind: string, data: any) => void) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.token }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) {
    const j = await r.json().catch(() => ({}));
    throw new Error(typeof j.detail === 'string' ? j.detail : r.statusText);
  }
  const rd = r.body.getReader(), dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await rd.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i); buf = buf.slice(i + 2);
      let kind = 'message', data = '';
      for (const line of frame.split('\n')) {
        if (line.startsWith('event: ')) kind = line.slice(7);
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      if (data) on(kind, JSON.parse(data));
    }
  }
}
