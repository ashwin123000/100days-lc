export const ADVENTURE_TOPICS = [
  {
    id: 'arrays-hashing',
    label: 'Arrays & Hashing',
    icon: 'arrays',
    x: 8.5,
    y: 72,
    aliases: ['array', 'hash table', 'hash map', 'hash set'],
  },
  {
    id: 'strings-windows',
    label: 'Strings & Windows',
    icon: 'strings',
    x: 21.5,
    y: 53,
    aliases: ['string', 'sliding window', 'substring'],
  },
  {
    id: 'stack-queue',
    label: 'Stack & Queue',
    icon: 'stack',
    x: 38,
    y: 76,
    aliases: ['stack', 'queue'],
  },
  {
    id: 'lists-search',
    label: 'Lists & Search',
    icon: 'lists',
    x: 55,
    y: 60,
    aliases: ['linked list', 'binary search', 'two pointers'],
  },
  {
    id: 'trees',
    label: 'Trees',
    icon: 'trees',
    x: 70,
    y: 43,
    aliases: ['tree', 'trie'],
  },
  {
    id: 'graphs',
    label: 'Graphs',
    icon: 'graphs',
    x: 92,
    y: 37,
    aliases: ['graph', 'depth first search', 'breadth first search', 'union find', 'topological sort'],
  },
  {
    id: 'dynamic-programming',
    label: 'Dynamic Programming',
    icon: 'dynamic',
    x: 77,
    y: 16,
    aliases: ['dynamic programming'],
  },
  {
    id: 'greedy-backtracking',
    label: 'Greedy & Backtracking',
    icon: 'greedy',
    x: 59,
    y: 32,
    aliases: ['greedy', 'backtracking'],
  },
  {
    id: 'heap-design',
    label: 'Heap & Design',
    icon: 'heap',
    x: 42,
    y: 17,
    aliases: ['heap', 'priority queue', 'design'],
  },
  {
    id: 'final-boss',
    label: 'Final Boss',
    icon: 'boss',
    x: 20,
    y: 22,
    difficulty: 'hard',
    aliases: [],
  },
]

function normalizeTopic(value) {
  return String(value ?? '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

export function problemMatchesAdventureTopic(problem, topicId) {
  const topic = ADVENTURE_TOPICS.find((item) => item.id === topicId)
  if (!topic) return false

  if (topic.difficulty) {
    return normalizeTopic(problem?.difficulty) === topic.difficulty
  }

  const tags = problem?.topics ?? problem?.topicTags ?? problem?.topic_tags ?? []
  return tags.some((tag) => {
    const tagName = normalizeTopic(typeof tag === 'string' ? tag : tag?.name ?? tag?.slug)
    return tagName && topic.aliases.some((alias) => tagName.includes(normalizeTopic(alias)))
  })
}
