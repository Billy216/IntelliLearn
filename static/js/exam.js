(function() {
    'use strict';

    // ===== DOM =====
    const subjectSelect = document.getElementById('examSubject');
    const generateBtn = document.getElementById('generateExamBtn');
    const statusEl = document.getElementById('examStatus');
    const examBody = document.getElementById('examBody');
    const examPaperTitle = document.getElementById('examPaperTitle');
    const judgeList = document.getElementById('judgeList');
    const choiceList = document.getElementById('choiceList');
    const fillList = document.getElementById('fillList');
    const essayList = document.getElementById('essayList');
    const resetBtn = document.getElementById('resetExamBtn');
    const examHistory = document.getElementById('examHistory');
    const examHistoryList = document.getElementById('examHistoryList');

    let currentExam = null;
    let currentMajor = '';
    let currentPaperId = null;

    // ===== 上标转换 =====
    const SUPERSCRIPT_MAP = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵',
        '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ', 'f': 'ᶠ', 'g': 'ᵍ',
        'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ', 'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ',
        'o': 'ᵒ', 'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ', 'v': 'ᵛ',
        'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾'
    };

    function toSuperscript(text) {
        return String(text).split('').map(ch => SUPERSCRIPT_MAP[ch] || ch).join('');
    }

    function convertPowerNotation(text) {
        return String(text).replace(/\^(\{[^}]*\}|\([^)]*\)|[A-Za-z]+|\d+|.)/g, function(match, inner) {
            if ((inner.startsWith('{') && inner.endsWith('}')) || (inner.startsWith('(') && inner.endsWith(')'))) {
                inner = inner.slice(1, -1);
            }
            return toSuperscript(inner);
        });
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function renderText(text) {
        let html = escapeHtml(text);
        html = convertPowerNotation(html);
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\n/g, '<br>');
        return html;
    }

    function displayMajorName(major) {
        return major === 'py' ? 'Python' : major;
    }

    function setStatus(msg, isError) {
        statusEl.textContent = msg || '';
        statusEl.style.color = isError ? '#f64f59' : '#9e62c1';
    }

    // ===== 生成试卷 =====
    generateBtn.addEventListener('click', function() {
        const major = subjectSelect.value;
        generateBtn.disabled = true;
        generateBtn.textContent = '正在出题...';
        setStatus('AI 正在根据你的错题出题，请稍候（可能需要几十秒）...');

        fetch('/api/exam/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ major: major })
        })
        .then(res => res.json())
        .then(data => {
            generateBtn.disabled = false;
            generateBtn.textContent = '🎲 生成试卷';
            if (data.success) {
                currentExam = data.exam;
                currentMajor = data.major;
                currentPaperId = data.paper_id || null;
                renderExam();
                setStatus('');
                loadHistory();
            } else {
                examBody.style.display = 'none';
                setStatus('⚠️ ' + (data.message || '出题失败'), true);
            }
        })
        .catch(() => {
            generateBtn.disabled = false;
            generateBtn.textContent = '🎲 生成试卷';
            setStatus('⚠️ 网络错误，请稍后重试', true);
        });
    });

    // ===== 历史试卷 =====
    function loadHistory() {
        fetch('/api/exam/papers', {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(res => res.json())
        .then(data => {
            if (data.success && data.data && data.data.length > 0) {
                renderHistory(data.data);
            } else {
                examHistory.style.display = 'none';
            }
        })
        .catch(() => {
            examHistory.style.display = 'none';
        });
    }

    function renderHistory(papers) {
        examHistory.style.display = 'block';
        examHistoryList.innerHTML = '';
        papers.forEach(p => {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'exam-history-chip' + (currentPaperId === p.id ? ' active' : '');
            const time = (p.created_at || '').replace('T', ' ').slice(0, 16);
            chip.innerHTML = '<span class="chip-major">' + escapeHtml(displayMajorName(p.major)) + '</span>' +
                '<span class="chip-time">' + escapeHtml(time) + '</span>';
            chip.addEventListener('click', function() {
                openPaper(p.id, chip);
            });
            examHistoryList.appendChild(chip);
        });
    }

    function openPaper(paperId, chipEl) {
        setStatus('正在加载历史试卷...');
        fetch('/api/exam/papers/' + paperId, {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                currentExam = data.exam;
                currentMajor = data.major;
                currentPaperId = paperId;
                renderExam();
                setStatus('');
                document.querySelectorAll('.exam-history-chip').forEach(c => {
                    c.classList.toggle('active', c === chipEl);
                });
                examBody.scrollIntoView({ behavior: 'smooth', block: 'start' });
            } else {
                setStatus('⚠️ ' + (data.message || '加载失败'), true);
            }
        })
        .catch(() => setStatus('⚠️ 网络错误，请稍后重试', true));
    }

    // ===== 渲染试卷 =====
    function renderExam() {
        examBody.style.display = 'block';
        examPaperTitle.textContent = displayMajorName(currentMajor) + ' 小测';
        renderJudge();
        renderChoice();
        renderFill();
        renderEssay();
    }

    function makeCard(type, index, titleHtml, bodyHtml) {
        const card = document.createElement('div');
        card.className = 'exam-question';
        card.dataset.type = type;
        card.dataset.index = index;
        card.innerHTML = '<div class="exam-q-title">' + (index + 1) + '. ' + titleHtml + '</div>' + bodyHtml;
        return card;
    }

    function renderJudge() {
        judgeList.innerHTML = '';
        (currentExam.judge || []).forEach((item, i) => {
            const body = '<div class="exam-options">' +
                '<label class="exam-option"><input type="radio" name="judge_' + i + '" value="对"> 对</label>' +
                '<label class="exam-option"><input type="radio" name="judge_' + i + '" value="错"> 错</label>' +
                '</div>';
            const card = makeCard('judge', i, renderText(item.question), body);
            card.querySelectorAll('input').forEach(input => {
                input.addEventListener('change', function() {
                    gradeQuestion(card, item);
                });
            });
            judgeList.appendChild(card);
        });
    }

    function renderChoice() {
        choiceList.innerHTML = '';
        (currentExam.choice || []).forEach((item, i) => {
            const letters = ['A', 'B', 'C', 'D'];
            let body = '<div class="exam-options">';
            (item.options || []).forEach((opt, j) => {
                const letter = letters[j] || ('选项' + (j + 1));
                body += '<label class="exam-option"><input type="radio" name="choice_' + i + '" value="' + letter + '"> ' +
                    letter + '. ' + renderText(opt) + '</label>';
            });
            body += '</div>';
            const card = makeCard('choice', i, renderText(item.question), body);
            card.querySelectorAll('input').forEach(input => {
                input.addEventListener('change', function() {
                    gradeQuestion(card, item);
                });
            });
            choiceList.appendChild(card);
        });
    }

    function renderFill() {
        fillList.innerHTML = '';
        (currentExam.fill || []).forEach((item, i) => {
            const body = '<input type="text" class="exam-fill-input" placeholder="填写后回车或点击别处即可判断对错...">';
            const card = makeCard('fill', i, renderText(item.question), body);
            const input = card.querySelector('.exam-fill-input');
            input.addEventListener('change', function() {
                gradeQuestion(card, item);
            });
            input.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    input.blur();
                }
            });
            fillList.appendChild(card);
        });
    }

    function renderEssay() {
        essayList.innerHTML = '';
        (currentExam.essay || []).forEach((item, i) => {
            const body = '<div class="exam-essay-actions">' +
                '<button type="button" class="exam-essay-btn">✅ 我已完成</button></div>' +
                '<div class="exam-process" style="display:none;"></div>';
            const card = makeCard('essay', i, renderText(item.question), body);
            card.querySelector('.exam-essay-btn').addEventListener('click', function() {
                generateEssayProcess(card, item);
            });
            essayList.appendChild(card);
        });
    }

    // ===== 判断对错 =====
    function normalizeJudge(ans) {
        const a = String(ans || '').trim();
        if (/^错|错误|×/.test(a)) return '错';
        if (/^对|正确|√|✓/.test(a)) return '对';
        return a;
    }

    function normalizeChoice(ans) {
        return String(ans || '').trim().toUpperCase().charAt(0) || '';
    }

    function normalizeFill(ans) {
        return String(ans || '').trim().replace(/\s+/g, '');
    }

    function fillAcceptable(userAns, answer) {
        const u = normalizeFill(userAns);
        if (!u) return false;
        const parts = String(answer || '').split(/[或/；;]/);
        return parts.some(p => normalizeFill(p) === u);
    }

    function gradeQuestion(card, item) {
        const type = card.dataset.type;
        let isRight = false;
        let msg = '';
        if (type === 'judge') {
            const selected = card.querySelector('input:checked');
            const userAns = selected ? selected.value : '';
            if (!userAns) return;
            const rightAns = normalizeJudge(item.answer);
            isRight = userAns === rightAns;
            if (!isRight) msg = rightAns;
        } else if (type === 'choice') {
            const selected = card.querySelector('input:checked');
            const userAns = selected ? selected.value : '';
            if (!userAns) return;
            const rightAns = normalizeChoice(item.answer);
            isRight = userAns === rightAns;
            if (!isRight) {
                const letters = ['A', 'B', 'C', 'D'];
                const optIdx = letters.indexOf(rightAns);
                msg = rightAns + (optIdx >= 0 && item.options && item.options[optIdx] ? '. ' + item.options[optIdx] : '');
            }
        } else if (type === 'fill') {
            const input = card.querySelector('.exam-fill-input');
            const userAns = input ? input.value : '';
            if (!normalizeFill(userAns)) return;
            isRight = fillAcceptable(userAns, item.answer);
            if (!isRight) msg = item.answer || '';
        }
        showFeedback(card, isRight, msg, item.analysis || '');
    }

    // 答对：只显示“正确”，解析需用户主动点击查看；答错：立即显示过程
    function showFeedback(card, isRight, msg, analysis) {
        const old = card.querySelector('.exam-feedback');
        if (old) old.remove();
        const fb = document.createElement('div');
        fb.className = 'exam-feedback ' + (isRight ? 'correct' : 'wrong');
        if (isRight) {
            fb.innerHTML = '✅ 回答正确 <a href="javascript:void(0)" class="show-analysis">查看解析</a>';
            const link = fb.querySelector('.show-analysis');
            link.addEventListener('click', function() {
                const box = fb.querySelector('.analysis');
                if (box) {
                    box.style.display = box.style.display === 'none' ? 'block' : 'none';
                } else if (analysis) {
                    fb.innerHTML += '<div class="analysis"><div class="analysis-title">📖 解题过程</div>' +
                        renderText(analysis) + '</div>';
                }
            });
        } else {
            fb.innerHTML = '❌ 回答错误' + (msg ? '，正确答案：<strong>' + escapeHtml(msg) + '</strong>' : '');
            if (analysis) {
                fb.innerHTML += '<div class="analysis"><div class="analysis-title">📖 解题过程</div>' +
                    renderText(analysis) + '</div>';
            }
        }
        card.appendChild(fb);
        card.classList.toggle('correct', isRight);
        card.classList.toggle('wrong', !isRight);
    }

    // ===== 大题：我已完成（不做对错判断，直接出过程） =====
    function generateEssayProcess(card, item) {
        const btn = card.querySelector('.exam-essay-btn');
        const processDiv = card.querySelector('.exam-process');
        btn.disabled = true;
        btn.textContent = '正在生成解题过程...';
        processDiv.style.display = 'block';
        processDiv.innerHTML = '<h4>⏳ 请稍候...</h4>';

        fetch('/api/exam/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ question: item.question, user_answer: '' })
        })
        .then(res => res.json())
        .then(data => {
            btn.disabled = false;
            btn.textContent = '✅ 我已完成';
            if (data.success) {
                processDiv.innerHTML = '<h4>📖 参考答案与解题过程</h4>' + renderText(data.process);
                processDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            } else {
                processDiv.innerHTML = '<h4>⚠️</h4>' + renderText(data.message || '生成失败，请重试');
            }
        })
        .catch(() => {
            btn.disabled = false;
            btn.textContent = '✅ 我已完成';
            processDiv.innerHTML = '<h4>⚠️</h4>网络错误，请稍后重试';
        });
    }

    // ===== 重新作答 =====
    resetBtn.addEventListener('click', function() {
        if (!currentExam) return;
        renderExam();
        setStatus('已清空答案，可以重新作答');
    });

    // ===== 初始化：加载历史试卷 =====
    loadHistory();
})();
