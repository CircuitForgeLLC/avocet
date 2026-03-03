export type ApiError =
  | { kind: 'network'; message: string }
  | { kind: 'http'; status: number; detail: string }

export async function useApiFetch<T>(
  url: string,
  opts?: RequestInit,
): Promise<{ data: T | null; error: ApiError | null }> {
  try {
    const res = await fetch(url, opts)
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      return { data: null, error: { kind: 'http', status: res.status, detail } }
    }
    const data = await res.json() as T
    return { data, error: null }
  } catch (e) {
    return { data: null, error: { kind: 'network', message: String(e) } }
  }
}
