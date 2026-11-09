const allowedTags = new Set([
  'a', 'abbr', 'b', 'blockquote', 'br', 'caption', 'code', 'dd', 'del', 'details',
  'div', 'dl', 'dt', 'em', 'figcaption', 'figure', 'h1', 'h2', 'h3', 'h4', 'hr',
  'i', 'img', 'kbd', 'li', 'math', 'mi', 'mn', 'mo', 'mrow', 'mfrac', 'msup',
  'msub', 'mtext', 'munderover', 'mover', 'munder', 'ol', 'p', 'pre', 's', 'samp',
  'section', 'small', 'span', 'strong', 'sub', 'summary', 'sup', 'table', 'tbody',
  'td', 'th', 'thead', 'tr', 'tt', 'u', 'ul', 'var',
])

const blockedTags = new Set([
  'base', 'button', 'embed', 'form', 'iframe', 'input', 'link', 'meta', 'object',
  'script', 'select', 'style', 'svg', 'textarea',
])

function isSafeUrl(value, image = false) {
  try {
    const url = new URL(value, 'https://leetcode.com')
    return image
      ? url.protocol === 'https:'
      : ['https:', 'http:', 'mailto:'].includes(url.protocol)
  } catch {
    return false
  }
}

export function sanitizeProblemHtml(value) {
  if (typeof value !== 'string' || !value) return ''

  const template = document.createElement('template')
  template.innerHTML = value
  const elements = [...template.content.querySelectorAll('*')]

  for (const element of elements) {
    const tag = element.tagName.toLowerCase()
    if (blockedTags.has(tag)) {
      element.remove()
      continue
    }
    if (!allowedTags.has(tag)) {
      element.replaceWith(...element.childNodes)
      continue
    }

    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase()
      const value = attribute.value
      if (tag === 'a' && name === 'href' && isSafeUrl(value)) continue
      if (tag === 'img' && name === 'src' && isSafeUrl(value, true)) continue
      if (tag === 'img' && name === 'alt') continue
      if (name === 'title' || name === 'colspan' || name === 'rowspan' || name === 'scope') continue
      element.removeAttribute(attribute.name)
    }

    if (tag === 'a' && element.hasAttribute('href')) {
      element.setAttribute('target', '_blank')
      element.setAttribute('rel', 'noopener noreferrer')
    }
    if (tag === 'img' && element.hasAttribute('src')) {
      element.setAttribute('loading', 'lazy')
      element.setAttribute('referrerpolicy', 'no-referrer')
    }
  }

  return template.innerHTML
}

export function createProblemReference(problem) {
  const title = escapeHtml(problem.title ?? 'LeetCode problem')
  const description = sanitizeProblemHtml(problem.description ?? '')
  const tags = (problem.topic_tags ?? [])
    .map((tag) => (typeof tag === 'string' ? tag : tag.name ?? tag.slug ?? ''))
    .filter(Boolean)
    .map(escapeHtml)
    .join(', ')
  const topicLine = tags ? `<p><strong>Topics:</strong> ${tags}</p>` : ''
  const originalUrl = escapeHtml(problem.original_url ?? '')
  const link = originalUrl
    ? `<p><a href="${originalUrl}">Original LeetCode problem</a></p>`
    : ''

  return `<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title></head>
<body><main><h1>${title}</h1>${topicLine}${link}<article>${description}</article></main></body>
</html>`
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[character])
}
