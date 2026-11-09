import { useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowUpRight,
  Bookmark,
  Check,
  Clipboard,
  Download,
  ExternalLink,
  FileText,
  Lightbulb,
  MessageCircle,
  TerminalSquare,
} from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { createProblemReference, sanitizeProblemHtml } from '../utils/problemContent.js'

const resourceTabs = [
  { id: 'solution', label: 'Solution', icon: TerminalSquare },
  { id: 'notes', label: 'Notes', icon: FileText },
  { id: 'bookmark', label: 'Bookmark', icon: Bookmark },
  { id: 'concept', label: 'Concept', icon: Lightbulb },
  { id: 'discuss', label: 'Discuss', icon: MessageCircle },
]

const sampleDiscussion = [
  { author: 'MLSC community', text: 'Share an approach, ask a question, or compare notes after giving the problem a try.' },
]

function valueToText(value) {
  if (value == null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function getTagName(tag) {
  if (typeof tag === 'string') return tag
  return tag?.name ?? tag?.slug ?? ''
}

function getExamples(examples) {
  if (!Array.isArray(examples)) return []
  return examples.map((example) =>
    typeof example === 'string' ? example : valueToText(example),
  ).filter(Boolean)
}

function getSolutions(solution) {
  if (Array.isArray(solution)) {
    return solution.map((item, index) => ({
      language: item.language ?? item.lang ?? `Reference ${index + 1}`,
      code: item.code ?? item.solution ?? valueToText(item),
    }))
  }
  if (solution && typeof solution === 'object') {
    return Object.entries(solution).map(([language, code]) => ({
      language,
      code: typeof code === 'string' ? code : valueToText(code),
    }))
  }
  if (typeof solution === 'string' && solution.trim()) {
    return [{ language: 'Reference', code: solution }]
  }
  return []
}

function ProblemWorkspace({
  problem,
  loading,
  error,
  saveError,
  resources,
  onResourceChange,
  initialTab = 'solution',
  onBack,
  onRetry,
}) {
  const [activeTab, setActiveTab] = useState(initialTab)
  const [noteDraftOverride, setNoteDraftOverride] = useState(null)
  const noteDraft = noteDraftOverride ?? resources.notes ?? ''
  const [discussionDraft, setDiscussionDraft] = useState('')
  const [copied, setCopied] = useState('')
  const [copyError, setCopyError] = useState('')
  const [starterLanguage, setStarterLanguage] = useState('')
  const [solutionLanguage, setSolutionLanguage] = useState('')
  const shouldReduceMotion = useReducedMotion()

  const descriptionHtml = useMemo(
    () => sanitizeProblemHtml(problem?.description ?? ''),
    [problem?.description],
  )
  const examples = useMemo(() => getExamples(problem?.examples), [problem?.examples])
  const solutions = useMemo(() => getSolutions(problem?.solution), [problem?.solution])
  const selectedSolution =
    solutions.find((solution) => solution.language === solutionLanguage) ?? solutions[0]
  const starterCode = problem?.starter_code ?? []
  const selectedStarter =
    starterCode.find((starter) => starter.language === starterLanguage) ?? starterCode[0]
  const inputOutput = problem?.input_output_information ?? {}
  const similarQuestions = problem?.similar_questions ?? []

  const copyText = async (label, text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(label)
      setCopyError('')
      window.setTimeout(() => setCopied(''), 1600)
    } catch {
      setCopyError('Clipboard access is unavailable in this browser. Select and copy the text instead.')
    }
  }

  const downloadReference = () => {
    const blob = new Blob([createProblemReference(problem)], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${problem.slug || problem.problem_id || 'problem'}-reference.html`
    link.click()
    URL.revokeObjectURL(url)
  }

  const postDiscussion = (event) => {
    event.preventDefault()
    const text = discussionDraft.trim()
    if (!text) return
    onResourceChange({ discussion: [...(resources.discussion ?? []), { author: 'You', text }] })
    setDiscussionDraft('')
  }

  const renderResource = () => {
    if (activeTab === 'solution') {
      if (!solutions.length) {
        return (
          <div className="resource-empty">
            <TerminalSquare size={20} />
            <strong>No reference solution is available</strong>
            <span>The dataset does not include a verified solution for this problem.</span>
          </div>
        )
      }
      return (
        <div className="resource-content">
          <div className="resource-title-row">
            <div><h3>Reference solution</h3><p>Verified dataset content · no code execution</p></div>
            {solutions.length > 1 && (
              <label className="resource-language">
                <span className="sr-only">Solution language</span>
                <select value={selectedSolution?.language ?? ''} onChange={(event) => setSolutionLanguage(event.target.value)}>
                  {solutions.map((solution) => <option key={solution.language}>{solution.language}</option>)}
                </select>
              </label>
            )}
          </div>
          <pre className="workspace-code"><code>{selectedSolution?.code}</code></pre>
        </div>
      )
    }

    if (activeTab === 'notes') {
      return (
        <form className="resource-content notes-form" onSubmit={async (event) => {
          event.preventDefault()
          try {
            await onResourceChange({ notes: noteDraft })
            setNoteDraftOverride(null)
          } catch {
            return
          }
        }}>
          <h3>Your notes</h3>
          <p>Personal notes are private to your learner account.</p>
          <label className="sr-only" htmlFor="workspace-notes">Your notes</label>
          <textarea
            id="workspace-notes"
            value={noteDraft}
            onChange={(event) => setNoteDraftOverride(event.target.value)}
            placeholder="Capture an insight, edge case, or approach…"
            rows={5}
          />
          <button className="resource-save-button" type="submit"><Check size={15} /> Save notes</button>
          {resources.notes && !saveError && <span className="resource-saved-note">Notes saved to your account.</span>}
          {saveError && <span className="dialog-error" role="alert">{saveError}</span>}
        </form>
      )
    }

    if (activeTab === 'bookmark') {
      return (
        <div className="resource-content bookmark-panel">
          <div className="bookmark-panel-icon"><Bookmark size={20} fill={resources.bookmarked ? 'currentColor' : 'none'} /></div>
          <div><h3>{resources.bookmarked ? 'Saved for later' : 'Keep this problem close'}</h3><p>{resources.bookmarked ? 'This problem is in your bookmarks.' : 'Bookmark it to revisit during your practice.'}</p></div>
          <button
            className="resource-save-button"
            type="button"
            aria-pressed={Boolean(resources.bookmarked)}
            onClick={() => onResourceChange({ bookmarked: !resources.bookmarked })}
          >
            <Bookmark size={15} fill={resources.bookmarked ? 'currentColor' : 'none'} />
            {resources.bookmarked ? 'Remove bookmark' : 'Bookmark'}
          </button>
        </div>
      )
    }

    if (activeTab === 'concept') {
      const tags = (problem.topic_tags ?? []).map(getTagName).filter(Boolean)
      return (
        <div className="resource-content">
          <h3>Concepts in this problem</h3>
          <p>Topics are shown as supplied by the problem dataset.</p>
          <div className="workspace-tags">
            {tags.map((tag) => <span className="workspace-tag" key={tag}>{tag}</span>)}
            {problem.category && <span className="workspace-tag workspace-tag-category">{problem.category}</span>}
            {!tags.length && !problem.category && <span className="resource-empty-inline">No topic concepts are listed in the dataset.</span>}
          </div>
        </div>
      )
    }

    const discussion = [...sampleDiscussion, ...(resources.discussion ?? [])]
    return (
      <div className="resource-content discussion-panel">
        <h3>Problem discussion</h3>
        <p>Exchange ideas and questions with the challenge community.</p>
        <div className="discussion-list">
          {discussion.map((item, index) => (
            <article className="discussion-item" key={`${item.author}-${index}`}>
              <span className="discussion-avatar">{item.author.slice(0, 1)}</span>
              <div><strong>{item.author}</strong><p>{item.text}</p></div>
            </article>
          ))}
        </div>
        <form className="discussion-compose" onSubmit={postDiscussion}>
          <label className="sr-only" htmlFor="workspace-discussion">Add to discussion</label>
          <textarea id="workspace-discussion" rows={2} value={discussionDraft} onChange={(event) => setDiscussionDraft(event.target.value)} placeholder="Share a thought or ask a question…" />
          <button className="resource-save-button" type="submit" disabled={!discussionDraft.trim()}>Post</button>
        </form>
      </div>
    )
  }

  if (!problem) {
    return (
      <section className="workspace-error page-shell" aria-live="polite">
        <div className="workspace-error-card">
          <TerminalSquare size={26} />
          <h1>{loading ? 'Retrieving problem information…' : 'Problem information is unavailable'}</h1>
          <p>{loading ? 'Looking up the verified dataset record. This may take a little longer on the first request.' : error || 'The problem dataset could not provide a verified record for this problem.'}</p>
          <div className="workspace-error-actions">
            {!loading && <button className="primary-button" type="button" onClick={onRetry}>Retry</button>}
            <button className="secondary-button" type="button" onClick={onBack}>Back to problems</button>
          </div>
        </div>
      </section>
    )
  }

  const titleToCopy = problem.title ?? ''
  const urlToCopy = problem.original_url ?? ''
  const metadataStats = [
    problem.total_accepted != null && { label: 'Accepted', value: valueToText(problem.total_accepted) },
    problem.total_submissions != null && { label: 'Submissions', value: valueToText(problem.total_submissions) },
  ].filter(Boolean)

  return (
    <motion.section
      className="workspace-page"
      aria-label={`Problem workspace: ${problem.title}`}
      initial={shouldReduceMotion ? false : { opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: shouldReduceMotion ? 0 : 0.28 }}
    >
      <div className="workspace-topbar">
        <button className="back-link" type="button" onClick={onBack}><ArrowLeft size={16} /> Back to problems</button>
        <span className="workspace-topbar-label">MLSC PROBLEM WORKSPACE</span>
        <a className="workspace-topbar-link" href={problem.original_url} target="_blank" rel="noopener noreferrer">
          LeetCode <ArrowUpRight size={14} />
        </a>
      </div>

      <div className="workspace-split">
        <section className="workspace-problem-panel" aria-labelledby="workspace-problem-title">
          <div className="workspace-problem-header">
            <p className="section-kicker">PROBLEM {problem.problem_id ? `#${problem.problem_id}` : ''}</p>
            <h1 id="workspace-problem-title">{problem.title}</h1>
            <div className="workspace-problem-stats">
              {problem.difficulty && <span className={`workspace-difficulty difficulty-${problem.difficulty.toLowerCase()}`}>{problem.difficulty}</span>}
              {problem.acceptance_rate != null && <span>{Number(problem.acceptance_rate).toFixed(1)}% acceptance</span>}
              {problem.category && <span>{problem.category}</span>}
            </div>
            {!!metadataStats.length && (
              <div className="workspace-dataset-stats">
                {metadataStats.map((stat) => <span key={stat.label}><strong>{stat.value}</strong> {stat.label}</span>)}
              </div>
            )}
            {!!problem.topic_tags?.length && (
              <div className="workspace-tags">
                {problem.topic_tags.map((tag, index) => {
                  const name = getTagName(tag)
                  return name ? <span className="workspace-tag" key={`${name}-${index}`}>{name}</span> : null
                })}
              </div>
            )}
          </div>

          <div className="workspace-statement">
            {descriptionHtml ? (
              <article className="dataset-statement" dangerouslySetInnerHTML={{ __html: descriptionHtml }} />
            ) : (
              <div className="statement-unavailable">A complete problem statement is not available in this dataset record.</div>
            )}

            {examples.length > 0 && (
              <section className="dataset-extra-section">
                <h2>Examples from dataset</h2>
                {examples.map((example, index) => <pre className="workspace-code" key={index}>{example}</pre>)}
              </section>
            )}
            {problem.sample_test_case && (
              <section className="dataset-extra-section">
                <h2>Sample test case</h2>
                <pre className="workspace-code">{problem.sample_test_case}</pre>
              </section>
            )}
            {problem.constraints && (
              <section className="dataset-extra-section">
                <h2>Constraints</h2>
                {Array.isArray(problem.constraints)
                  ? <ul>{problem.constraints.map((constraint, index) => <li key={index}>{constraint}</li>)}</ul>
                  : <pre className="workspace-code">{valueToText(problem.constraints)}</pre>}
              </section>
            )}
            {Object.keys(inputOutput).length > 0 && (
              <section className="dataset-extra-section">
                <h2>Input / output information</h2>
                <dl className="workspace-definition-list">
                  {Object.entries(inputOutput).map(([label, value]) => (
                    <div key={label}><dt>{label}</dt><dd><pre>{valueToText(value)}</pre></dd></div>
                  ))}
                </dl>
              </section>
            )}
            {problem.environment_info && (
              <details className="dataset-metadata">
                <summary>Environment information</summary>
                <pre className="workspace-code">{problem.environment_info}</pre>
              </details>
            )}
            {problem.metadata && (
              <details className="dataset-metadata">
                <summary>Dataset metadata</summary>
                <pre className="workspace-code">{valueToText(problem.metadata)}</pre>
              </details>
            )}
            {!!similarQuestions.length && (
              <section className="dataset-extra-section">
                <h2>Similar questions</h2>
                <ul className="similar-question-list">
                  {similarQuestions.map((question, index) => {
                    const relatedTitle = typeof question === 'string'
                      ? question
                      : question.title ?? question.questionTitle ?? valueToText(question)
                    const relatedSlug = typeof question === 'object'
                      ? question.titleSlug ?? question.slug
                      : null
                    return (
                      <li key={`${relatedSlug ?? relatedTitle}-${index}`}>
                        {relatedSlug
                          ? <a href={`https://leetcode.com/problems/${encodeURIComponent(relatedSlug)}/`} target="_blank" rel="noopener noreferrer">{relatedTitle}</a>
                          : <span>{relatedTitle}</span>}
                      </li>
                    )
                  })}
                </ul>
              </section>
            )}
          </div>
        </section>

        <aside className="workspace-actions-panel" aria-label="Problem actions and learning resources">
          <section className="workspace-action-card vscode-card">
            <div className="workspace-action-heading">
              <div className="workspace-action-icon"><TerminalSquare size={19} /></div>
              <div><p className="section-kicker">YOUR WORKFLOW</p><h2>Try it on VS Code first</h2></div>
            </div>
            <p className="workspace-action-description">
              Work through the problem locally in VS Code or your preferred setup. We provide a
              reference file and dataset starter-code information where available — no browser IDE
              or code execution is provided.
            </p>

            <div className="copy-field">
              <span>Problem title</span>
              <div><code>{titleToCopy}</code><button type="button" onClick={() => copyText('title', titleToCopy)} aria-label="Copy problem title">{copied === 'title' ? <Check size={15} /> : <Clipboard size={15} />}</button></div>
            </div>
            <div className="copy-field">
              <span>LeetCode URL</span>
              <div><code>{urlToCopy}</code><button type="button" onClick={() => copyText('url', urlToCopy)} aria-label="Copy LeetCode URL">{copied === 'url' ? <Check size={15} /> : <Clipboard size={15} />}</button></div>
            </div>
            {copyError && <p className="workspace-copy-error" role="status">{copyError}</p>}

            <div className="workspace-download-row">
              <button className="secondary-button" type="button" onClick={downloadReference}><Download size={15} /> Download problem reference</button>
            </div>
            <p className="workspace-download-note">Downloads a statement reference file; it does not open VS Code automatically.</p>

            {starterCode.length > 0 && (
              <div className="starter-code-info">
                <div className="starter-code-header">
                  <div><h3>Dataset starter code</h3><p>Reference only · not an editor</p></div>
                  {starterCode.length > 1 && (
                    <label className="resource-language">
                      <span className="sr-only">Starter code language</span>
                      <select value={selectedStarter?.language ?? ''} onChange={(event) => setStarterLanguage(event.target.value)}>
                        {starterCode.map((starter) => <option key={starter.language}>{starter.language}</option>)}
                      </select>
                    </label>
                  )}
                </div>
                <pre className="workspace-code starter-code-block"><code>{selectedStarter?.code}</code></pre>
              </div>
            )}
          </section>

          <section className="workspace-action-card leetcode-card">
            <div className="workspace-action-heading">
              <div className="workspace-action-icon leetcode-icon"><ExternalLink size={18} /></div>
              <div><p className="section-kicker">ORIGINAL PROBLEM</p><h2>Continue on LeetCode</h2></div>
            </div>
            <p className="workspace-action-description">Open the original problem statement on LeetCode in a new tab.</p>
            <a className="primary-button solve-leetcode-button" href={problem.original_url} target="_blank" rel="noopener noreferrer">
              Solve on LeetCode <ArrowUpRight size={17} />
            </a>
          </section>

          <section className="workspace-resources-card">
            <div className="workspace-resources-heading">
              <p className="section-kicker">AFTER SOLVING</p>
              <h2>Keep learning</h2>
              <p>These resources are available whenever you need them.</p>
            </div>
            <div className="resource-tabs" role="tablist" aria-label="Learning resources">
              {resourceTabs.map(({ id, label, icon: Icon }) => (
                <button
                  className={`resource-tab ${activeTab === id ? 'resource-tab-active' : ''} ${id === 'bookmark' && resources.bookmarked ? 'resource-tab-bookmarked' : ''}`}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === id}
                  key={id}
                  onClick={() => setActiveTab(id)}
                >
                  <Icon size={15} fill={id === 'bookmark' && resources.bookmarked ? 'currentColor' : 'none'} />
                  {label}
                  {id === 'bookmark' && resources.bookmarked && <Check size={12} />}
                </button>
              ))}
            </div>
            <div className="resource-panel" role="tabpanel">{renderResource()}</div>
          </section>
        </aside>
      </div>
    </motion.section>
  )
}

export default ProblemWorkspace
