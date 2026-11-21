const values = new Map<string, string>()

export const prototypeStorage: Storage = {
  get length() { return values.size },
  key(index) { return [...values.keys()][index] ?? null },
  getItem(key) { return values.get(key) ?? null },
  setItem(key, value) { values.set(key, value) },
  removeItem(key) { values.delete(key) },
  clear() { values.clear() },
}
