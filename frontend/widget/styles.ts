// Styles of the widget's shadow root. Logical properties (inset-inline, margin-inline) keep the layout
// correct in right-to-left mode.
export const WIDGET_CSS = `
:host { --sw-primary: #0f766e; --sw-bg: #ffffff; --sw-fg: #0f172a; --sw-muted: #64748b; --sw-border: #e2e8f0; --sw-soft: #f1f5f9;
  all: initial; font-family: "Inter", "Noto Sans Arabic", system-ui, -apple-system, "Segoe UI", Tahoma, sans-serif; }
@media (prefers-color-scheme: dark) { :host { --sw-bg: #0f172a; --sw-fg: #f1f5f9; --sw-muted: #94a3b8; --sw-border: #1e293b; --sw-soft: #1e293b; } }
* { box-sizing: border-box; }
button { font: inherit; cursor: pointer; }
.launcher { position: fixed; bottom: 20px; z-index: 2147483000; width: 56px; height: 56px; border: 0; border-radius: 50%;
  background: var(--sw-primary); color: #fff; display: grid; place-items: center; box-shadow: 0 8px 24px rgba(15,23,42,.25); }
.launcher.right { right: 20px; } .launcher.left { left: 20px; }
.launcher svg { width: 26px; height: 26px; }
.launcher:focus-visible, button:focus-visible, textarea:focus-visible, select:focus-visible { outline: 2px solid var(--sw-primary); outline-offset: 2px; }
.panel { position: fixed; bottom: 88px; z-index: 2147483000; width: 380px; max-width: calc(100vw - 24px); height: 560px; max-height: calc(100vh - 110px);
  background: var(--sw-bg); color: var(--sw-fg); border: 1px solid var(--sw-border); border-radius: 16px; display: flex; flex-direction: column;
  overflow: hidden; box-shadow: 0 16px 48px rgba(15,23,42,.22); font-size: 14px; line-height: 1.5; }
.panel[hidden] { display: none; }
.panel.right { right: 20px; } .panel.left { left: 20px; }
.panel[dir="rtl"] { font-family: "Noto Sans Arabic", Tahoma, system-ui, sans-serif; line-height: 1.75; }
@media (max-width: 480px) { .panel { inset: 0; width: 100%; max-width: none; height: 100%; max-height: none; border-radius: 0; } }
.header { display: flex; align-items: center; gap: 8px; padding: 12px 14px; background: var(--sw-primary); color: #fff; }
.title { flex: 1; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.header select { background: transparent; color: #fff; border: 1px solid rgba(255,255,255,.5); border-radius: 6px; padding: 2px 4px; font: inherit; }
.header select option { color: #0f172a; }
.icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 8px; border: 1px solid var(--sw-border); background: transparent; color: inherit; }
.header .icon { border-color: transparent; color: #fff; }
.icon svg, .send svg { width: 18px; height: 18px; }
.icon.recording { color: #dc2626; border-color: #fca5a5; }
.log { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.row.mine { align-items: flex-end; }
.bubble { max-width: 85%; padding: 9px 13px; border-radius: 14px; white-space: pre-wrap; word-wrap: break-word; background: var(--sw-soft); }
.row.mine .bubble { background: var(--sw-primary); color: #fff; }
.row.system .bubble { background: transparent; border: 1px dashed var(--sw-border); color: var(--sw-muted); font-size: 13px; }
.who { font-size: 12px; font-weight: 600; color: var(--sw-primary); }
.product { max-width: 85%; border: 1px solid var(--sw-border); border-radius: 10px; padding: 7px 10px; display: flex; flex-direction: column; font-size: 12px; }
.product span { color: var(--sw-muted); }
.sources { max-width: 85%; font-size: 12px; color: var(--sw-muted); }
.sources summary { cursor: pointer; } .sources p { margin: 4px 0 0; }
.typing { display: flex; gap: 4px; padding: 0 16px 8px; } .typing[hidden] { display: none; }
.typing span { width: 6px; height: 6px; border-radius: 50%; background: var(--sw-muted); animation: sw-bounce 1s infinite; }
.typing span:nth-child(2) { animation-delay: .15s; } .typing span:nth-child(3) { animation-delay: .3s; }
@keyframes sw-bounce { 0%, 80%, 100% { transform: translateY(0); opacity: .5; } 40% { transform: translateY(-4px); opacity: 1; } }
.composer { display: flex; align-items: flex-end; gap: 6px; padding: 10px; border-top: 1px solid var(--sw-border); }
.composer textarea { flex: 1; resize: none; min-height: 38px; max-height: 110px; padding: 8px 10px; border-radius: 10px; border: 1px solid var(--sw-border);
  background: var(--sw-bg); color: var(--sw-fg); font: inherit; }
.send { width: 38px; height: 38px; border: 0; border-radius: 10px; background: var(--sw-primary); color: #fff; display: grid; place-items: center; }
.panel[dir="rtl"] .send svg { transform: scaleX(-1); }
.footer { padding: 0 12px 10px; }
.link { border: 0; background: none; color: var(--sw-muted); font-size: 12px; text-decoration: underline; padding: 0; }
@media (prefers-reduced-motion: reduce) { .typing span { animation: none; } }
`;
