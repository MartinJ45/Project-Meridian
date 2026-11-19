import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const PAD = 32 + 2 // .pdf-scroll padding (16px each side) + 1px slack per side for sub-pixel rounding

// Opens at "Fit" (whole sheet width visible) and stays fitted as the pane resizes,
// until the user zooms manually. All scrolling happens inside .pdf-scroll.
// highlight: { box_2d: [ymin, xmin, ymax, xmax] on a 0-1000 grid, page, label } from the Evidence tab.
export default function PdfViewer({ url, highlight, onClearHighlight }) {
  const canvasRef = useRef(null)
  const scrollRef = useRef(null)
  const markRef = useRef(null)
  const [pdf, setPdf] = useState(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(null) // page size at scale 1
  const [fit, setFit] = useState(true)
  const [scale, setScale] = useState(1)
  const [error, setError] = useState(null)

  useEffect(() => {
    setPdf(null); setPage(1); setError(null); setFit(true)
    const task = pdfjs.getDocument(url)
    task.promise.then(setPdf).catch((e) => setError(e.message))
    return () => { task.destroy() }
  }, [url])

  useEffect(() => {
    if (!pdf) return
    pdf.getPage(page).then((p) => {
      const v = p.getViewport({ scale: 1 })
      setPageSize({ w: v.width, h: v.height })
    })
  }, [pdf, page])

  // Fit mode: scale the sheet so it fits the pane (width and height), and refit on resize.
  useEffect(() => {
    const el = scrollRef.current
    if (!fit || !pageSize || !el) return
    const refit = () => {
      const s = Math.min((el.clientWidth - PAD) / pageSize.w, (el.clientHeight - PAD) / pageSize.h)
      // Round down so the rendered sheet can never be a fraction of a pixel too big.
      if (s > 0) setScale(Math.max(0.1, Math.floor(s * 1000) / 1000))
    }
    refit()
    const ro = new ResizeObserver(refit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [fit, pageSize])

  useEffect(() => {
    if (!pdf) return
    let renderTask
    let cancelled = false
    pdf.getPage(page).then((p) => {
      if (cancelled) return
      const viewport = p.getViewport({ scale })
      const canvas = canvasRef.current
      if (!canvas) return
      const ratio = window.devicePixelRatio || 1
      canvas.width = viewport.width * ratio
      canvas.height = viewport.height * ratio
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`
      const ctx = canvas.getContext('2d')
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
      renderTask = p.render({ canvasContext: ctx, viewport })
      renderTask.promise.catch(() => {}) // cancelled renders reject; that's expected
    })
    return () => { cancelled = true; renderTask?.cancel() }
  }, [pdf, page, scale])

  const zoom = (f) => { setFit(false); setScale((s) => Math.min(6, Math.max(0.1, s * f))) }

  // Jump to the highlighted page and bring the box into view (zooming in a little if fitted).
  useEffect(() => {
    if (!highlight) return
    if (highlight.page && highlight.page !== page) setPage(highlight.page)
    if (fit) { setFit(false); setScale((s) => Math.max(s, 0.9)) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlight])
  useEffect(() => {
    if (highlight && markRef.current) markRef.current.scrollIntoView({ block: 'center', inline: 'center' })
  }, [highlight, scale, pageSize])

  const box = highlight?.box_2d && (!highlight.page || highlight.page === page) ? highlight.box_2d : null

  if (error) return <div className="muted">Could not load drawing: {error}</div>
  return (
    <div className="pdf">
      <div className="toolbar">
        <button onClick={() => zoom(1 / 1.25)} title="Zoom out" aria-label="Zoom out">−</button>
        <span>{Math.round(scale * 100)}%</span>
        <button onClick={() => zoom(1.25)} title="Zoom in" aria-label="Zoom in">+</button>
        <button className={fit ? 'active' : ''} onClick={() => setFit(true)} title="Fit sheet to pane">Fit</button>
        {pdf?.numPages > 1 && (
          <>
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>sheet {page}/{pdf.numPages}</span>
            <button disabled={page >= pdf.numPages} onClick={() => setPage(page + 1)}>›</button>
          </>
        )}
        {highlight && (
          <span className="hl-chip" title={highlight.label}>
            Highlighting: {String(highlight.label || '').slice(0, 30)}
            <button onClick={onClearHighlight} aria-label="Clear highlight">✕</button>
          </span>
        )}
        <a href={url} target="_blank" rel="noreferrer">Open PDF</a>
      </div>
      <div className="pdf-scroll" ref={scrollRef}>
        <div className="sheet">
          <canvas ref={canvasRef} />
          {box && (
            <div
              ref={markRef}
              className="hl-box"
              style={{
                top: `${box[0] / 10}%`, left: `${box[1] / 10}%`,
                height: `${(box[2] - box[0]) / 10}%`, width: `${(box[3] - box[1]) / 10}%`,
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
