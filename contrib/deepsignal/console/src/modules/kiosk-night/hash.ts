export function parseKioskHash(hash: string): string | undefined {
  const match = /^#(.+)-kiosk$/.exec(hash)
  return match?.[1]
}
