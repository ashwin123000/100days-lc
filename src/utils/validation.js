export function isValidLeetCodeProblemUrl(value) {
  try {
    const parsedUrl = new URL(value)
    return (
      parsedUrl.protocol === 'https:' &&
      ['leetcode.com', 'www.leetcode.com'].includes(parsedUrl.hostname.toLowerCase()) &&
      parsedUrl.username === '' &&
      parsedUrl.password === '' &&
      /^\/problems\/[a-z0-9-]+\/?$/i.test(parsedUrl.pathname)
    )
  } catch {
    return false
  }
}
