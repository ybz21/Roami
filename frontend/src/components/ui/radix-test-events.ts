export function installRadixTestEvents() {
  HTMLElement.prototype.scrollIntoView ||= () => {}
  HTMLElement.prototype.hasPointerCapture ||= () => false
  HTMLElement.prototype.setPointerCapture ||= () => {}
  HTMLElement.prototype.releasePointerCapture ||= () => {}
  globalThis.ResizeObserver ||= class { observe() {} unobserve() {} disconnect() {} }
}
