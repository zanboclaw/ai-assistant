const listeners = new Map();

export function on(eventName, handler) {
  const handlers = listeners.get(eventName) || new Set();
  handlers.add(handler);
  listeners.set(eventName, handlers);
  return () => handlers.delete(handler);
}

export function emit(eventName, payload) {
  const handlers = listeners.get(eventName) || new Set();
  handlers.forEach((handler) => handler(payload));
}

