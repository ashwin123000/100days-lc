import { ArrowUpRight, CalendarDays, Sparkles } from 'lucide-react'

function getTopicNames(topics = []) {
  return topics.map((topic) => typeof topic === 'string' ? topic : topic?.name).filter(Boolean)
}

function PotdFeature({ potd, onOpen, admin = false, onManage }) {
  const topicTags = getTopicNames(potd?.topicTags ?? potd?.topic_tags ?? [])
  const descriptionPreview = (potd?.description ?? '')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

  return (
    <section className={`potd-feature ${admin ? 'potd-feature-admin' : ''}`} aria-labelledby="potd-title">
      <div className="potd-feature-copy">
        <div className="potd-icon"><Sparkles size={20} /></div>
        <div>
          <p className="section-kicker">DAILY CHALLENGE</p>
          <h2 id="potd-title">Today&apos;s Problem of the Day</h2>
          {potd ? (
            <>
              <p className="potd-current-title">{potd.title}</p>
              <div className="potd-problem-meta">
                {potd.difficulty && <span>{potd.difficulty}</span>}
                {topicTags.length > 0 && <span>{topicTags.join(' · ')}</span>}
                {!admin && <span className="potd-today-label">Today&apos;s POTD</span>}
              </div>
              {!admin && descriptionPreview && (
                <p className="potd-description-preview">
                  {descriptionPreview.length > 240 ? `${descriptionPreview.slice(0, 237)}…` : descriptionPreview}
                </p>
              )}
            </>
          ) : (
            <p className="potd-empty-copy">
              {admin ? 'No problem has been published for today yet.' : 'Today’s featured problem will appear here once it is published.'}
            </p>
          )}
        </div>
      </div>

      <div className="potd-feature-actions">
        {potd && !admin && (
          <button className="potd-open-button" type="button" onClick={onOpen}>
            Open problem <ArrowUpRight size={17} />
          </button>
        )}
        {admin && (
          <button className="primary-button potd-manage-button" type="button" onClick={onManage}>
            <CalendarDays size={16} />
            {potd ? 'Update Today’s POTD' : 'Add Today’s POTD'}
          </button>
        )}
      </div>
    </section>
  )
}

export default PotdFeature
