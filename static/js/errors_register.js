/**
 * IntelliLearn 错题本
 *
 * 重要说明（与原实现的区别）：
 *   - 已彻底移除原文件中 50 条写死的"兜底模拟题库数据"（FALLBACK_QUESTIONS）；
 *   - 接口失败时显示真实错误与重试按钮，绝不使用假数据填充页面；
 *   - 学科、错误类型、数量统计全部来自后端真实数据；
 *   - 搜索、筛选、分页均为服务端查询（/api/wrong_questions 支持这些参数）。
 */
(function () {
    'use strict';

    var R = window.ILRender;

    // ======================== 状态 ========================

    var state = {
        page: 1,
        pageSize: 12,
        total: 0,
        filters: {
            keyword: '',
            major: '',
            error_type: '',
            mastery: ''
        },
        items: [],
        currentId: null,
        subjects: [],
        errorTypes: [],
        loading: false
    };

    // ======================== DOM ========================

    var container = document.getElementById('questionsContainer');
    var loadingIndicator = document.getElementById('loadingIndicator');
    var pager = document.getElementById('pager');
    var pageInfo = document.getElementById('pageInfo');
    var questionCount = document.getElementById('questionCount');
    var statsPanel = document.getElementById('statsPanel');

    var keywordInput = document.getElementById('keywordInput');
    var majorSelect = document.getElementById('majorSelect');
    var errorTypeSelect = document.getElementById('errorTypeSelect');
    var masterySelect = document.getElementById('masterySelect');

    var modalOverlay = document.getElementById('modalOverlay');
    var modalTags = document.getElementById('modalTags');
    var modalQuestion = document.getElementById('modalQuestion');
    var modalAnswer = document.getElementById('modalAnswer');
    var modalStudentAnswer = document.getElementById('modalStudentAnswer');
    var studentAnswerSection = document.getElementById('studentAnswerSection');
    var modalErrorAnalysis = document.getElementById('modalErrorAnalysis');
    var errorAnalysisSection = document.getElementById('errorAnalysisSection');

    var editMajor = document.getElementById('editMajor');
    var editErrorType = document.getElementById('editErrorType');
    var editMastery = document.getElementById('editMastery');
    var editKp = document.getElementById('editKp');

    // ======================== 工具 ========================

    function escapeHtml(text) {
        return R ? R.escapeHtml(text) : String(text || '');
    }

    function renderInto(element, text) {
        if (R) {
            R.renderInto(element, text);
            return;
        }

        element.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    }

    function toast(message) {
        var box = document.getElementById('bookToast');

        if (!box) {
            box = document.createElement('div');
            box.id = 'bookToast';
            box.className = 'book-toast';
            document.body.appendChild(box);
        }

        box.textContent = message;
        box.classList.add('show');

        clearTimeout(box._timer);
        box._timer = setTimeout(function () {
            box.classList.remove('show');
        }, 3200);
    }

    function displayMajor(major) {
        return major === 'py' ? 'Python' : major;
    }

    function setLoading(loading) {
        state.loading = loading;
        loadingIndicator.style.display = loading ? 'flex' : 'none';
    }

    /** 统一的 JSON 请求，返回解析后的数据或抛出带后端 message 的错误 */
    function request(url, options) {
        options = options || {};

        return fetch(url, {
            method: options.method || 'GET',
            headers: options.body
                ? { 'Content-Type': 'application/json' }
                : undefined,
            credentials: 'same-origin',
            body: options.body ? JSON.stringify(options.body) : undefined
        }).then(function (response) {
            return response.json()
                .catch(function () {
                    throw new Error('服务器返回了非预期的内容（HTTP ' + response.status + '）');
                })
                .then(function (data) {
                    if (!response.ok || !data.success) {
                        throw new Error(data.message || ('请求失败（HTTP ' + response.status + '）'));
                    }

                    return data;
                });
        });
    }

    // ======================== 初始化筛选项 ========================

    function loadSubjects() {
        return request('/api/subjects')
            .then(function (data) {
                state.subjects = data.majors || [];
                state.errorTypes = data.error_types || [];

                fillSelect(majorSelect, state.subjects, '全部学科', displayMajor);
                fillSelect(editMajor, state.subjects, '请选择学科', displayMajor);
                fillSelect(errorTypeSelect, state.errorTypes, '全部错误类型');
                fillSelect(editErrorType, state.errorTypes, '（不设置错误类型）');
            })
            .catch(function (error) {
                toast('学科列表加载失败：' + error.message);
            });
    }

    function fillSelect(select, values, placeholder, labeler) {
        if (!select) {
            return;
        }

        select.innerHTML = '';

        var first = document.createElement('option');
        first.value = '';
        first.textContent = placeholder;
        select.appendChild(first);

        values.forEach(function (value) {
            var option = document.createElement('option');
            option.value = value;
            option.textContent = labeler ? labeler(value) : value;
            select.appendChild(option);
        });
    }

    // ======================== 统计 ========================

    function loadStats() {
        return request('/api/wrong_questions/stats')
            .then(function (data) {
                renderStats(data.data || {});
            })
            .catch(function () {
                // 统计失败不影响列表展示；留空而不是编造数字
                statsPanel.innerHTML = '';
            });
    }

    function renderStats(stats) {
        statsPanel.innerHTML = '';

        if (!stats.total) {
            return;
        }

        var cards = [
            { label: '错题总数', value: stats.total },
            { label: '已掌握', value: stats.mastered },
            { label: '掌握率', value: (stats.mastery_rate || 0) + '%' }
        ];

        cards.forEach(function (card) {
            var box = document.createElement('div');
            box.className = 'stat-card';

            var value = document.createElement('span');
            value.className = 'stat-value';
            value.textContent = card.value;

            var label = document.createElement('span');
            label.className = 'stat-label';
            label.textContent = card.label;

            box.appendChild(value);
            box.appendChild(label);
            statsPanel.appendChild(box);
        });

        var weak = stats.weak_points || [];

        if (weak.length) {
            var weakBox = document.createElement('div');
            weakBox.className = 'stat-weak';

            var title = document.createElement('span');
            title.className = 'stat-weak-title';
            title.textContent = '薄弱知识点：';
            weakBox.appendChild(title);

            weak.slice(0, 6).forEach(function (point) {
                var tag = document.createElement('span');
                tag.className = 'tag tag-kp';
                tag.textContent = point.kp_name + ' ×' + point.total;
                tag.title = '点击按该知识点筛选';
                tag.style.cursor = 'pointer';
                tag.addEventListener('click', function () {
                    keywordInput.value = point.kp_name;
                    state.filters.keyword = point.kp_name;
                    state.page = 1;
                    loadQuestions();
                });
                weakBox.appendChild(tag);
            });

            statsPanel.appendChild(weakBox);
        }
    }

    // ======================== 列表查询 ========================

    function buildQuery() {
        var params = new URLSearchParams();

        params.set('page', state.page);
        params.set('page_size', state.pageSize);

        Object.keys(state.filters).forEach(function (key) {
            if (state.filters[key]) {
                params.set(key, state.filters[key]);
            }
        });

        return params.toString();
    }

    function loadQuestions() {
        setLoading(true);

        return request('/api/wrong_questions?' + buildQuery())
            .then(function (data) {
                state.items = data.data || [];
                state.total = data.total || 0;

                renderQuestions();
                renderPager();
            })
            .catch(function (error) {
                container.innerHTML = '';

                var notice = document.createElement('div');
                notice.className = 'il-notice il-notice-error';
                notice.textContent = '错题加载失败：' + error.message;

                var retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'il-retry';
                retry.textContent = '重试';
                retry.addEventListener('click', loadQuestions);

                notice.appendChild(retry);
                container.appendChild(notice);

                questionCount.textContent = '';
            })
            .then(function () {
                setLoading(false);
            });
    }

    function renderQuestions() {
        container.innerHTML = '';

        questionCount.textContent = state.total
            ? '共 ' + state.total + ' 道题目'
            : '';

        if (!state.items.length) {
            var empty = document.createElement('div');
            empty.className = 'empty-state';

            var hasFilter = Object.keys(state.filters).some(function (key) {
                return state.filters[key];
            });

            var icon = document.createElement('div');
            icon.className = 'empty-icon';
            icon.textContent = hasFilter ? '🔍' : '📚';

            var line = document.createElement('p');
            line.textContent = hasFilter ? '没有符合条件的错题' : '错题本还是空的';

            var hint = document.createElement('p');
            hint.className = 'empty-hint';
            hint.textContent = hasFilter
                ? '可以调整筛选条件，或清空后重新查询'
                : '在 AI 回答页把题目加入错题本后，会显示在这里';

            empty.appendChild(icon);
            empty.appendChild(line);
            empty.appendChild(hint);
            container.appendChild(empty);
            return;
        }

        state.items.forEach(function (item) {
            container.appendChild(buildCard(item));
        });
    }

    function buildCard(item) {
        var card = document.createElement('div');
        card.className = 'question-card';
        card.dataset.id = item.id;

        var head = document.createElement('div');
        head.className = 'card-head';

        var tags = document.createElement('div');
        tags.className = 'card-tags';

        tags.appendChild(makeTag(displayMajor(item.major) || '未分类', 'card-tag subject'));

        if (item.sub) {
            tags.appendChild(makeTag(item.sub, 'card-tag grade'));
        }

        if (item.error_type) {
            item.error_type.split('、').forEach(function (type) {
                if (type) {
                    tags.appendChild(makeTag(type, 'card-tag error'));
                }
            });
        }

        head.appendChild(tags);

        var mastery = document.createElement('span');
        mastery.className = 'card-mastery mastery-' + (item.mastery || 0);
        mastery.textContent = ['未掌握', '模糊', '已掌握'][item.mastery || 0];
        head.appendChild(mastery);

        card.appendChild(head);

        var question = document.createElement('div');
        question.className = 'card-question';
        question.textContent = item.question || '';
        card.appendChild(question);

        var footer = document.createElement('div');
        footer.className = 'card-footer';

        var viewBtn = document.createElement('button');
        viewBtn.type = 'button';
        viewBtn.className = 'card-btn';
        viewBtn.textContent = '查看解答';
        viewBtn.addEventListener('click', function (event) {
            event.stopPropagation();
            openDetail(item.id);
        });

        var deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'card-btn danger';
        deleteBtn.textContent = '删除';
        deleteBtn.addEventListener('click', function (event) {
            event.stopPropagation();
            removeQuestion(item.id, item.question);
        });

        footer.appendChild(viewBtn);
        footer.appendChild(deleteBtn);

        if (item.created_at) {
            var time = document.createElement('span');
            time.className = 'card-time';
            time.textContent = String(item.created_at).slice(0, 10);
            footer.appendChild(time);
        }

        card.appendChild(footer);

        card.addEventListener('click', function () {
            openDetail(item.id);
        });

        return card;
    }

    function makeTag(text, className) {
        var span = document.createElement('span');
        span.className = className;
        span.textContent = text;
        return span;
    }

    function renderPager() {
        var totalPages = Math.max(1, Math.ceil(state.total / state.pageSize));

        if (state.total <= state.pageSize) {
            pager.style.display = 'none';
            return;
        }

        pager.style.display = 'flex';
        pageInfo.textContent = '第 ' + state.page + ' / ' + totalPages + ' 页';
        document.getElementById('prevPageBtn').disabled = state.page <= 1;
        document.getElementById('nextPageBtn').disabled = state.page >= totalPages;
    }

    // ======================== 详情 / 编辑 / 删除 ========================

    function openDetail(id) {
        state.currentId = id;

        modalOverlay.classList.add('show');
        modalTags.innerHTML = '';
        modalQuestion.textContent = '正在加载…';
        modalAnswer.textContent = '';
        modalStudentAnswer.textContent = '';
        modalErrorAnalysis.textContent = '';
        studentAnswerSection.style.display = 'none';
        errorAnalysisSection.style.display = 'none';

        request('/api/wrong_questions/' + id)
            .then(function (data) {
                fillModal(data.data || {});
            })
            .catch(function (error) {
                modalQuestion.textContent = '加载失败：' + error.message;
            });
    }

    function fillModal(item) {
        modalTags.innerHTML = '';
        modalQuestion.textContent = '';

        if (item.major) {
            modalTags.appendChild(makeTag('学科：' + displayMajor(item.major), 'tag tag-major'));
        }

        if (item.sub) {
            modalTags.appendChild(makeTag('章节：' + item.sub, 'tag tag-sub'));
        }

        (item.kp_list || []).forEach(function (kp) {
            modalTags.appendChild(makeTag('知识点：' + kp, 'tag tag-kp'));
        });

        if (item.error_type) {
            item.error_type.split('、').forEach(function (type) {
                if (type) {
                    modalTags.appendChild(makeTag('错误类型：' + type, 'tag tag-error'));
                }
            });
        }

        modalTags.appendChild(makeTag(
            '来源：' + (item.source === 'teacher' ? '教师' : 'AI 分析'),
            'tag tag-muted'
        ));

        if (item.created_at) {
            modalTags.appendChild(makeTag(
                '加入时间：' + String(item.created_at).slice(0, 19),
                'tag tag-muted'
            ));
        }

        modalQuestion.textContent = item.question || '（题目内容为空）';

        if (item.image_url) {
            var img = document.createElement('img');
            img.src = item.image_url;
            img.className = 'modal-image';
            img.alt = '题目图片';
            img.loading = 'lazy';
            modalQuestion.appendChild(img);
        }

        if (item.user_answer) {
            studentAnswerSection.style.display = 'block';
            modalStudentAnswer.textContent = item.user_answer;
        }

        renderInto(
            modalAnswer,
            item.answer || item.standard_answer || '这道题还没有保存解答。'
        );

        if (item.analysis) {
            errorAnalysisSection.style.display = 'block';
            renderInto(modalErrorAnalysis, item.analysis);
        }

        // 编辑区回填
        editMajor.value = item.major || '';
        editErrorType.value = (item.error_type || '').split('、')[0] || '';
        editMastery.value = String(item.mastery || 0);
        editKp.value = (item.kp_list || []).join('、');
    }

    function closeModal() {
        modalOverlay.classList.remove('show');
        state.currentId = null;
    }

    function saveEdit() {
        if (!state.currentId) {
            return;
        }

        var saveBtn = document.getElementById('saveEditBtn');
        saveBtn.disabled = true;

        request('/api/wrong_questions/' + state.currentId, {
            method: 'PATCH',
            body: {
                major: editMajor.value,
                error_type: editErrorType.value,
                mastery: Number(editMastery.value),
                knowledge_points: editKp.value
            }
        })
            .then(function (data) {
                toast(data.message || '已更新');
                closeModal();
                loadStats();
                loadQuestions();
            })
            .catch(function (error) {
                toast('保存失败：' + error.message);
            })
            .then(function () {
                saveBtn.disabled = false;
            });
    }

    function markReviewed() {
        if (!state.currentId) {
            return;
        }

        request('/api/wrong_questions/' + state.currentId + '/review', {
            method: 'POST',
            body: { mastery: Number(editMastery.value) }
        })
            .then(function (data) {
                toast(data.message || '已记录复习');
                loadStats();
                loadQuestions();
            })
            .catch(function (error) {
                toast('记录失败：' + error.message);
            });
    }

    function removeQuestion(id, question) {
        var preview = (question || '').slice(0, 30);
        var suffix = question && question.length > 30 ? '…' : '';

        var confirmed = window.confirm(
            '确定要删除这道错题吗？\n「' + preview + suffix + '」\n删除后不可恢复。'
        );

        if (!confirmed) {
            return;
        }

        request('/api/wrong_questions/' + id, { method: 'DELETE' })
            .then(function (data) {
                toast(data.message || '已删除');

                if (state.currentId === id) {
                    closeModal();
                }

                if (state.items.length === 1 && state.page > 1) {
                    state.page -= 1;
                }

                loadStats();
                loadQuestions();
            })
            .catch(function (error) {
                toast('删除失败：' + error.message);
            });
    }

    // ======================== 事件绑定 ========================

    function readFilters() {
        state.filters.keyword = keywordInput.value.trim();
        state.filters.major = majorSelect.value;
        state.filters.error_type = errorTypeSelect.value;
        state.filters.mastery = masterySelect.value;
    }

    function bind() {
        document.getElementById('searchBtn').addEventListener('click', function () {
            readFilters();
            state.page = 1;
            loadQuestions();
        });

        document.getElementById('resetBtn').addEventListener('click', function () {
            keywordInput.value = '';
            majorSelect.value = '';
            errorTypeSelect.value = '';
            masterySelect.value = '';
            readFilters();
            state.page = 1;
            loadQuestions();
        });

        keywordInput.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                document.getElementById('searchBtn').click();
            }
        });

        document.getElementById('prevPageBtn').addEventListener('click', function () {
            if (state.page > 1) {
                state.page -= 1;
                loadQuestions();
            }
        });

        document.getElementById('nextPageBtn').addEventListener('click', function () {
            state.page += 1;
            loadQuestions();
        });

        document.getElementById('modalClose').addEventListener('click', closeModal);

        modalOverlay.addEventListener('click', function (event) {
            if (event.target === modalOverlay) {
                closeModal();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && modalOverlay.classList.contains('show')) {
                closeModal();
            }
        });

        document.getElementById('saveEditBtn').addEventListener('click', saveEdit);
        document.getElementById('reviewBtn').addEventListener('click', markReviewed);

        document.getElementById('deleteBtn').addEventListener('click', function () {
            if (state.currentId) {
                removeQuestion(state.currentId, modalQuestion.textContent);
            }
        });
    }

    function init() {
        bind();

        // 先加载筛选项与统计，再加载列表；任一失败都不影响其它部分
        Promise.all([loadSubjects(), loadStats()]).then(function () {
            loadQuestions();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
