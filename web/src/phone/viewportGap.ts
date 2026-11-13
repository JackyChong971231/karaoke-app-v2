// WebKit on iOS (Safari, and Chrome/Firefox which use it) sometimes lays out
// position:fixed elements against a stale, taller viewport — most often after
// the keyboard closes or the toolbar changes size. Anything pinned to bottom:0
// then hides behind the browser toolbar. We measure how far the fixed layer's
// bottom extends past what is actually visible and publish it as --vv-gap, which
// the bottom-pinned elements add to their offset. Everywhere else it stays 0px.

export function trackViewportGap(): void {
  const vv = window.visualViewport;
  if (vv === null) return; // no API → keep the plain CSS behaviour

  const probe = document.createElement("div");
  probe.setAttribute("aria-hidden", "true");
  probe.style.cssText = "position:fixed;top:0;bottom:0;left:0;width:0;visibility:hidden;pointer-events:none";
  document.body.appendChild(probe);

  const root = document.documentElement;
  let frame = 0;

  const measure = (): void => {
    frame = 0;
    const active = document.activeElement;
    const typing =
      active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement || (active as HTMLElement | null)?.isContentEditable === true;
    let gap = 0;
    // While typing, let the keyboard cover the bars as usual; when zoomed, the
    // visual viewport is smaller on purpose and must not move the bars.
    if (!typing && vv.scale < 1.01) {
      const fixedBottom = probe.getBoundingClientRect().bottom;
      const visibleBottom = vv.offsetTop + vv.height;
      gap = Math.max(0, Math.round(fixedBottom - visibleBottom));
      if (gap < 2) gap = 0;
    }
    root.style.setProperty("--vv-gap", `${String(gap)}px`);
  };

  const schedule = (): void => {
    if (frame === 0) frame = requestAnimationFrame(measure);
  };
  // iOS settles the viewport a little after the keyboard animates away.
  const settle = (): void => {
    schedule();
    window.setTimeout(schedule, 150);
    window.setTimeout(schedule, 500);
  };

  vv.addEventListener("resize", schedule);
  vv.addEventListener("scroll", schedule);
  window.addEventListener("resize", schedule);
  window.addEventListener("orientationchange", settle);
  window.addEventListener("pageshow", settle);
  document.addEventListener("focusin", settle);
  document.addEventListener("focusout", settle);
  document.addEventListener("visibilitychange", settle);
  measure();
}
