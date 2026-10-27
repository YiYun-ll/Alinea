import type { Issue, LocationFragment } from '../types/contracts'

export type NormalizedRect = [number, number, number, number]

export interface ViewportRect {
  left: number
  top: number
  width: number
  height: number
}

export interface ViewportLike {
  convertToViewportPoint(x: number, y: number): number[]
}

function validRect(rect: number[]): rect is NormalizedRect {
  return rect.length === 4 && rect.every((value) => Number.isFinite(value) && value >= 0 && value <= 1) && rect[2] >= rect[0] && rect[3] >= rect[1]
}

export class PageCoordinateAdapter {
  constructor(
    private readonly pageView: number[],
    private readonly viewport: ViewportLike,
  ) {}

  toViewportRect(rect: number[], pageSizePt: Record<string, number>): ViewportRect | null {
    if (!validRect(rect) || this.pageView.length !== 4) return null
    const pageWidth = pageSizePt.width
    const pageHeight = pageSizePt.height
    if (!Number.isFinite(pageWidth) || !Number.isFinite(pageHeight) || pageWidth <= 0 || pageHeight <= 0) return null

    const [viewLeft, , viewRight, viewTop] = this.pageView
    const x0 = viewLeft + rect[0] * pageWidth
    const x1 = viewLeft + rect[2] * pageWidth
    const y0 = viewTop - rect[1] * pageHeight
    const y1 = viewTop - rect[3] * pageHeight
    if (viewRight < viewLeft) return null

    const points: Array<[number, number]> = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    const transformed = points.map(([x, y]) => this.viewport.convertToViewportPoint(x, y))
    if (transformed.some((point) => point.length < 2 || !Number.isFinite(point[0]) || !Number.isFinite(point[1]))) return null
    const xs = transformed.map((point) => point[0])
    const ys = transformed.map((point) => point[1])
    const left = Math.min(...xs)
    const top = Math.min(...ys)
    return { left, top, width: Math.max(...xs) - left, height: Math.max(...ys) - top }
  }
}

export interface IssueOverlay {
  issue: Issue
  fragment: LocationFragment
  rect: NormalizedRect
  rectIndex: number
}

export function overlaysForPage(issues: Issue[], revisionId: string, pageIndex: number, previewSha256?: string): IssueOverlay[] {
  const overlays: IssueOverlay[] = []
  for (const issue of issues) {
    const location = issue.location
    if (issue.revision_id !== revisionId || location.revision_id !== revisionId || location.status !== 'LOCATED') continue
    if (previewSha256 && location.preview_pdf_sha256 !== previewSha256) continue
    for (const fragment of location.fragments) {
      if (fragment.page_index !== pageIndex) continue
      fragment.rects_normalized.forEach((rect, rectIndex) => {
        if (validRect(rect)) overlays.push({ issue, fragment, rect, rectIndex })
      })
    }
  }
  return overlays
}
