function tagName(tag) {
  if (typeof tag === 'string') return tag
  return tag?.name ?? tag?.slug ?? ''
}

export function canonicalToListProblem(problem) {
  const topicTags = problem.topicTags ?? problem.topic_tags ?? []
  return {
    ...problem,
    id: problem.externalProblemId ?? problem.external_problem_id ?? problem.problem_id ?? problem.problemId,
    canonicalId: problem.problemId ?? problem.slug,
    title: problem.title,
    url: problem.leetcodeUrl ?? problem.original_url,
    difficulty: problem.difficulty ?? 'Unknown',
    topics: topicTags.map(tagName).filter(Boolean),
    acceptance: problem.acceptanceRate ?? problem.acceptance_rate ?? null,
    solution: problem.solution ?? null,
    notes: problem.adminNotes ?? '',
    discussion: [],
    bookmarked: false,
    status: 'Not started',
  }
}

export function canonicalToWorkspaceProblem(problem) {
  return {
    problem_id: problem.externalProblemId ?? problem.external_problem_id ?? problem.problem_id,
    canonical_id: problem.problemId ?? problem.canonicalId ?? problem.slug,
    title: problem.title,
    slug: problem.slug,
    description: problem.description ?? '',
    difficulty: problem.difficulty ?? null,
    acceptance_rate: problem.acceptanceRate ?? problem.acceptance_rate ?? null,
    total_accepted: problem.totalAccepted ?? problem.total_accepted ?? null,
    total_submissions: problem.totalSubmissions ?? problem.total_submissions ?? null,
    topic_tags: problem.topicTags ?? problem.topic_tags ?? [],
    category: problem.category ?? null,
    examples: problem.examples ?? [],
    constraints: problem.constraints ?? null,
    input_output_information: problem.inputOutputInformation ?? problem.input_output_information ?? {},
    starter_code: problem.starterCode ?? problem.starter_code ?? [],
    solution: problem.solution ?? null,
    similar_questions: problem.similarQuestions ?? problem.similar_questions ?? [],
    sample_test_case: problem.sampleTestCase ?? problem.sample_test_case ?? '',
    metadata: problem.datasetMetadata ?? problem.metadata ?? null,
    environment_info: problem.environmentInfo ?? problem.environment_info ?? '',
    original_url: problem.leetcodeUrl ?? problem.original_url ?? problem.url ?? '',
  }
}
