/**
 * render.js 单元测试（Node 环境，无需浏览器）
 *
 * 重点验证两件事：
 *   1. 安全性：模型输出/用户内容中的 HTML 必须被转义，不能形成注入；
 *   2. 公式：KaTeX 可用时渲染为公式，不可用时降级为可读纯文本，
 *      任何情况下都不能把 LaTeX 源码原样丢给用户。
 *
 * 运行：node tests/render_test.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const RENDER_PATH = path.join(__dirname, '..', 'static', 'js', 'render.js');
const source = fs.readFileSync(RENDER_PATH, 'utf8');

let passed = 0;
const failures = [];

function check(name, condition, detail) {
    if (condition) {
        passed += 1;
        console.log('  [PASS] ' + name);
    } else {
        failures.push(name + (detail ? ' :: ' + detail : ''));
        console.log('  [FAIL] ' + name + (detail ? '  ' + detail : ''));
    }
}

/** 构造一个沙箱环境并加载 render.js */
function loadRenderer(options) {
    options = options || {};

    const sandbox = {
        console: console,
        window: {}
    };

    if (options.katex) {
        // 用一个可预测的假 KaTeX 代替真实实现，便于断言
        sandbox.window.katex = {
            renderToString: function (latex, config) {
                return '<span class="katex-stub" data-display="'
                    + (config && config.displayMode ? '1' : '0')
                    + '">' + latex + '</span>';
            }
        };
    }

    vm.createContext(sandbox);
    vm.runInContext(source, sandbox);

    return sandbox.window.ILRender;
}

console.log('\n[1] 加载与基础 API');
const R = loadRenderer({ katex: true });
check('暴露 escapeHtml / render / renderInto / hasKatex',
    typeof R.escapeHtml === 'function'
    && typeof R.render === 'function'
    && typeof R.renderInto === 'function'
    && typeof R.hasKatex === 'function');
check('检测到 KaTeX', R.hasKatex() === true);

console.log('\n[2] HTML 转义（XSS 防护）');
check('转义尖括号与引号',
    R.escapeHtml('<img src=x onerror="alert(1)">')
    === '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');

const xssCases = [
    '<script>alert(1)</script>',
    '<img src=x onerror=alert(1)>',
    '<svg/onload=alert(1)>',
    '"><iframe src=javascript:alert(1)>',
    '<a href="javascript:alert(1)">click</a>'
];

xssCases.forEach(function (payload) {
    const html = R.render(payload);
    const hasRawTag = /<(script|img|svg|iframe|a[\s>])/i.test(html);

    check('注入载荷被转义：' + payload.slice(0, 28), !hasRawTag, html.slice(0, 90));
});

console.log('\n[3] Markdown 渲染');
const md = R.render('## 标题\n\n- 第一项\n- 第二项\n\n**加粗**与`代码`\n\n| A | B |\n| --- | --- |\n| 1 | 2 |');

check('渲染二级标题', md.indexOf('<h4') !== -1 || md.indexOf('<h2') !== -1);
check('渲染无序列表', md.indexOf('<ul') !== -1 && md.indexOf('<li>第一项</li>') !== -1);
check('渲染加粗', md.indexOf('<strong>加粗</strong>') !== -1);
check('渲染行内代码', md.indexOf('<code class="il-inline-code">代码</code>') !== -1);
check('渲染表格', md.indexOf('<table') !== -1 && md.indexOf('<th>A</th>') !== -1);

console.log('\n[4] 数学公式（KaTeX 可用）');
const inlineMath = R.render('求 $\\frac{1}{2}$ 的值');
check('行内公式交给 KaTeX 渲染',
    inlineMath.indexOf('katex-stub') !== -1
    && inlineMath.indexOf('\\frac') !== -1);

const displayMath = R.render('$$\\int_0^1 x^2\\,\\mathrm{d}x$$');
check('独立公式使用 display 模式',
    displayMath.indexOf('data-display="1"') !== -1);

check('公式内的 Markdown 字符不被误处理',
    R.render('$a*b*c$').indexOf('katex-stub') !== -1);

console.log('\n[5] 数学公式（KaTeX 不可用时的降级）');
const RN = loadRenderer({ katex: false });
check('未检测到 KaTeX', RN.hasKatex() === false);

const fallback = RN.render('结果是 $\\frac{a}{b}$ 和 $\\sqrt{2}$');
check('分式降级为 (a)/(b)', fallback.indexOf('(a)/(b)') !== -1, fallback);
check('根号降级为 √', fallback.indexOf('√(2)') !== -1, fallback);
check('降级后不残留 LaTeX 反斜杠命令',
    fallback.indexOf('\\frac') === -1 && fallback.indexOf('\\sqrt') === -1,
    fallback);
check('降级内容被包在 math-fallback 中', fallback.indexOf('math-fallback') !== -1);

console.log('\n[6] 服务端纯文本降级优先');
const withPlain = RN.render('$\\frac{a}{b}$', { plain: 'a/b （服务端降级文本）' });
check('提供 plain 时使用服务端降级文本',
    withPlain.indexOf('服务端降级文本') !== -1,
    withPlain);

console.log('\n[7] 代码块与流式容错');
const code = R.render('```python\nprint("hi")\n```');
check('围栏代码块渲染为 pre', code.indexOf('<pre class="il-code">') !== -1);
check('代码内容被转义', code.indexOf('&quot;hi&quot;') !== -1 || code.indexOf('"hi"') !== -1);

const streaming = R.render('计算中 $x^2', { streaming: true });
check('流式中未闭合公式不报错', typeof streaming === 'string' && streaming.length > 0);

const empty = R.render('');
check('空文本返回空字符串', empty === '');

const nullSafe = R.render(null);
check('null 输入不抛异常', nullSafe === '');

console.log('\n' + '='.repeat(56));
console.log('通过 ' + passed + ' 项，失败 ' + failures.length + ' 项');

if (failures.length) {
    console.log('\n失败明细：');
    failures.forEach(function (item) { console.log('  - ' + item); });
}

console.log('='.repeat(56));

process.exit(failures.length ? 1 : 0);
