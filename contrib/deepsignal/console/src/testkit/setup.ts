if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (media) => ({
    media, matches: false, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
    dispatchEvent: () => true,
  })
}
