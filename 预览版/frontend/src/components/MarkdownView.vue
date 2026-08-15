<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import katex from 'katex'
import 'katex/dist/katex.min.css'

const props = defineProps<{ content: string }>()

const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

// 代码块渲染：专门的代码框 + 右上角复制按钮
const defaultFence = md.renderer.rules.fence || ((tokens: any, idx: number, options: any, env: any, self: any) => self.renderToken(tokens, idx, options))
md.renderer.rules.fence = (tokens: any, idx: number, options: any, env: any, self: any) => {
  const token = tokens[idx]
  const lang = (token.info || '').trim().split(/\s+/)[0] || ''
  // SVG 示意图：内联渲染（几何题配图）
  if (lang.toLowerCase() === 'svg') {
    let svg = token.content
      .replace(/<script[\s\S]*?<\/script>/gi, '')
      .replace(/\son\w+\s*=\s*["'][^"']*["']/gi, '')
    return `<div class="svg-wrap">${svg}</div>`
  }
  const codeId = 'cb' + Math.random().toString(36).slice(2, 8)
  const content = md.utils.escapeHtml(token.content)
  return `<div class="code-block" data-id="${codeId}">
    <div class="code-head"><span>${md.utils.escapeHtml(lang || 'code')}</span><button class="copy-btn" onclick="copyCode('${codeId}', this)">复制</button></div>
    <pre><code>${content}</code></pre>
  </div>`
}

// 全局复制函数（单例绑定）
if (!(window as unknown as Record<string, unknown>).__recallCopyBound) {
  ;(window as unknown as Record<string, unknown>).__recallCopyBound = true
  ;(window as unknown as Record<string, unknown>).copyCode = (id: string, btn: HTMLElement) => {
    const el = document.querySelector(`[data-id="${id}"] pre`)
    const text = el?.textContent || ''
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        btn.textContent = '✅ 已复制'
        setTimeout(() => { btn.textContent = '复制' }, 1500)
      }).catch(() => fallbackCopy(text, btn))
    } else {
      fallbackCopy(text, btn)
    }
  }
}

function fallbackCopy(text: string, btn: HTMLElement) {
  const ta = document.createElement('textarea')
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  btn.textContent = '✅ 已复制'
  setTimeout(() => { btn.textContent = '复制' }, 1500)
}

// AI 可能输出 \\(...\\) / \\[...\\] 定界符（markdown 会吞反斜杠），且常带空格（如 $ x $）
// 统一归一化：定界符 → $/$$，并去除 $...$ 内部首尾空格
function normalizeLatex(src: string): string {
  return src
    .replace(/\\\[/g, '$$').replace(/\\\]/g, '$$')
    .replace(/\\\(/g, '$').replace(/\\\)/g, '$')
    .replace(/\$\$[ \t]*([\s\S]*?)[ \t]*\$\$/g, (_m, c: string) => `$$${c.trim()}$$`)
    .replace(/\$[ \t]+([\s\S]*?)[ \t]+\$/g, (_m, c: string) => `$${c.trim()}$`)
}

const KATEX_TAG = (i: number) => `@@KATEX${i}@@`

function readableMathFallback(tex: string): string {
  let out = tex.trim()
  for (let i = 0; i < 4; i++) {
    out = out.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)')
    out = out.replace(/\\sqrt\{([^{}]*)\}/g, '√($1)')
    out = out.replace(/\\(?:text|mathrm|operatorname)\{([^{}]*)\}/g, '$1')
  }
  return out
    .replace(/\\left|\\right/g, '')
    .replace(/\\cdot/g, '·').replace(/\\times/g, '×').replace(/\\pm/g, '±')
    .replace(/\\leqslant|\\leq/g, '≤').replace(/\\geqslant|\\geq/g, '≥').replace(/\\neq/g, '≠')
    .replace(/\\infty/g, '∞').replace(/\\to/g, '→').replace(/\\partial/g, '∂')
    .replace(/\\[a-zA-Z]+/g, '□')
    .replace(/[{}]/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim() || '公式格式待修正'
}

function renderMath(tex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(tex.trim(), { displayMode, throwOnError: true, strict: 'ignore' })
  } catch {
    const fallback = md.utils.escapeHtml(readableMathFallback(tex))
    return `<span class="math-fallback" title="公式格式待修正">${fallback}</span>`
  }
}

// 常见裸 LaTeX 命令（AI 偶尔不按格式用 $ 包裹，兜底识别）
const BARE_LATEX_RE = /(?<![$\\])\\(frac|int|sum|lim|sqrt|Delta|times|cdot|infty|to|leq|geq|neq|pm|partial|mathrm|text|quad|qquad|left|right|alpha|beta|gamma|delta|epsilon|zeta|eta|theta|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|phi|chi|psi|omega|Gamma|Lambda|Sigma|Phi|Psi|Omega|Xi|bar|hat|vec|dot|overline|max|min|ln|log|sin|cos|tan|det|begin|end|cases|leqslant|geqslant|textbf|ldots)[^，。；、\n$]*/g

// 裸 LaTeX 环境块（\begin{cases}...\end{cases}，无 $ 包裹）
const BARE_ENV_RE = /\\begin\{[a-zA-Z*]+\}[\s\S]*?\\end\{[a-zA-Z*]+\}/g
// 未知或损坏的裸命令也必须被接管，不能以 \badcommand 的源码形式泄露到页面。
const RESIDUAL_LATEX_RE = /(?<![$\\])\\[A-Za-z]+(?:\{[^{}\n]*\})*/g

// 自实现公式提取：顺序很重要——① 先提取已有 $...$/$$...$$ 的公式 → ② 再兜底裸 LaTeX 命令
// 最后交给 markdown-it 渲染，回填 katex HTML
// AI 常用单个 \n 分段（Markdown 规范要求空行才分段）——渲染前把“普通文本行”之间的单换行升级为空行，
// 让回答自动分好段；代码块/列表/公式行保持原样，避免破坏结构。
function normalizeBlocks(src: string): string {
  // 保护代码块
  const blocks: string[] = []
  let s = src.replace(/```[\s\S]*?(?:```|$)/g, (m) => {
    blocks.push(m)
    return `\u0000CB${blocks.length - 1}\u0000`
  })
  const lines = s.split('\n')
  const isSpecial = (l: string) => /^\s*(?:[-*]|\d+[.)]|>|\||\$\$|\u0000CB|$)/.test(l)
  const isHeading = (l: string) => /^\s{0,3}#{1,6}\s+/.test(l)
  const isHr = (l: string) => /^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$/.test(l)
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = lines[i + 1]
    // 标题/水平线行：前面必须是空行（Markdown 规定），否则补一个，保证 ###/---- 生效
    if ((isHeading(line) || isHr(line)) && out.length > 0 && out[out.length - 1].trim() !== '') {
      out.push('')
    }
    out.push(line)
    if (next !== undefined && !isSpecial(line) && !isSpecial(next) && !isHeading(next) && line.trim() && next.trim()) {
      out.push('')
    }
  }
  s = out.join('\n')
  return s.replace(/\u0000CB(\d+)\u0000/g, (_m, i: string) => blocks[Number(i)] ?? '')
}

// 流式输出半成品补全：未闭合的 $/$$/\(/``` 自动闭合，避免过程闪现乱码，格式一步到位
function closeUnclosed(src: string): string {
  let s = src
  // 1) 未闭合代码块
  if ((s.split('```').length - 1) % 2 === 1) s += '\n```'
  // 2) 未闭合 \( 定界符
  const lparen = (s.match(/\\\(/g) || []).length
  const rparen = (s.match(/\\\)/g) || []).length
  if (lparen > rparen) s += '\\)'
  // 3) 未闭合 $ / $$
  let out = ''
  let inMath = false
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '\\') { out += ch + (s[i + 1] || ''); i++; continue }
    if (ch === '$') {
      if (s[i + 1] === '$') { out += '$$'; i++; inMath = !inMath; continue }
      out += '$'
      inMath = !inMath
      continue
    }
    out += ch
  }
  if (inMath) out += '$'
  return out
}

function renderWithKatex(src: string): string {
  const parts: string[] = []
  // 流式半成品补全（未闭合 $/代码块等），保证实时输出过程格式正确
  src = closeUnclosed(src)
  // 仅移除安全的简单下标（∬_S → ∬S）；复杂下标必须保留花括号结构，避免破坏公式。
  src = src
    .replace(/([∬∫∮∑∏∭])_\{([A-Za-z0-9]+)\}/g, '$1$2')
    .replace(/([∬∫∮∑∏∭])_([A-Za-z0-9]+)/g, '$1$2')
  // 只恢复确定由 JSON 未转义命令造成的控制字符（例如 \frac → 换页符 + rac）。
  // 普通 Tab/回车必须保持为文本空白，不能被错误显示成 \t / \r。
  src = src
    .replace(/\u000crac/g, '\\frac').replace(/\u0008ar/g, '\\bar')
    .replace(/\u0008eta/g, '\\beta').replace(/\u0008egin/g, '\\begin')
    .replace(/\u000b(?:ec|dots)/g, (m) => `\\v${m.slice(1)}`)
    .replace(/\u0007lpha/g, '\\alpha')
    .replace(/\t(?:ext|imes|an|heta|o)/g, (m) => `\\t${m.slice(1)}`)
    .replace(/\r(?:ight|ho)/g, (m) => `\\r${m.slice(1)}`)
    .replace(/[\u0000-\u0007\u000b-\u000c\u000e-\u001f]/g, ' ')
  let text = normalizeBlocks(src)
  text = normalizeLatex(text)
  // 1) 独立公式 $$...$$
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_m, c: string) => {
    parts.push(renderMath(c, true))
    return KATEX_TAG(parts.length - 1)
  })
  // 2) 行内公式 $...$（至少 1 个字符，避免误伤孤立 $）
  text = text.replace(/\$([\s\S]+?)\$/g, (_m, c: string) => {
    parts.push(renderMath(c, false))
    return KATEX_TAG(parts.length - 1)
  })
  // 2.5) 裸 LaTeX 环境块（\begin{cases}...\end{cases}，无 $ 包裹）整体渲染
  text = text.replace(BARE_ENV_RE, (m: string) => {
    parts.push(renderMath(m, true))
    return KATEX_TAG(parts.length - 1)
  })
  // 3) 兜底：剩余文本中的裸 LaTeX 命令（此时不会有 $ 干扰，直接包裹并提取）
  text = text.replace(BARE_LATEX_RE, (m: string) => {
    parts.push(renderMath(m, false))
    return KATEX_TAG(parts.length - 1)
  })
  // 3.25) 最终接管未知/损坏的裸 LaTeX 命令，确保不会以源码出现在页面。
  text = text.replace(RESIDUAL_LATEX_RE, (m: string) => {
    parts.push(renderMath(m, false))
    return KATEX_TAG(parts.length - 1)
  })
  // 3.5) 纯文本分数：1/n、3/4、a/b → \frac{}{}（跳过日期 2026/08、文件名 jpg/png 等）
  text = text.replace(/(?<![A-Za-z0-9:])(\d{1,4}|[a-zA-Z])\/([a-zA-Z0-9]{1,6})(?![A-Za-z0-9])/g, (m: string, a: string, b: string) => {
    if (/^\d{4}$/.test(a) && /^\d{1,2}$/.test(b)) return m  // 日期如 2026/08
    parts.push(renderMath(`\\frac{${a}}{${b}}`, false))
    return KATEX_TAG(parts.length - 1)
  })
  // 4) 整段表达式兜底：遇到幂/下标标记（x^2、a_n）时，向两侧扩展到完整数学表达式，整体用 TeX 渲染
  //    例如 f(x)=x^2−4x+3 会整体渲染为斜体公式，而不是只渲染 x²
  text = extractExpr(text, parts)
  const html = md.render(text)
  return html.replace(/@@KATEX(\d+)@@/g, (_m, i: string) => parts[Number(i)] ?? '')
}

// 数学表达式允许的字符（ASCII 数学符号 + 常见 Unicode 数学符号）
const EXPR_BLOCK_RE = /[^A-Za-z0-9()\[\]{}=\+\-−×÷±≤≥<>\.\^_\sΔ∑∫√π∞μγαβθλ]/u

function extractExpr(text: string, parts: string[]): string {
  const MARK = /[A-Za-z0-9)](\^\{?[0-9-]+\}?|\_\{?[A-Za-z0-9]+\}?)/g
  let out = ''
  let last = 0
  let m: RegExpExecArray | null
  MARK.lastIndex = 0
  while ((m = MARK.exec(text))) {
    // 已被前面表达式覆盖的匹配直接跳过（避免同一段重复渲染）
    if (m.index < last) continue
    let l = m.index
    while (l > 0 && !EXPR_BLOCK_RE.test(text[l - 1])) l--
    let r = m.index + m[0].length
    while (r < text.length && !EXPR_BLOCK_RE.test(text[r])) r++
    while (l < r && text[l] === ' ') l++
    while (r > l && text[r - 1] === ' ') r--
    const expr = text.slice(l, r)
    if (expr.length > 1) {
      out += text.slice(last, l) + KATEX_TAG(parts.length)
      parts.push(renderMath(expr, false))
      last = r
    }
  }
  out += text.slice(last)
  return out
}

const html = computed(() => renderWithKatex(props.content || ''))
</script>

<template>
  <div class="md-view" v-html="html" />
</template>

<style scoped>
.md-view { font-size: 15px; line-height: 1.8; }
.md-view :deep(p) { margin: 0.55em 0; }
/* 单个换行（AI 未用空行分段时）也产生间距，避免行与行挤在一起 */
.md-view :deep(br) { display: block; content: ''; margin: 0.35em 0; }
.md-view :deep(h1), .md-view :deep(h2), .md-view :deep(h3) { margin: 0.7em 0 0.35em; font-weight: 600; }
.md-view :deep(ul), .md-view :deep(ol) { padding-left: 1.5em; margin: 0.4em 0; }
.md-view :deep(li) { margin: 0.3em 0; }
.md-view :deep(code) { background: #F5F5F7; padding: 1px 5px; border-radius: 4px; font-size: 0.92em; font-family: "SF Mono", Consolas, monospace; }
.md-view :deep(pre) { margin: 0; }
.md-view :deep(code) { font-family: "SF Mono", Consolas, monospace; }
/* 代码块专用框（深色 + 头部 + 复制按钮） */
.md-view :deep(.code-block) { background: #1D1D1F; border-radius: 10px; overflow: hidden; margin: 10px 0; border: 1px solid #2C2C2E; }
.md-view :deep(.code-head) { display: flex; justify-content: space-between; align-items: center; padding: 5px 12px; background: #2C2C2E; color: #AEAEB2; font-size: 11px; }
.md-view :deep(.copy-btn) { background: transparent; border: 1px solid #48484A; color: #AEAEB2; border-radius: 6px; padding: 1px 10px; font-size: 11px; cursor: pointer; transition: all .15s; }
.md-view :deep(.copy-btn:hover) { color: #fff; border-color: #6E6E73; }
.md-view :deep(.code-block pre) { padding: 12px 14px; overflow-x: auto; }
.md-view :deep(.code-block code) { background: none; color: #F5F5F7; font-size: 13px; line-height: 1.6; }
.md-view :deep(table) { border-collapse: collapse; margin: 0.5em 0; }
.md-view :deep(td), .md-view :deep(th) { border: 1px solid #E5E5EA; padding: 4px 10px; }
.md-view :deep(blockquote) { border-left: 3px solid #E5E5EA; padding-left: 10px; color: #6E6E73; margin: 0.4em 0; }
.md-view :deep(.svg-wrap) { margin: 10px 0; padding: 10px; background: #fff; border: 1px solid #E5E5EA; border-radius: 10px; text-align: center; }
.md-view :deep(.svg-wrap svg) { max-width: 100%; height: auto; }
.md-view :deep(.katex) { font-size: 1.05em; }
.md-view :deep(.math-fallback) { color: #8A5A00; background: #FFF8E8; border-bottom: 1px dashed #D99700; padding: 0 3px; }
</style>
