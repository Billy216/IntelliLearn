/**
 * IntelliLearn 共享内容渲染器
 *
 * 目标：把 AI 返回的 Markdown + LaTeX 文本安全地渲染成 HTML。
 *
 * 安全原则：
 *   1. 先转义 HTML，再做 Markdown 变换，绝不把未转义的模型输出塞进 innerHTML；
 *   2. 数学公式交给 KaTeX 渲染；KaTeX 不可用（离线/CDN 被拦）时，
 *      由调用方传入服务端生成的纯文本降级内容（reply_plain），
 *      保证任何情况下都不会把 LaTeX 源码直接显示给用户。
 *
 * 对外 API（挂在 window.ILRender 上）：
 *   escapeHtml(text)                  转义 HTML
 *   hasKatex()                        KaTeX 是否可用
 *   render(text, options)             返回 HTML 字符串
 *   renderInto(element, text, options) 渲染进指定元素
 *   options.plain                     无 KaTeX 时使用的纯文本降级内容
 *   options.streaming                 流式输出中（未闭合公式按普通文本处理）
 */
(function (global) {
    'use strict';

    // ======================== 基础工具 ========================

    function escapeHtml(text) {
        return String(text === null || text === undefined ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function hasKatex() {
        return !!(global.katex && typeof global.katex.renderToString === 'function');
    }

    // ======================== 数学公式处理 ========================

    var MATH_PLACEHOLDER_PREFIX = '\u0000MATH';
    var CODE_PLACEHOLDER_PREFIX = '\u0000CODE';

    /**
     * 抽出数学公式，替换成占位符，避免 Markdown 处理破坏公式内容。
     * 支持 $$...$$、\[...\]、$...$、\(...\)。
     */
    function extractMath(text, streaming, store) {
        var patterns = [
            { re: /\$\$([\s\S]+?)\$\$/g, display: true },
            { re: /\\\[([\s\S]+?)\\\]/g, display: true },
            { re: /\\\(([\s\S]+?)\\\)/g, display: false },
            { re: /\$([^\$\n]+?)\$/g, display: false }
        ];

        var result = text;

        patterns.forEach(function (pattern) {
            result = result.replace(pattern.re, function (match, body) {
                // 流式输出时公式可能只写了一半，此时不渲染，按普通文本处理
                if (streaming && body.indexOf('\\') === -1 && match.length < 3) {
                    return match;
                }

                var index = store.length;
                store.push({ latex: body, display: pattern.display });

                return MATH_PLACEHOLDER_PREFIX + index + '\u0000';
            });
        });

        return result;
    }

    /** 抽出围栏代码块，避免其中的内容被当作 Markdown 处理。 */
    function extractCodeBlocks(text, store) {
        return text.replace(
            /```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g,
            function (match, lang, code) {
                var index = store.length;
                store.push({ lang: lang || '', code: code });

                return CODE_PLACEHOLDER_PREFIX + index + '\u0000';
            }
        );
    }

    /** 把占位符还原成 KaTeX 渲染结果或降级文本。 */
    function restoreMath(html, store) {
        return html.replace(
            new RegExp(MATH_PLACEHOLDER_PREFIX + '(\\d+)\u0000', 'g'),
            function (match, index) {
                var item = store[Number(index)];

                if (!item) {
                    return '';
                }

                if (!hasKatex()) {
                    // 没有 KaTeX：不要把 LaTeX 源码直接展示出来，
                    // 交给调用方使用服务端准备好的纯文本降级内容。
                    return '<span class="math-fallback">'
                        + escapeHtml(simplifyLatex(item.latex))
                        + '</span>';
                }

                try {
                    return global.katex.renderToString(item.latex, {
                        displayMode: item.display,
                        throwOnError: false,
                        strict: false,
                        output: 'html'
                    });
                } catch (error) {
                    return '<code class="math-error">'
                        + escapeHtml(item.latex)
                        + '</code>';
                }
            }
        );
    }

    function restoreCodeBlocks(html, store) {
        return html.replace(
            new RegExp(CODE_PLACEHOLDER_PREFIX + '(\\d+)\u0000', 'g'),
            function (match, index) {
                var item = store[Number(index)];

                if (!item) {
                    return '';
                }

                return '<pre class="il-code"><code>'
                    + escapeHtml(item.code.replace(/\n$/, ''))
                    + '</code></pre>';
            }
        );
    }

    /**
     * 极简 LaTeX 降级：仅在 KaTeX 不可用时使用，
     * 目的是让公式仍然可读，而不是完整还原排版。
     */
    function simplifyLatex(latex) {
        var text = String(latex || '');

        // 分式必须最先处理：此时花括号还在，
        // 否则后面的去括号步骤会把 \frac{a}{b} 变成 "ab"。
        var fracPattern = /\\(?:d|t)?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}/;
        var guard = 0;

        while (fracPattern.test(text) && guard < 30) {
            text = text.replace(fracPattern, '($1)/($2)');
            guard += 1;
        }

        // 根号（含 n 次根）：\sqrt[3]{x} → ³√(x)，\sqrt{x} → √(x)
        text = text.replace(
            /\\sqrt\s*\[([^\]]*)\]\s*\{([^{}]*)\}/g,
            '$1√($2)'
        );
        text = text.replace(/\\sqrt\s*\{([^{}]*)\}/g, '√($1)');

        var replacements = [
            [/\\left|\\right/g, ''],
            [/\\dfrac|\\frac/g, ''],
            [/\\cdot/g, '·'],
            [/\\times/g, '×'],
            [/\\div/g, '÷'],
            [/\\pm/g, '±'],
            [/\\infty/g, '∞'],
            [/\\pi/g, 'π'],
            [/\\alpha/g, 'α'],
            [/\\beta/g, 'β'],
            [/\\gamma/g, 'γ'],
            [/\\theta/g, 'θ'],
            [/\\lambda/g, 'λ'],
            [/\\mu/g, 'μ'],
            [/\\sigma/g, 'σ'],
            [/\\omega/g, 'ω'],
            [/\\to|\\rightarrow/g, '→'],
            [/\\ge|\\geq/g, '≥'],
            [/\\le|\\leq/g, '≤'],
            [/\\neq|\\ne/g, '≠'],
            [/\\approx/g, '≈'],
            [/\\sum/g, 'Σ'],
            [/\\prod/g, 'Π'],
            [/\\int/g, '∫'],
            [/\\lim/g, 'lim'],
            [/\\mathrm\{([^{}]*)\}/g, '$1'],
            [/\\text\{([^{}]*)\}/g, '$1'],
            [/\\[a-zA-Z]+/g, ''],
            [/[{}$]/g, ''],
            [/\\,/g, ' ']
        ];

        replacements.forEach(function (pair) {
            text = text.replace(pair[0], pair[1]);
        });

        return text.replace(/\s+/g, ' ').trim();
    }

    // ======================== Markdown 渲染 ========================

    function renderInline(text) {
        var html = text;

        // 行内代码
        html = html.replace(/`([^`]+)`/g, function (match, code) {
            return '<code class="il-inline-code">' + code + '</code>';
        });

        // 加粗
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

        // 斜体（避免误伤 ** 已处理的情况）
        html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');

        // 删除线
        html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');

        return html;
    }

    function renderTable(lines) {
        var rows = lines.map(function (line) {
            return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
                .split('|')
                .map(function (cell) { return cell.trim(); });
        });

        if (rows.length < 2) {
            return '';
        }

        var head = rows[0];
        var body = rows.slice(2);

        var html = '<div class="il-table-wrap"><table class="il-table"><thead><tr>';

        head.forEach(function (cell) {
            html += '<th>' + renderInline(cell) + '</th>';
        });

        html += '</tr></thead><tbody>';

        body.forEach(function (row) {
            html += '<tr>';

            row.forEach(function (cell) {
                html += '<td>' + renderInline(cell) + '</td>';
            });

            html += '</tr>';
        });

        html += '</tbody></table></div>';

        return html;
    }

    function renderMarkdown(text) {
        var lines = escapeHtml(text).split('\n');
        var html = [];
        var index = 0;

        function flushParagraph(buffer) {
            if (!buffer.length) {
                return;
            }

            html.push(
                '<p>' + renderInline(buffer.join('<br>')) + '</p>'
            );

            buffer.length = 0;
        }

        var paragraph = [];

        while (index < lines.length) {
            var line = lines[index];
            var trimmed = line.trim();

            // 空行
            if (!trimmed) {
                flushParagraph(paragraph);
                index += 1;
                continue;
            }

            // 表格
            if (
                trimmed.indexOf('|') === 0
                && index + 1 < lines.length
                && /^\s*\|?[\s:-]+\|[\s:|-]*$/.test(lines[index + 1])
            ) {
                flushParagraph(paragraph);

                var tableLines = [];

                while (
                    index < lines.length
                    && lines[index].trim().indexOf('|') !== -1
                ) {
                    tableLines.push(lines[index]);
                    index += 1;
                }

                html.push(renderTable(tableLines));
                continue;
            }

            // 标题
            var heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);

            if (heading) {
                flushParagraph(paragraph);

                var level = Math.min(6, heading[1].length + 2);

                html.push(
                    '<h' + level + ' class="il-h">'
                    + renderInline(heading[2])
                    + '</h' + level + '>'
                );

                index += 1;
                continue;
            }

            // 分隔线
            if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
                flushParagraph(paragraph);
                html.push('<hr class="il-hr">');
                index += 1;
                continue;
            }

            // 引用
            if (trimmed.indexOf('&gt;') === 0) {
                flushParagraph(paragraph);

                var quoteLines = [];

                while (
                    index < lines.length
                    && lines[index].trim().indexOf('&gt;') === 0
                ) {
                    quoteLines.push(
                        lines[index].trim().replace(/^&gt;\s?/, '')
                    );
                    index += 1;
                }

                html.push(
                    '<blockquote class="il-quote">'
                    + renderInline(quoteLines.join('<br>'))
                    + '</blockquote>'
                );

                continue;
            }

            // 列表
            var isUl = /^\s*[-*+]\s+/.test(line);
            var isOl = /^\s*\d+[.)]\s+/.test(line);

            if (isUl || isOl) {
                flushParagraph(paragraph);

                var tag = isUl ? 'ul' : 'ol';
                var items = [];

                while (index < lines.length) {
                    var candidate = lines[index];

                    var match = isUl
                        ? /^\s*[-*+]\s+(.*)$/.exec(candidate)
                        : /^\s*\d+[.)]\s+(.*)$/.exec(candidate);

                    if (!match) {
                        break;
                    }

                    items.push('<li>' + renderInline(match[1]) + '</li>');
                    index += 1;
                }

                html.push(
                    '<' + tag + ' class="il-list">'
                    + items.join('')
                    + '</' + tag + '>'
                );

                continue;
            }

            paragraph.push(trimmed);
            index += 1;
        }

        flushParagraph(paragraph);

        return html.join('\n');
    }

    // ======================== 对外接口 ========================

    /**
     * 渲染文本为 HTML 字符串。
     *
     * @param {string} text 原始文本（可能含 Markdown 与 LaTeX）
     * @param {object} [options] { plain: 无 KaTeX 时的降级文本, streaming: 是否流式中 }
     * @returns {string} HTML
     */
    function render(text, options) {
        options = options || {};

        var source = String(text === null || text === undefined ? '' : text);
        var plain = options.plain;

        // KaTeX 不可用且提供了服务端纯文本降级内容时，直接用降级内容
        if (!hasKatex() && plain) {
            source = String(plain);
        }

        var mathStore = [];
        var codeStore = [];

        source = extractCodeBlocks(source, codeStore);
        source = extractMath(source, !!options.streaming, mathStore);

        var html = renderMarkdown(source);

        html = restoreMath(html, mathStore);
        html = restoreCodeBlocks(html, codeStore);

        return html;
    }

    /**
     * 渲染进指定元素。
     *
     * @param {HTMLElement} element 目标元素
     * @param {string} text 原始文本
     * @param {object} [options] 同 render()
     */
    function renderInto(element, text, options) {
        if (!element) {
            return;
        }

        element.innerHTML = render(text, options);
    }

    global.ILRender = {
        escapeHtml: escapeHtml,
        hasKatex: hasKatex,
        render: render,
        renderInto: renderInto,
        simplifyLatex: simplifyLatex
    };
})(window);
