import { useEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

export default function PdfViewer({ url }) {
  const canvasRef = useRef(null)
  const [pdf, setPdf] = useState(null)
  const [page, setPage] = useState(1)
  const [scale, setScale] = useState(1)
  const [error, setError] = useState(null)

  useEffect(() => {
    setPdf(null); setPage(1); setError(null)
    const task = pdfjs.getDocument(url)
    task.promise.then(setPdf).catch((e) => setError(e.message))
    return () => task.destroy()
  }, [url])

  useEffect(() => {
    if (!pdf) return
    let renderTask
    pdf.getPage(page).then((p) => {
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
    })
    return () => renderTask?.cancel()
  }, [pdf, page, scale])

  if (error) return <div className="muted">Could not load drawing: {error}</div>
  return (
    <div className="pdf">
      <div className="toolbar">
        <button onClick={() => setScale((s) => Math.max(0.25, s - 0.25))}>−</button>
        <span>{Math.round(scale * 100)}%</span>
        <button onClick={() => setScale((s) => s + 0.25)}>+</button>
        {pdf?.numPages > 1 && (
          <>
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
            <span>sheet {page}/{pdf.numPages}</span>
            <button disabled={page >= pdf.numPages} onClick={() => setPage(page + 1)}>›</button>
          </>
        )}
        <a href={url} target="_blank" rel="noreferrer">Open PDF</a>
      </div>
      <div className="pdf-scroll"><canvas ref={canvasRef} /></div>
    </div>
  )
}
