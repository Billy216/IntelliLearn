/**
 * 个性化练习与复习卷 - practice.js
 *
 * 约定：
 *   1. 所有题目/答案/解析文本都先转义再插入 DOM；
 *      优先使用共享渲染器 window.ILRender（/static/js/render.js），
 *      渲染器不可用时退化为纯文本（textContent + <br>）。
 *   2. 任何接口失败都只展示服务端返回的 message 并提供「重试」，
 *      绝不渲染本地编造的题目或答案。
 *   3. 没有真实数据时展示中文空状态，不用占位假数据。
 */
(function () {
    'use strict';

    // ======================== 共享渲染器 ========================

    var RENDER = window.ILRender || null;

    /**
     * 转义 HTML。
     * TODO: 这里依赖共享渲染器 window.ILRender（/static/js/render.js）；
     *       文件缺失时使用下面的本地兜底实现。
     */
    function escapeHtml(text) {
        if (RENDER && typeof RENDER.escapeHtml === 'function') {
            return RENDER.escapeHtml(text);
        }

        return String(text === null || text === undefined ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    /**
     * 把含 Markdown / LaTeX 的文本渲染进元素。
     * 有 window.ILRender 时用它（内部已转义）；否则用纯文本 + 换行兜底。
     */
    function renderRich(element, text, plain) {
        if (!element) {
            return;
        }

        var source = text === null || text === undefined ? '' : String(text);

        if (RENDER && typeof RENDER.renderInto === 'function') {
            RENDER.renderInto(element, source, { plain: plain || null });
            return;
        }

        // 兜底实现：不解析任何标记，只把换行变成 <br>，不会执行 HTML
        clearNode(element);

        var lines = source.split('\n');

        lines.forEach(function (line, index) {
            if (index > 0) {
                element.appendChild(document.createElement('br'));
            }

            element.appendChild(document.createTextNode(line));
        });
    }

    /**
     * 在一个新建的子容器里渲染富文本并挂到父节点。
     *
     * 注意：renderInto / innerHTML 会**替换**目标元素的全部子节点，
     * 所以绝不能把标题和富文本渲染进同一个元素，必须各用一个容器。
     */
    function appendRich(parent, text, className) {
        var holder = make('div', className || null);

        renderRich(holder, text);
        parent.appendChild(holder);

        return holder;
    }

    // ======================== DOM ========================

    var els = {
        major: document.getElementById('prMajor'),
        kp: document.getElementById('prKp'),
        qtype: document.getElementById('prQtype'),
        difficulty: document.getElementById('prDifficulty'),
        errorType: document.getElementById('prErrorType'),
        mastery: document.getElementById('prMastery'),
        course: document.getElementById('prCourse'),
        source: document.getElementById('prSource'),
        count: document.getElementById('prCount'),
        allowAi: document.getElementById('prAllowAi'),
        verifiedOnly: document.getElementById('prVerifiedOnly'),
        generateBtn: document.getElementById('prGenerateBtn'),
        status: document.getElementById('prStatus'),
        notices: document.getElementById('prNotices'),
        stats: document.getElementById('prStats'),
        statsRefresh: document.getElementById('prStatsRefresh'),
        tasks: document.getElementById('prTasks'),
        tasksRefresh: document.getElementById('prTasksRefresh'),
        history: document.getElementById('prHistory'),
        historyRefresh: document.getElementById('prHistoryRefresh'),
        paperCard: document.getElementById('prPaperCard'),
        paperTitle: document.getElementById('prPaperTitle'),
        paperMeta: document.getElementById('prPaperMeta'),
        paperNotices: document.getElementById('prPaperNotices'),
        questions: document.getElementById('prQuestions'),
        submitBtn: document.getElementById('prSubmitBtn'),
        printBtn: document.getElementById('prPrintBtn'),
        closeBtn: document.getElementById('prCloseBtn'),
        summary: document.getElementById('prSummary'),
        wrongbookActions: document.getElementById('prWrongbookActions'),
        wrongAllBtn: document.getElementById('prWrongAllBtn')
    };

    var state = {
        options: null,
        paper: null,
        review: null,
        submitted: false,
        historyPage: 1,
        historyTotal: 0
    };

    var QTYPE_NAMES = {
        judge: '判断题',
        choice: '选择题',
        fill: '填空题',
        essay: '解答题'
    };

    var UNVERIFIED_AI_TEXT = 'AI 生成，未经校验，答案仅供参考';

    // ======================== 基础工具 ========================

    function clearNode(node) {
        if (!node) {
            return;
        }

        while (node.firstChild) {
            node.removeChild(node.firstChild);
        }
    }

    function make(tag, className, text) {
        var node = document.createElement(tag);

        if (className) {
            node.className = className;
        }

        if (text !== undefined && text !== null) {
            node.textContent = String(text);
        }

        return node;
    }

    function setStatus(message, isError) {
        if (!els.status) {
            return;
        }

        els.status.textContent = message || '';
        els.status.style.color = isError ? '#f64f59' : '#9e62c1';
    }

    function setBusy(button, busy, busyText, idleText) {
        if (!button) {
            return;
        }

        button.disabled = !!busy;
        button.textContent = busy ? busyText : idleText;
    }

    /** 统一请求：返回 {ok, status, data}，网络异常抛出到调用方处理。 */
    function apiFetch(url, options) {
        var init = options || {};

        init.credentials = 'same-origin';

        if (init.body && typeof init.body !== 'string') {
            init.headers = init.headers || {};
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(init.body);
        }

        return fetch(url, init).then(function (response) {
            return response.json().catch(function () {
                return { success: false, message: '服务器返回了无法解析的内容（HTTP ' + response.status + '）' };
            }).then(function (data) {
                return { ok: response.ok && data.success === true, status: response.status, data: data };
            });
        });
    }

    /** 错误状态 + 重试按钮（只显示服务端 message）。 */
    function showError(container, message, onRetry) {
        clearNode(container);

        var box = make('div', 'pr-error');
        box.appendChild(make('span', null, message || '请求失败，请稍后重试'));

        if (typeof onRetry === 'function') {
            var retry = make('button', 'pr-retry-btn', '重试');
            retry.type = 'button';
            retry.addEventListener('click', onRetry);
            box.appendChild(retry);
        }

        container.appendChild(box);
    }

    /** 空状态。 */
    function showEmpty(container, icon, title, desc) {
        clearNode(container);

        var box = make('div', 'pr-empty');
        box.appendChild(make('div', 'pr-empty-icon', icon));
        box.appendChild(make('h4', null, title));

        if (desc) {
            box.appendChild(make('p', null, desc));
        }

        container.appendChild(box);
    }

    /** 提示条（AI 未校验等）。 */
    function showNotices(container, notices) {
        if (!container) {
            return;
        }

        clearNode(container);

        if (!notices || !notices.length) {
            container.hidden = true;
            return;
        }

        var list = make('ul');

        notices.forEach(function (notice) {
            list.appendChild(make('li', null, notice));
        });

        container.appendChild(list);
        container.hidden = false;
    }

    function fillSelect(select, items, valueKey, labelKey, placeholder) {
        if (!select) {
            return;
        }

        var current = select.value;

        clearNode(select);

        if (placeholder) {
            var first = make('option', null, placeholder);
            first.value = '';
            select.appendChild(first);
        }

        (items || []).forEach(function (item) {
            var option = make('option', null, item[labelKey]);
            option.value = item[valueKey];
            select.appendChild(option);
        });

        if (current) {
            select.value = current;
        }
    }

    // ======================== 筛选选项 ========================

    function loadOptions() {
        return apiFetch('/api/practice/options').then(function (result) {
            if (!result.ok) {
                setStatus('筛选项加载失败：' + (result.data.message || '未知错误'), true);
                return;
            }

            state.options = result.data.data;

            // 学科按真实数据量排序，方便直接选到有题目的学科
            var allMajors = (state.options.majors || []).slice().sort(function (a, b) {
                return (b.wrong_count + b.bank_count) - (a.wrong_count + a.bank_count);
            });

            fillSelect(
                els.major,
                allMajors.map(function (item) {
                    return {
                        value: item.name,
                        label: item.name + '（错题 ' + item.wrong_count + ' / 题库 ' + item.bank_count + '）'
                    };
                }),
                'value',
                'label',
                '全部学科'
            );

            fillSelect(
                els.kp,
                (state.options.knowledge_points || []).map(function (item) {
                    return {
                        value: item.name,
                        label: item.name + '（错题 ' + item.wrong_count + ' / 题库 ' + item.bank_count + '）'
                    };
                }),
                'value',
                'label',
                '全部知识点'
            );

            fillSelect(els.qtype, state.options.qtypes, 'value', 'label', '不限题型');
            fillSelect(els.difficulty, state.options.difficulties, 'value', 'label', '不限难度');

            fillSelect(
                els.errorType,
                (state.options.error_types || []).map(function (name) {
                    return { value: name, label: name };
                }),
                'value',
                'label',
                '不限错误类型'
            );

            fillSelect(els.mastery, state.options.mastery_options, 'value', 'label', '不限掌握度');

            fillSelect(
                els.course,
                (state.options.courses || []).map(function (item) {
                    return { value: item.id, label: item.name };
                }),
                'value',
                'label',
                '不限课程'
            );

            if (els.count && state.options.limits) {
                els.count.max = state.options.limits.max_count;
                els.count.value = state.options.limits.default_count;
            }

            if (state.options.ai_available === false && els.allowAi) {
                els.allowAi.checked = false;
                els.allowAi.disabled = true;
                els.allowAi.parentNode.appendChild(
                    make('span', 'pr-hint', '（服务端未配置 AI 密钥，已自动关闭）')
                );
            }
        }).catch(function () {
            setStatus('筛选项加载失败：网络错误，请稍后重试', true);
        });
    }

    // ======================== 组卷 ========================

    function generatePaper() {
        var payload = {
            major: els.major ? els.major.value : '',
            kp: els.kp ? els.kp.value : '',
            qtype: els.qtype ? els.qtype.value : '',
            difficulty: els.difficulty ? els.difficulty.value : '',
            error_type: els.errorType ? els.errorType.value : '',
            mastery: els.mastery ? els.mastery.value : '',
            course_id: els.course ? els.course.value : '',
            source: els.source ? els.source.value : 'auto',
            count: els.count ? els.count.value : 10,
            allow_ai: els.allowAi ? els.allowAi.checked : true,
            verified_only: els.verifiedOnly ? els.verifiedOnly.checked : true
        };

        setBusy(els.generateBtn, true, '正在组卷...', '生成练习卷');
        setStatus('正在按错题与题库组卷，请稍候...', false);
        showNotices(els.notices, []);

        apiFetch('/api/practice/papers', { method: 'POST', body: payload }).then(function (result) {
            setBusy(els.generateBtn, false, '', '生成练习卷');

            if (!result.ok) {
                setStatus('组卷失败：' + (result.data.message || '未知错误'), true);
                return;
            }

            var composition = result.data.composition || {};

            setStatus(
                '已生成 ' + result.data.created_count + ' 道题（错题 ' + (composition.wrong || 0) +
                ' / 题库 ' + (composition.bank || 0) + ' / AI ' + (composition.ai || 0) + '）',
                false
            );

            showNotices(els.notices, result.data.notices);

            renderPaper(result.data.paper, null);
            loadHistory();
        }).catch(function () {
            setBusy(els.generateBtn, false, '', '生成练习卷');
            setStatus('组卷失败：网络错误，请稍后重试', true);
        });
    }

    // ======================== 试卷渲染 ========================

    function sourceBadge(item) {
        if (item.answer_source === 'ai') {
            return { text: UNVERIFIED_AI_TEXT, className: 'pr-badge pr-badge-warn' };
        }

        if (!item.verified) {
            return { text: '题库题目（未校验，仅供参考）', className: 'pr-badge pr-badge-warn' };
        }

        return { text: item.answer_source_name || '', className: 'pr-badge' };
    }

    function buildJudgeInput(item, disabled) {
        var wrap = make('div', 'pr-judge');

        ['对', '错'].forEach(function (label, index) {
            var option = make('label', 'pr-option');
            var radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'q_' + item.id;
            radio.value = label;
            radio.disabled = !!disabled;
            radio.dataset.itemId = String(item.id);

            if (index === 0) {
                radio.id = 'q_' + item.id + '_true';
            }

            option.appendChild(radio);
            option.appendChild(make('span', 'pr-option-text', label));
            wrap.appendChild(option);
        });

        return wrap;
    }

    function buildChoiceInput(item, disabled) {
        var wrap = make('div', 'pr-options');

        (item.options || []).forEach(function (option) {
            var label = make('label', 'pr-option');
            var radio = document.createElement('input');
            radio.type = 'radio';
            radio.name = 'q_' + item.id;
            radio.value = option.label;
            radio.disabled = !!disabled;
            radio.dataset.itemId = String(item.id);

            label.appendChild(radio);
            label.appendChild(make('span', 'pr-option-text', option.label + '. ' + option.text));
            wrap.appendChild(label);
        });

        return wrap;
    }

    function buildTextInput(item, disabled) {
        if (item.qtype === 'essay') {
            var area = document.createElement('textarea');
            area.className = 'pr-essay-input';
            area.placeholder = '请写出你的解答过程';
            area.disabled = !!disabled;
            area.dataset.itemId = String(item.id);
            return area;
        }

        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'pr-fill-input';
        input.placeholder = '请输入答案';
        input.disabled = !!disabled;
        input.dataset.itemId = String(item.id);
        return input;
    }

    function buildAnswerArea(item, reviewItem) {
        var disabled = !!state.submitted;

        if (reviewItem) {
            // 回顾模式：展示作答与判定，不再允许修改
            var box = make('div', 'pr-feedback');

            var userLine = make('div');
            userLine.appendChild(make('span', 'pr-fb-title', '你的作答：'));
            userLine.appendChild(make('span', reviewItem.is_correct === false ? 'pr-fb-user' : null,
                reviewItem.user_answer ? reviewItem.user_answer : '（未作答）'));
            box.appendChild(userLine);

            var verdict = '未自动判分';

            if (reviewItem.is_correct === true) {
                verdict = '判定：正确';
            } else if (reviewItem.is_correct === false) {
                verdict = '判定：错误';
            }

            box.appendChild(make('div', 'pr-fb-title', verdict));

            var refBlock = make('div', 'pr-fb-block');
            refBlock.appendChild(make('div', 'pr-fb-title', '参考答案'));
            appendRich(refBlock, reviewItem.correct_answer || '（本题没有参考答案）');
            box.appendChild(refBlock);

            if (reviewItem.analysis) {
                var analysisBlock = make('div', 'pr-fb-block');
                analysisBlock.appendChild(make('div', 'pr-fb-title', '解析'));
                appendRich(analysisBlock, reviewItem.analysis);
                box.appendChild(analysisBlock);
            }

            if (reviewItem.ai_comment) {
                var aiBlock = make('div', 'pr-ai-comment');
                aiBlock.appendChild(make('div', 'pr-fb-title', 'AI 讲评（非评分依据）'));
                appendRich(aiBlock, reviewItem.ai_comment);
                box.appendChild(aiBlock);
            } else if (reviewItem.qtype === 'essay') {
                var noneBlock = make('div', 'pr-ai-comment');
                noneBlock.appendChild(make('div', 'pr-fb-title', 'AI 讲评'));
                noneBlock.appendChild(make('div', null, '本题没有生成 AI 讲评（AI 调用失败或未作答）。'));
                box.appendChild(noneBlock);
            }

            if (reviewItem.is_correct !== true) {
                var actions = make('div', 'pr-feedback-actions');
                var button = make('button', 'pr-mini-btn', '把这道题加入错题本');
                button.type = 'button';
                button.addEventListener('click', function () {
                    addToWrongbook([reviewItem.id], button);
                });
                actions.appendChild(button);
                box.appendChild(actions);
            }

            return box;
        }

        if (item.qtype === 'judge') {
            return buildJudgeInput(item, disabled);
        }

        if (item.qtype === 'choice' && (item.options || []).length) {
            return buildChoiceInput(item, disabled);
        }

        var wrap = make('div');
        wrap.appendChild(buildTextInput(item, disabled));

        if (item.qtype === 'choice' && !(item.options || []).length) {
            wrap.appendChild(make('div', 'pr-hint', '本题没有选项文本，请直接填写选项字母（如 A）。'));
        }

        return wrap;
    }

    function reviewItemMap(review) {
        var map = {};

        ((review && review.items) || []).forEach(function (item) {
            map[item.id] = item;
        });

        return map;
    }

    function renderPaper(paper, review) {
        if (!paper) {
            els.paperCard.hidden = true;
            return;
        }

        state.paper = paper;
        state.review = review || null;
        state.submitted = !!review;

        els.paperCard.hidden = false;
        els.paperTitle.textContent = paper.title || '练习卷';

        var meta = '共 ' + paper.item_count + ' 题 · 学科：' + (paper.major || '综合') +
            ' · 生成时间：' + (paper.created_at || '-');

        if (review && review.record) {
            meta += ' · 已提交：' + (review.record.submitted_at || '-');
        }

        els.paperMeta.textContent = meta;

        showNotices(els.paperNotices, (review && review.notices) || paper.notices || []);

        var reviewMap = reviewItemMap(review);
        clearNode(els.questions);

        (paper.items || []).forEach(function (item, index) {
            var reviewItem = reviewMap[item.id] || null;
            var card = make('div', 'pr-question');

            if (reviewItem) {
                if (reviewItem.is_correct === true) {
                    card.classList.add('correct');
                } else if (reviewItem.is_correct === false) {
                    card.classList.add('wrong');
                } else {
                    card.classList.add('ungraded');
                }
            }

            var head = make('div', 'pr-q-head');
            head.appendChild(make('span', 'pr-q-no', '第 ' + (index + 1) + ' 题'));

            var typeBadge = make('span', 'pr-badge', item.qtype_name || QTYPE_NAMES[item.qtype] || item.qtype);
            head.appendChild(typeBadge);

            var badge = sourceBadge(item);

            if (badge.text) {
                head.appendChild(make('span', badge.className, badge.text));
            }

            if (item.kp_name) {
                head.appendChild(make('span', 'pr-badge', '知识点：' + item.kp_name));
            }

            if (reviewItem) {
                var verdictText = '未自动判分';

                if (reviewItem.is_correct === true) {
                    verdictText = '正确';
                } else if (reviewItem.is_correct === false) {
                    verdictText = '错误';
                }

                var verdictClass = reviewItem.is_correct === true
                    ? 'pr-badge pr-badge-ok'
                    : (reviewItem.is_correct === false ? 'pr-badge pr-badge-bad' : 'pr-badge pr-badge-warn');

                head.appendChild(make('span', verdictClass, verdictText));
            }

            card.appendChild(head);

            var questionText = make('div', 'pr-q-text');
            appendRich(questionText, item.question || '');
            card.appendChild(questionText);

            card.appendChild(buildAnswerArea(item, reviewItem));
            els.questions.appendChild(card);
        });

        // 提交按钮：未提交时可提交；已提交时隐藏
        els.submitBtn.hidden = state.submitted;
        els.submitBtn.disabled = false;
        els.submitBtn.textContent = '提交并判分';

        els.wrongbookActions.hidden = !state.submitted;

        if (state.submitted && review && review.record) {
            renderSummary(paper, review);
        } else {
            els.summary.hidden = true;
            clearNode(els.summary);
        }

        els.paperCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function renderSummary(paper, review) {
        clearNode(els.summary);

        var record = review.record || {};

        els.summary.appendChild(make('div', 'pr-summary-score', record.score + ' 分'));
        els.summary.appendChild(make('div', 'pr-summary-line',
            '答对 ' + record.correct_count + ' / 可自动判分 ' + record.graded_count +
            ' 题（共 ' + record.total_count + ' 题）· 正确率 ' + record.accuracy + '%'));

        if (record.graded_count === 0) {
            els.summary.appendChild(make('div', 'pr-summary-line',
                '本次没有可自动判分的题目，得分按 0 分记录，请以逐题参考答案与讲评为准。'));
        }

        var points = (review.wrong_points || []).filter(function (row) {
            return row.wrong > 0;
        });

        if (points.length) {
            var text = points.map(function (row) {
                return row.kp_name + '（错 ' + row.wrong + ' / 共 ' + row.total + '）';
            }).join('、');

            els.summary.appendChild(make('div', 'pr-summary-line', '错题知识点分布：' + text));
        } else {
            els.summary.appendChild(make('div', 'pr-summary-line', '本次没有答错的题目。'));
        }

        var ungraded = (review.items || []).filter(function (item) {
            return !item.graded;
        }).length;

        if (ungraded) {
            els.summary.appendChild(make('div', 'pr-summary-line',
                ungraded + ' 道题未自动判分（主观题或参考答案无法比对），不计入得分。'));
        }

        els.summary.hidden = false;
    }

    function collectAnswers() {
        var answers = {};

        (state.paper.items || []).forEach(function (item) {
            answers[item.id] = '';
        });

        Array.prototype.forEach.call(
            els.questions.querySelectorAll('input[type="radio"]:checked'),
            function (radio) {
                answers[radio.dataset.itemId] = radio.value;
            }
        );

        Array.prototype.forEach.call(
            els.questions.querySelectorAll('input.pr-fill-input, textarea.pr-essay-input'),
            function (input) {
                answers[input.dataset.itemId] = input.value;
            }
        );

        return answers;
    }

    // ======================== 提交判分 ========================

    function submitPaper() {
        if (!state.paper) {
            setStatus('还没有练习卷可以提交', true);
            return;
        }

        var answers = collectAnswers();
        var unanswered = Object.keys(answers).filter(function (key) {
            return !String(answers[key] || '').trim();
        });

        if (unanswered.length === Object.keys(answers).length) {
            if (!window.confirm('你还没有作答任何题目，确定要提交吗？（未作答的题目会按错误或未判分处理）')) {
                return;
            }
        } else if (unanswered.length) {
            if (!window.confirm('还有 ' + unanswered.length + ' 道题没有作答，确定提交吗？')) {
                return;
            }
        }

        setBusy(els.submitBtn, true, '正在判分...', '提交并判分');
        setStatus('正在提交并判分，解答题需要 AI 讲评时可能稍慢...', false);

        apiFetch('/api/practice/papers/' + state.paper.id + '/submit', {
            method: 'POST',
            body: { answers: answers }
        }).then(function (result) {
            setBusy(els.submitBtn, false, '', '提交并判分');

            if (!result.ok) {
                setStatus('提交失败：' + (result.data.message || '未知错误'), true);
                els.submitBtn.disabled = false;
                els.submitBtn.textContent = '重新提交';
                return;
            }

            setStatus(result.data.already_submitted
                ? '这份练习卷之前已经提交过，下面显示的是当时的判分结果。'
                : '判分完成。', false);

            renderPaper(result.data.paper, result.data.review);
            loadHistory();
            loadStats();
        }).catch(function () {
            setBusy(els.submitBtn, false, '', '提交并判分');
            setStatus('提交失败：网络错误，请稍后重试', true);
        });
    }

    // ======================== 错题本 ========================

    function addToWrongbook(itemIds, button) {
        if (!state.paper) {
            return Promise.resolve();
        }

        if (button) {
            button.disabled = true;
            button.textContent = '正在加入...';
        }

        return apiFetch('/api/practice/papers/' + state.paper.id + '/wrongbook', {
            method: 'POST',
            body: { item_ids: itemIds || null }
        }).then(function (result) {
            if (button) {
                button.disabled = false;
                button.textContent = '把这道题加入错题本';
            }

            if (!result.ok) {
                setStatus('加入错题本失败：' + (result.data.message || '未知错误'), true);
                return;
            }

            setStatus(result.data.message || '已加入错题本', false);

            if (button) {
                button.textContent = '已加入错题本';
                button.disabled = true;
            }
        }).catch(function () {
            if (button) {
                button.disabled = false;
                button.textContent = '把这道题加入错题本';
            }

            setStatus('加入错题本失败：网络错误，请稍后重试', true);
        });
    }

    function addAllWrong(button) {
        setBusy(button, true, '正在加入...', '把本次错题全部加入错题本');

        addToWrongbook(null, null).then(function () {
            setBusy(button, false, '', '把本次错题全部加入错题本');
        });
    }

    // ======================== 练习历史 ========================

    function loadHistory() {
        return apiFetch('/api/practice/papers?page=' + state.historyPage + '&page_size=10')
            .then(function (result) {
                if (!result.ok) {
                    showError(els.history, result.data.message || '练习历史加载失败', loadHistory);
                    return;
                }

                state.historyTotal = result.data.total || 0;
                renderHistory(result.data.data || [], result.data.total || 0);
            }).catch(function () {
                showError(els.history, '练习历史加载失败：网络错误', loadHistory);
            });
    }

    function renderHistory(items, total) {
        clearNode(els.history);

        if (!items.length) {
            showEmpty(els.history, '📄', '还没有练习记录',
                '在上方选择学科与知识点后点击「生成练习卷」，提交后这里会显示得分与时间。');
            return;
        }

        items.forEach(function (item) {
            var row = make('div', 'pr-row');

            var main = make('div', 'pr-row-main');
            main.appendChild(make('div', 'pr-row-title', item.title || '练习卷'));

            var meta = '共 ' + item.item_count + ' 题 · ' + (item.source_name || '练习卷') +
                ' · 生成于 ' + (item.created_at || '-');

            if (item.submitted) {
                meta += ' · 提交于 ' + (item.submitted_at || '-');
            }

            main.appendChild(make('div', 'pr-row-meta', meta));
            row.appendChild(main);

            var actions = make('div', 'pr-row-actions');

            var score = make('div', item.submitted ? 'pr-score' : 'pr-score pr-score-none',
                item.submitted ? (item.score + ' 分') : '未提交');
            actions.appendChild(score);

            var open = make('button', 'pr-mini-btn pr-mini-primary', item.submitted ? '查看结果' : '继续作答');
            open.type = 'button';
            open.addEventListener('click', function () {
                openPaper(item.id);
            });
            actions.appendChild(open);

            row.appendChild(actions);
            els.history.appendChild(row);
        });

        var pages = Math.max(1, Math.ceil(total / 10));

        if (pages > 1) {
            var pager = make('div', 'pr-row-actions');
            pager.style.justifyContent = 'center';
            pager.style.marginTop = '10px';

            var prev = make('button', 'pr-mini-btn', '上一页');
            prev.type = 'button';
            prev.disabled = state.historyPage <= 1;
            prev.addEventListener('click', function () {
                if (state.historyPage > 1) {
                    state.historyPage -= 1;
                    loadHistory();
                }
            });

            var info = make('span', 'pr-row-meta', '第 ' + state.historyPage + ' / ' + pages + ' 页（共 ' + total + ' 份）');
            info.style.margin = '0 10px';

            var next = make('button', 'pr-mini-btn', '下一页');
            next.type = 'button';
            next.disabled = state.historyPage >= pages;
            next.addEventListener('click', function () {
                if (state.historyPage < pages) {
                    state.historyPage += 1;
                    loadHistory();
                }
            });

            pager.appendChild(prev);
            pager.appendChild(info);
            pager.appendChild(next);
            els.history.appendChild(pager);
        }
    }

    function openPaper(paperId) {
        setStatus('正在打开练习卷...', false);

        apiFetch('/api/practice/papers/' + paperId).then(function (result) {
            if (!result.ok) {
                setStatus('打开失败：' + (result.data.message || '未知错误'), true);
                return;
            }

            setStatus(result.data.submitted
                ? '这是一份已提交的练习卷，下面显示当时的作答与判分结果。'
                : '练习卷已打开，作答完成后点击「提交并判分」。', false);

            renderPaper(result.data.paper, result.data.review);
        }).catch(function () {
            setStatus('打开失败：网络错误，请稍后重试', true);
        });
    }

    // ======================== 统计 ========================

    function loadStats() {
        return apiFetch('/api/practice/stats').then(function (result) {
            if (!result.ok) {
                showError(els.stats, result.data.message || '统计加载失败', loadStats);
                return;
            }

            renderStats(result.data.data || {});
        }).catch(function () {
            showError(els.stats, '统计加载失败：网络错误', loadStats);
        });
    }

    function statBox(value, label) {
        var box = make('div', 'pr-stat-box');
        box.appendChild(make('div', 'pr-stat-value', value));
        box.appendChild(make('div', 'pr-stat-label', label));
        return box;
    }

    function renderStats(data) {
        clearNode(els.stats);

        if (!data.papers) {
            showEmpty(els.stats, '📊', '还没有练习成绩',
                '提交一次练习卷后，这里会显示练习次数、平均分与各知识点的真实正确率。' +
                (data.wrong_question_total ? '（错题本现有 ' + data.wrong_question_total + ' 道题，可先据此组卷。）' : ''));
            return;
        }

        var grid = make('div', 'pr-stat-grid');
        grid.appendChild(statBox(data.papers + ' 次', '完成练习'));
        grid.appendChild(statBox(data.avg_score + ' 分', '平均分'));
        grid.appendChild(statBox(data.best_score + ' 分', '最好成绩'));
        grid.appendChild(statBox(data.accuracy + '%', '自动判分正确率'));
        grid.appendChild(statBox(data.correct_items + ' / ' + data.graded_items, '答对 / 可判分'));
        els.stats.appendChild(grid);

        if ((data.by_knowledge_point || []).length) {
            els.stats.appendChild(make('div', 'pr-sub-title', '知识点正确率（来自真实作答记录）'));

            data.by_knowledge_point.forEach(function (row) {
                var line = make('div', 'pr-kp-row');
                line.appendChild(make('span', 'pr-kp-name', row.kp_name));

                var bar = make('div', 'pr-kp-bar');
                var fill = make('span');
                fill.style.width = Math.max(0, Math.min(100, row.accuracy)) + '%';
                bar.appendChild(fill);
                line.appendChild(bar);

                line.appendChild(make('span', 'pr-kp-value',
                    row.accuracy + '%（' + row.correct + '/' + row.graded + '）'));

                els.stats.appendChild(line);
            });
        }

        if ((data.by_qtype || []).length) {
            els.stats.appendChild(make('div', 'pr-sub-title', '题型正确率'));

            data.by_qtype.forEach(function (row) {
                var line = make('div', 'pr-kp-row');
                line.appendChild(make('span', 'pr-kp-name', row.qtype_name));

                var bar = make('div', 'pr-kp-bar');
                var fill = make('span');
                fill.style.width = Math.max(0, Math.min(100, row.accuracy)) + '%';
                bar.appendChild(fill);
                line.appendChild(bar);

                line.appendChild(make('span', 'pr-kp-value',
                    row.accuracy + '%（' + row.correct + '/' + row.graded + '）'));

                els.stats.appendChild(line);
            });
        }

        if ((data.recent || []).length) {
            els.stats.appendChild(make('div', 'pr-sub-title', '最近练习'));

            data.recent.forEach(function (row) {
                var line = make('div', 'pr-kp-row');
                line.appendChild(make('span', 'pr-kp-name', row.title || '练习卷'));
                line.appendChild(make('span', 'pr-kp-bar'));
                line.appendChild(make('span', 'pr-kp-value',
                    row.score + ' 分 · ' + (row.submitted_at || '')));
                els.stats.appendChild(line);
            });
        }
    }

    // ======================== 教师复习任务 ========================

    function loadTasks() {
        return apiFetch('/api/practice/tasks').then(function (result) {
            if (!result.ok) {
                showError(els.tasks, result.data.message || '复习任务加载失败', loadTasks);
                return;
            }

            renderTasks(result.data.data || []);
        }).catch(function () {
            showError(els.tasks, '复习任务加载失败：网络错误', loadTasks);
        });
    }

    function renderTasks(items) {
        clearNode(els.tasks);

        if (!items.length) {
            showEmpty(els.tasks, '📌', '暂无教师布置的复习任务',
                '老师发布复习任务后会出现在这里，点击即可组卷作答（提交后自动回写完成情况）。');
            return;
        }

        items.forEach(function (task) {
            var row = make('div', 'pr-row');

            var main = make('div', 'pr-row-main');
            main.appendChild(make('div', 'pr-row-title', task.title || '复习任务'));

            var meta = [];

            if (task.course_name) {
                meta.push('课程：' + task.course_name);
            }

            if (task.due_at) {
                meta.push('截止：' + task.due_at);
            }

            if (task.done) {
                meta.push('已完成' + (task.score !== null && task.score !== undefined ? '（' + task.score + ' 分）' : ''));
            } else {
                meta.push('未完成');
            }

            if (task.content) {
                meta.push(task.content);
            }

            main.appendChild(make('div', 'pr-row-meta', meta.join(' · ')));
            row.appendChild(main);

            var actions = make('div', 'pr-row-actions');
            var button = make('button', 'pr-mini-btn pr-mini-primary', task.done ? '查看任务练习' : '开始练习');
            button.type = 'button';
            button.addEventListener('click', function () {
                startTask(task.id, button);
            });
            actions.appendChild(button);

            row.appendChild(actions);
            els.tasks.appendChild(row);
        });
    }

    function startTask(taskId, button) {
        setBusy(button, true, '正在打开...', '开始练习');
        setStatus('正在准备任务练习卷...', false);

        apiFetch('/api/practice/tasks/' + taskId + '/start', { method: 'POST' })
            .then(function (result) {
                setBusy(button, false, '', '开始练习');

                if (!result.ok) {
                    setStatus('打开任务失败：' + (result.data.message || '未知错误'), true);
                    return;
                }

                setStatus(result.data.reused
                    ? '该任务使用老师指定的练习卷。'
                    : '已按任务要求为你生成练习卷。', false);

                showNotices(els.notices, result.data.notices);
                renderPaper(result.data.paper, result.data.review);
                loadTasks();
                loadHistory();
            }).catch(function () {
                setBusy(button, false, '', '开始练习');
                setStatus('打开任务失败：网络错误，请稍后重试', true);
            });
    }

    // ======================== 打印 ========================

    function printPaper() {
        if (!state.paper) {
            setStatus('请先打开或生成一份练习卷，再使用打印。', true);
            return;
        }

        window.print();
    }

    // ======================== 初始化 ========================

    function bindEvents() {
        if (els.generateBtn) {
            els.generateBtn.addEventListener('click', generatePaper);
        }

        if (els.submitBtn) {
            els.submitBtn.addEventListener('click', submitPaper);
        }

        if (els.printBtn) {
            els.printBtn.addEventListener('click', printPaper);
        }

        if (els.closeBtn) {
            els.closeBtn.addEventListener('click', function () {
                els.paperCard.hidden = true;
                state.paper = null;
                state.review = null;
                state.submitted = false;
            });
        }

        if (els.wrongAllBtn) {
            els.wrongAllBtn.addEventListener('click', function () {
                addAllWrong(els.wrongAllBtn);
            });
        }

        if (els.statsRefresh) {
            els.statsRefresh.addEventListener('click', loadStats);
        }

        if (els.tasksRefresh) {
            els.tasksRefresh.addEventListener('click', loadTasks);
        }

        if (els.historyRefresh) {
            els.historyRefresh.addEventListener('click', function () {
                state.historyPage = 1;
                loadHistory();
            });
        }
    }

    function init() {
        bindEvents();

        loadOptions();
        loadStats();
        loadTasks();
        loadHistory();
    }

    init();
})();
