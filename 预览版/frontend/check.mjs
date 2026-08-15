import MarkdownIt from 'markdown-it'
import katex from 'katex'
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
function normalizeLatex(src) {
  return src.replace(/\\(/g, '$').replace(/\\)/g, '$')
    .replace(/\$[ \t]+([\s\S]*?)[ \t]+\$/g, (_m, c) => `$${c.trim()}$`)
}
const KATEX_TAG = (i) => `@@KATEX${i}@@`
function render(src) {
  const parts = []
  let text = normalizeLatex(src)
  text = text.replace(/\$([\s\S]+?)\$/g, (_m, c) => {
    parts.push(katex.renderToString(c.trim(), { displayMode: false, throwOnError: false }))
    return KATEX_TAG(parts.length - 1)
  })
  return md.render(text).replace(/@@KATEX(\d+)@@/g, (_m, i) => parts[Number(i)] ?? '')
}
const o = "B. \( f'(x)=x^{2}-4 \)"
const html = render(o)
// 可见渲染区 = katex-html 部分（去掉 katex-mathml 隐藏区）
const visible = html.split('<span class="katex-mathml">')[0]
const mathml = html.split('<span class="katex-mathml">')[1] || ''
console.log('可见区含 x^{2}:', visible.includes('x^{2}'), '（应为 false）')
console.log('隐藏区含 x^{2}:', mathml.includes('x^{2}'), '（应为 true，不影响显示）')
console.log('可见区含 x²上标结构 msup:', visible.includes('msup') || visible.includes('vlist'))
