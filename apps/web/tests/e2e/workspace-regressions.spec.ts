import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

test('dragged DOCX submits without requiring a second file-picker selection', async ({ page }) => {
  await page.goto('/#/new')
  const buffer = await readFile(path.resolve(process.cwd(), '../../examples/alinea-demo.docx'))
  const transfer = await page.evaluateHandle((bytes) => {
    const data = new DataTransfer()
    data.items.add(new File([new Uint8Array(bytes)], '拖入的文档.docx', { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
    return data
  }, [...buffer])
  await page.locator('.dropzone').dispatchEvent('drop', { dataTransfer: transfer })
  await expect(page.getByLabel('项目名称')).toHaveValue('拖入的文档')
  await expect(page.getByLabel('原稿 DOCX 文件')).toHaveValue('')
  await page.getByRole('button', { name: '上传并继续' }).click()
  await expect(page.getByRole('heading', { name: '确认本次检查' })).toBeVisible()
  await expect(page.locator('.setup-facts')).toContainText('拖入的文档')
})

test('oversized uploads are rejected before creating an empty project', async ({ page }) => {
  const creates: string[] = []
  page.on('request', (request) => { if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/projects')) creates.push(request.url()) })
  await page.goto('/#/new')
  await page.getByLabel('原稿 DOCX 文件').setInputFiles({ name: 'large.docx', mimeType: 'application/octet-stream', buffer: Buffer.alloc(16 * 1024 * 1024) })
  await page.getByRole('button', { name: '上传并继续' }).click()
  await expect(page.getByRole('alert')).toContainText('15 MiB')
  expect(creates).toEqual([])
})

test('a project read failure can recover through the reload button', async ({ page }) => {
  let failed = false
  await page.route('**/api/v1/projects/*', async (route) => {
    const request = route.request()
    if (!failed && request.method() === 'GET' && /\/projects\/[^/]+$/.test(new URL(request.url()).pathname)) {
      failed = true
      await route.fulfill({ status: 503, json: { detail: 'Temporary failure' } })
    } else await route.continue()
  })
  await page.goto('/')
  await page.getByRole('button', { name: '使用真实演示文档' }).click()
  await page.getByRole('button', { name: '重新加载', exact: true }).click()
  await expect(page.getByRole('heading', { name: '确认本次检查' })).toBeVisible()
  expect(failed).toBe(true)
})

test('creating a second demo does not reuse unsaved rules from the first project', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '使用真实演示文档' }).click()
  await expect(page.getByRole('heading', { name: '确认本次检查' })).toBeVisible()
  const firstUrl = page.url()
  await page.getByRole('link', { name: '查看或编辑完整规则' }).click()
  const ruleName = page.getByRole('textbox', { name: '规则名称', exact: true })
  await ruleName.fill('不应进入新项目的规则')
  await ruleName.blur()
  await page.getByRole('link', { name: 'Alinea 首页' }).click()
  await page.getByRole('button', { name: '使用真实演示文档' }).click()
  await expect(page.getByRole('heading', { name: '确认本次检查' })).toBeVisible()
  expect(page.url()).not.toBe(firstUrl)
  await page.getByRole('link', { name: '查看或编辑完整规则' }).click()
  await expect(page.getByRole('textbox', { name: '规则名称', exact: true })).not.toHaveValue('不应进入新项目的规则')
})
