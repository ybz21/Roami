function revealReviewState() {
  const state = document.getElementById(location.hash.slice(1))
  if (state instanceof HTMLDetailsElement) {
    state.open = true
    state.scrollIntoView({ block: 'start' })
    state.querySelector('summary')?.focus({ preventScroll: true })
  }
}

window.addEventListener('hashchange', revealReviewState)
revealReviewState()
