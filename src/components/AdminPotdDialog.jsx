import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Check, FileText, Image, LoaderCircle, Trash2, Upload, X } from 'lucide-react'
import { isValidLeetCodeProblemUrl } from '../utils/validation.js'

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const unit = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / (1024 ** unit)).toFixed(unit ? 1 : 0)} ${units[unit]}`
}

function AdminPotdDialog({ potd, onPrepare, onPublish, onClose }) {
  const [title, setTitle] = useState(potd?.title ?? '')
  const [url, setUrl] = useState(potd?.leetcodeUrl ?? potd?.original_url ?? '')
  const [solution, setSolution] = useState(potd?.solution ?? '')
  const [notes, setNotes] = useState(potd?.adminNotes ?? potd?.admin_notes ?? '')
  const [files, setFiles] = useState([])
  const [preparedProblem, setPreparedProblem] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const filesRef = useRef(files)

  useEffect(() => {
    filesRef.current = files
  }, [files])
  useEffect(() => () => {
    filesRef.current.forEach((file) => file.previewUrl && URL.revokeObjectURL(file.previewUrl))
  }, [])

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [busy, onClose])

  const addFiles = (event) => {
    const additions = Array.from(event.target.files ?? []).map((file) => ({
      id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${file.name}-${file.size}`,
      file,
      previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : '',
    }))
    setFiles((current) => [...current, ...additions])
    event.target.value = ''
  }

  const removeFile = (fileId) => {
    setFiles((current) => {
      const removed = current.find((item) => item.id === fileId)
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
      return current.filter((item) => item.id !== fileId)
    })
  }

  const prepare = async (event) => {
    event.preventDefault()
    const cleanTitle = title.trim()
    const cleanUrl = url.trim()
    if (!cleanTitle) return setError('Enter a problem title.')
    if (!isValidLeetCodeProblemUrl(cleanUrl)) return setError('Enter a valid LeetCode problem URL.')
    setBusy(true)
    setError('')
    try {
      const candidate = await onPrepare(cleanTitle, cleanUrl)
      setPreparedProblem(candidate)
    } catch (prepareError) {
      setError(prepareError.message)
    } finally {
      setBusy(false)
    }
  }

  const publish = async () => {
    setBusy(true)
    setError('')
    try {
      await onPublish({ title: title.trim(), url: url.trim(), solution, notes })
      onClose()
    } catch (publishError) {
      setError(publishError.message)
      setPreparedProblem(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose()
    }}>
      <section className="action-dialog potd-dialog" role="dialog" aria-modal="true" aria-labelledby="potd-dialog-title">
        <div className="dialog-top">
          <div className="dialog-title-wrap">
            <p className="section-kicker">TODAY&apos;S CHALLENGE</p>
            <h2 id="potd-dialog-title">{potd ? 'Update Today’s POTD' : 'Publish Today’s POTD'}</h2>
          </div>
          <button className="dialog-close" type="button" onClick={onClose} aria-label="Close dialog" disabled={busy}><X size={19} /></button>
        </div>

        {preparedProblem ? (
          <div className="potd-confirm">
            <p className="dialog-body">Verified against the Hugging Face problem dataset. Review the matching record before publishing.</p>
            <div className="potd-verified-card">
              <span>#{preparedProblem.problem_id} · {preparedProblem.difficulty ?? 'Difficulty not provided'}</span>
              <strong>{preparedProblem.title}</strong>
              <code>{preparedProblem.slug}</code>
            </div>
            {error && <p className="dialog-error" role="alert">{error}</p>}
            <div className="dialog-button-row">
              <button className="secondary-button" type="button" disabled={busy} onClick={() => setPreparedProblem(null)}>
                <ArrowLeft size={15} /> Edit details
              </button>
              <button className="primary-button" type="button" disabled={busy} onClick={publish}>
                {busy ? <><LoaderCircle className="spin" size={16} /> Publishing…</> : <>Confirm and publish <Check size={17} /></>}
              </button>
            </div>
          </div>
        ) : (
          <form className="dialog-form potd-form" onSubmit={prepare}>
            <label>
              Problem Title
              <input autoFocus disabled={busy} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Enter LeetCode problem title" required />
            </label>
            <label>
              LeetCode Problem Link
              <input disabled={busy} value={url} onChange={(event) => setUrl(event.target.value)} placeholder="Paste LeetCode problem link" inputMode="url" required />
            </label>
            <label>
              Solution
              <textarea disabled={busy} value={solution} onChange={(event) => setSolution(event.target.value)} placeholder="Add a verified reference solution (optional)" rows={4} />
            </label>
            <label>
              Notes
              <textarea disabled={busy} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Add challenge notes (optional)" rows={3} />
            </label>
            <div className="resource-upload">
              <span className="resource-upload-label">Resources</span>
              <label className="resource-upload-button">
                <Upload size={15} /> Choose files
                <input type="file" multiple onChange={addFiles} aria-label="Choose resources" />
              </label>
              <p>Preview only. Files are not uploaded or saved to Firebase Storage.</p>
              {files.length > 0 && (
                <ul className="resource-file-list">
                  {files.map(({ id, file, previewUrl }) => (
                    <li key={id}>
                      {previewUrl ? <img src={previewUrl} alt="" /> : file.type.startsWith('image/') ? <Image size={20} /> : <FileText size={20} />}
                      <span><strong>{file.name}</strong><small>{file.type || 'Unknown file type'} · {formatBytes(file.size)}</small></span>
                      <button type="button" aria-label={`Remove ${file.name}`} onClick={() => removeFile(id)}><Trash2 size={15} /></button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {error && <p className="dialog-error" role="alert">{error}</p>}
            <button className="primary-button dialog-submit" type="submit" disabled={busy}>
              {busy ? <><LoaderCircle className="spin" size={16} /> Verifying problem…</> : 'Review verified problem'}
              {!busy && <Check size={17} />}
            </button>
          </form>
        )}
      </section>
    </div>
  )
}

export default AdminPotdDialog
