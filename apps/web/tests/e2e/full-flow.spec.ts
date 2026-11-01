import { expect, test, type Page } from '@playwright/test'
import { stat } from 'node:fs/promises'
import path from 'node:path'

function watchConsole(page: Page): string[] {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  return errors
}

async function expectNoOverflow(page: Page): Promise<void> {
  const evidence = await page.evaluate(() => {
    const viewport = window.innerWidth
    const offenders = [...document.querySelectorAll<HTMLElement>('body *')].flatMap((element) => {
      const box = element.getBoundingClientRect()
      if (!box.width || (box.left >= 0 && box.right <= viewport) || element.closest('.table-scroll')) return []
      return [{ tag: element.tagName.toLowerCase(), class: element.className, left: Math.round(box.left), right: Math.round(box.right) }]
    })
    return { viewport, documentWidth: document.documentElement.scrollWidth, offenders: offenders.slice(0, 12) }
  })
  expect(evidence.documentWidth, JSON.stringify(evidence.offenders)).toBeLessThanOrEqual(evidence.viewport)
}

async function approveAndStart(page: Page): Promise<void> {
  await expect(page.getByRole('heading', { name: '确认本次检查' })).toBeVisible()
  await page.getByRole('button', { name: '批准规范并开始检查' }).click()
  const dialog = page.getByRole('dialog', { name: '批准规范并开始检查？' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveCSS('opacity', '1')
  await dialog.getByRole('button', { name: '批准并检查', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('.job-banner progress')).toBeVisible()
  await expect(page.locator('.job-banner progress')).toHaveAttribute('max', '100')
}

async function selectTwoIssues(page: Page, mobile = false): Promise<void> {
  if (mobile) await page.locator('.mobile-workspace-nav').getByRole('button', { name: /^问题/ }).click()
  await page.getByRole('checkbox', { name: '选择 I-01 纳入修复' }).check()
  await page.getByRole('checkbox', { name: '选择 I-02 纳入修复' }).check()
  await expect(page.locator('.selection-toolbar')).toContainText('已选 2 项')
  if (mobile) await expect(page.locator('.mobile-plan-bar')).toContainText('已选 2 项')
}

async function approveAndExecute(page: Page): Promise<void> {
  await expect(page.locator('.operation-list > li')).toHaveCount(2)
  await page.reload()
  await expect(page.locator('.operation-list > li')).toHaveCount(2)
  await page.getByRole('button', { name: '批准修复计划' }).click()
  await page.getByRole('button', { name: '批准计划', exact: true }).click()
  await expect(page.getByRole('button', { name: '执行修复', exact: true })).toBeEnabled()
  await page.reload()
  await expect(page.getByRole('button', { name: '执行修复', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '执行修复' }).click()
  await page.getByRole('button', { name: '提交执行' }).click()
  await expect(page.locator('.execution-progress progress')).toBeVisible()
  await expect(page.locator('.execution-progress progress')).toHaveAttribute('max', '100')
  await expect(page.getByText('候选修订版已生成', { exact: true })).toBeVisible({ timeout: 180_000 })
  await expect(page.locator('.page-heading .status')).toHaveText('已完成')
}

async function openResultView(page: Page, name: '对照' | '下载'): Promise<void> {
  await page.getByRole('button', { name, exact: true }).click()
  await expect(page.locator('.result-view-nav button').filter({ hasText: name })).toHaveAttribute('aria-pressed', 'true')
}

async function verifyRenderDetails(page: Page): Promise<void> {
  const toggle = page.getByRole('button', { name: /渲染环境详情/ })
  await toggle.click()
  await expect(page.locator('.warning-detail').first()).toContainText('Render environment:')
  await toggle.click()
  await expect(page.locator('.warning-detail')).toHaveCount(0)
}

test('real demo inspection, approved repair, verification and downloads', async ({ page }, testInfo) => {
  const consoleErrors = watchConsole(page)
  await page.goto('/')
  await expect(page.locator('.home-hero')).toBeVisible()
  await page.getByRole('button', { name: '使用真实演示文档' }).click()
  await expect(page).toHaveURL(/\/inspection\?setup=1$/)
  const demoToast = page.locator('.toast').filter({ hasText: '演示工作区已就绪' })
  await expect(demoToast).toBeVisible()
  await demoToast.getByRole('button', { name: '关闭通知' }).click()
  await expect(demoToast).toHaveCount(0)
  await approveAndStart(page)
  await expect(page.locator('.toast').filter({ hasText: '规则集已批准' })).toBeVisible()
  await expect(page.locator('.metric').filter({ hasText: '明确违规' }).first()).toContainText('20', { timeout: 180_000 })
  await expect(page.locator('.pdf-page')).toHaveCount(10)
  await expect(page.getByRole('spinbutton', { name: '页码', exact: true })).toHaveValue('5')
  await expect.poll(() => page.locator('.pdf-scroll').evaluate((container) => {
    const target = container.querySelector('[data-page-number="5"]')
    return target ? Math.abs(target.getBoundingClientRect().top - container.getBoundingClientRect().top - 16) : 9999
  })).toBeLessThan(4)
  await verifyRenderDetails(page)
  await selectTwoIssues(page)

  const inspectionPosts: string[] = []
  page.on('request', (request) => {
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/inspections')) inspectionPosts.push(request.url())
  })
  await page.getByRole('button', { name: '刷新结果' }).click()
  await expect(page.locator('.toast').filter({ hasText: '检查结果已刷新' })).toBeVisible()
  expect(inspectionPosts).toEqual([])
  await expect(page.getByRole('checkbox', { name: '选择 I-01 纳入修复' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '选择 I-02 纳入修复' })).toBeChecked()
  await page.locator('.selection-toolbar').getByRole('button', { name: '生成修复计划' }).click()
  await approveAndExecute(page)
  await page.getByRole('link', { name: '查看复检与下载' }).click()
  await expect(page.getByRole('heading', { name: '验证通过' })).toBeVisible()
  await verifyRenderDetails(page)
  await expect(page.locator('.metric').filter({ hasText: '复检已解决' }).first()).toContainText('2')
  await expect(page.locator('.metric').filter({ hasText: '选中项未解决' }).first()).toContainText('0')

  await openResultView(page, '对照')
  await page.getByRole('combobox', { name: '缩放比例' }).first().selectOption('1.25')
  await page.getByRole('button', { name: '顺时针旋转 90 度' }).first().click()
  const revisedDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: '下载修订版' }).click()
  const docx = await revisedDownload
  const docxPath = testInfo.outputPath('repaired.docx')
  await docx.saveAs(docxPath)
  expect((await stat(docxPath)).size).toBeGreaterThan(10_000)

  await openResultView(page, '下载')
  const jsonDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'JSON 报告' }).click()
  const json = await jsonDownload
  const jsonPath = testInfo.outputPath('report.json')
  await json.saveAs(jsonPath)
  expect((await stat(jsonPath)).size).toBeGreaterThan(500)

  const markdownDownload = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Markdown 报告' }).click()
  const markdown = await markdownDownload
  await markdown.saveAs(path.join(testInfo.outputDir, 'verification.md'))
  expect((await stat(path.join(testInfo.outputDir, 'verification.md'))).size).toBeGreaterThan(500)

  await page.locator('.artifact-details summary').click()
  const pdfDownload = page.waitForEvent('download')
  await page.locator('.artifact-table tr').filter({ hasText: 'PDF 预览' }).getByRole('button', { name: '下载文件' }).click()
  const pdf = await pdfDownload
  const pdfPath = testInfo.outputPath('verification.pdf')
  await pdf.saveAs(pdfPath)
  expect((await stat(pdfPath)).size).toBeGreaterThan(1_000)

  await expect(page.getByRole('button', { name: '减少动效' })).toHaveCount(0)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expect(page.locator('.motion-page')).toHaveCSS('animation-name', 'none')
  await page.reload()
  await expect(page.locator('.motion-page')).toHaveCSS('animation-name', 'none')
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await expect(page.locator('.motion-page')).not.toHaveCSS('animation-name', 'none')
  await expectNoOverflow(page)
  expect(consoleErrors).toEqual([])
})

test('default preset upload reaches real inspection confirmation', async ({ page }) => {
  const consoleErrors = watchConsole(page)
  await page.goto('/#/new')
  await expect(page.locator('input[name="preset_choice"][value="general_report"]')).toBeChecked()
  await page.getByLabel('原稿 DOCX 文件').setInputFiles(path.resolve(process.cwd(), '../../examples/alinea-demo.docx'))
  await expect(page.getByLabel('项目名称')).toHaveValue('alinea-demo')
  await page.getByRole('button', { name: '上传并继续' }).click()
  await expect(page).toHaveURL(/\/inspection\?setup=1$/)
  await expect(page.locator('.setup-facts')).toContainText('通用报告', { timeout: 30_000 })
  await approveAndStart(page)
  await expect(page.locator('.metric').filter({ hasText: '明确违规' }).first()).toContainText(/\d+/, { timeout: 180_000 })
  await expect(page.locator('.pdf-page')).toHaveCount(10)
  await expectNoOverflow(page)
  expect(consoleErrors).toEqual([])
})

test('mobile workflow remains usable from upload to results', async ({ page }) => {
  const consoleErrors = watchConsole(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expect(page.locator('.motion-page')).toHaveCSS('animation-name', 'none')
  await expect(page.getByRole('button', { name: '减少动效' })).toHaveCount(0)
  await page.getByRole('link', { name: '新建检查' }).click()
  await expect(page).toHaveURL(/\/new$/)
  await expect(page.locator('input[name="preset_choice"][value="general_report"]')).toBeChecked()
  await page.getByLabel('原稿 DOCX 文件').setInputFiles(path.resolve(process.cwd(), '../../examples/alinea-demo.docx'))
  await expect(page.getByLabel('项目名称')).toHaveValue('alinea-demo')
  await page.getByRole('button', { name: /更多选项/ }).click()
  await expect(page.getByRole('textbox', { name: '服务端预设 ID' })).toHaveValue('general_report')
  await page.getByRole('button', { name: /更多选项/ }).click()
  await expect(page.getByRole('textbox', { name: '服务端预设 ID' })).toHaveCount(0)
  await expect(page.locator('.motion-page')).toHaveCSS('animation-name', 'none')
  await expectNoOverflow(page)

  await page.getByRole('link', { name: 'Alinea 首页' }).click()
  await page.getByRole('button', { name: '使用真实演示文档' }).click()
  await expect(page).toHaveURL(/\/inspection\?setup=1$/)
  await expect(page.locator('.workflow-rail li')).toHaveCount(4)
  await expect(page.locator('[aria-current="step"]')).toHaveAttribute('aria-label', '检查与选择')
  await page.getByRole('link', { name: '任务记录' }).click()
  await expect(page.getByRole('heading', { name: '任务记录', exact: true })).toBeVisible()
  await expectNoOverflow(page)
  const headerButtons = await page.locator('.header-nav').evaluate((element) =>
    [...element.querySelectorAll('a, button')].map((item) => {
      const box = item.getBoundingClientRect()
      return { width: box.width, left: box.left, right: box.right }
    }),
  )
  expect(headerButtons.every((item) => item.width > 60 && item.left >= 0 && item.right <= 390)).toBe(true)

  await page.getByRole('link', { name: '检查与选择' }).click()
  await approveAndStart(page)
  await expect(page.locator('.metric').filter({ hasText: '明确违规' }).first()).toContainText('20', { timeout: 180_000 })
  await selectTwoIssues(page, true)
  await page.locator('.mobile-plan-bar').getByRole('button', { name: '生成修复计划' }).click()
  await approveAndExecute(page)
  await page.getByRole('link', { name: '查看复检与下载' }).click()
  await expect(page.getByRole('heading', { name: '验证通过' })).toBeVisible()
  await openResultView(page, '对照')
  await expect(page.locator('.compare-card')).toHaveCount(2)
  await openResultView(page, '下载')
  await expect(page.getByRole('heading', { name: '下载文件', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '下载修订版' })).toBeVisible()
  await expectNoOverflow(page)
  expect(consoleErrors).toEqual([])
})
