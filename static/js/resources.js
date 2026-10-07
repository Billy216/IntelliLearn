/* ============================================================
   resources.js —— 本校知识库与学习资源（模块五）
   全部数据来自 /api/resources* 与 /api/courses 等真实接口。
   演示数据（is_demo=1）在界面上必须显著标注「非真实校方资源」。
   ============================================================ */
(function () {
    'use strict';

    var ROLE = document.body.getAttribute('data-role') || 'student';
    var CAN_MANAGE = ROLE === 'teacher' || ROLE === 'admin';
    var IS_ADMIN = ROLE === 'admin';

    var state = {
        courses: [],
        chapters: [],
        majors: [],
        types: [],
        page: 1,
        pageSize: 12,
        total: 0
    };

    /* ---------- 基础工具（与 teacher.js 保持一致） ---------- */

    /* TODO: window.ILRender 由 static/js/render.js 提供；
       未加载时退化为本地转义，确保不会把未转义文本写入 innerHTML。 */
    function esc(text) {
        if (window.ILRender && typeof window.ILRender.escapeHtml === 'function') {
            return window.ILRender.escapeHtml(text);
        }

        return String(text === null || text === undefined ? '' : text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function markup(text) {
        if (text === null || text === undefined || text === '') {
            return '';
        }

        if (window.ILRender && typeof window.ILRender.render === 'function') {
            try {
                return window.ILRender.render(String(text));
            } catch (error) {
                return esc(text).replace(/\n/g, '<br>');
            }
        }

        return esc(text).replace(/\n/g, '<br>');
    }

    function $(id) {
        return document.getElementById(id);
    }

    function api(path, options) {
        options = options || {};

        var init = {
            method: options.method || 'GET',
            credentials: 'same-origin',
            headers: { 'Accept': 'application/json' }
        };

        if (options.body !== undefined) {
            init.headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(options.body);
        }

        return fetch(path, init).then(function (response) {
            return response.json().catch(function () {
                return null;
            }).then(function (data) {
                if (!response.ok || !data || data.success === false) {
                    return {
                        error: (data && data.message)
                            || ('请求失败（HTTP ' + response.status + '）'),
                        status: response.status,
                        code: data && data.code
                    };
                }

                return data;
            });
        }).catch(function (error) {
            return {
                error: '网络请求失败：' + (error && error.message
                    ? error.message : '无法连接服务器')
            };
        });
    }

    function setStatus(id, text, kind, retry) {
        var node = $(id);

        if (!node) {
            return;
        }

        node.className = 'status-line' + (kind ? ' ' + kind : '');
        node.innerHTML = '';

        if (!text) {
            return;
        }

        var span = document.createElement('span');
        span.innerHTML = esc(text);
        node.appendChild(span);

        if (retry) {
            var button = document.createElement('button');
            button.className = 'btn-link';
            button.type = 'button';
            button.textContent = '重试';
            button.addEventListener('click', retry);
            node.appendChild(button);
        }
    }

    function emptyState(text) {
        return '<div class="empty-state">' + esc(text) + '</div>';
    }

    /* ---------- 标签页 ---------- */

    function initTabs() {
        var buttons = document.querySelectorAll('#mainTabs .tab-btn');

        Array.prototype.forEach.call(buttons, function (button) {
            button.addEventListener('click', function () {
                Array.prototype.forEach.call(buttons, function (other) {
                    other.classList.remove('active');
                });

                button.classList.add('active');

                var target = button.getAttribute('data-tab');

                Array.prototype.forEach.call(
                    document.querySelectorAll('.tab-panel'),
                    function (panel) {
                        panel.classList.remove('active');
                    }
                );

                var panel = $('panel-' + target);

                if (panel) {
                    panel.classList.add('active');
                }

                if (target === 'recommend') {
                    loadRecommend();
                } else if (target === 'courses') {
                    loadCourseTree();
                } else if (target === 'classmatch') {
                    loadClassMatchOptions();
                }
            });
        });
    }

    /* ---------- 筛选项 ---------- */

    function loadFilters() {
        return Promise.all([
            api('/api/resources/filters'),
            api('/api/chapters')
        ]).then(function (results) {
            var filterResult = results[0];
            var chapterResult = results[1];

            if (filterResult.error) {
                setStatus('searchStatus', filterResult.error, 'error', loadFilters);
                return;
            }

            state.courses = filterResult.courses || [];
            state.majors = filterResult.majors || [];
            state.types = filterResult.rtypes || [];
            state.chapters = (chapterResult && chapterResult.data) || [];

            fillSelect($('fCourse'), '全部课程', state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            fillSelect($('fType'), '全部类型', state.types.map(function (item) {
                return { value: item.value, label: item.label };
            }));

            fillSelect($('fMajor'), '全部学科', state.majors.map(function (item) {
                return { value: item.major, label: item.major + '（' + item.total + '）' };
            }));

            fillChapterSelect($('fChapter'), '全部章节', null);

            fillSelect($('rType'), null, state.types.map(function (item) {
                return { value: item.value, label: item.label };
            }));

            fillSelect($('rCourse'), '不指定', state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            fillSelect($('chapCourse'), '请选择课程', state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            fillSelect($('kpCourse'), '不指定', state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            loadResources();
        });
    }

    function fillSelect(select, placeholder, items) {
        if (!select) {
            return;
        }

        select.innerHTML = '';

        if (placeholder !== null && placeholder !== undefined) {
            var option = document.createElement('option');
            option.value = '';
            option.textContent = placeholder;
            select.appendChild(option);
        }

        (items || []).forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = String(item.value);
            opt.textContent = item.label;
            select.appendChild(opt);
        });
    }

    function fillChapterSelect(select, placeholder, courseId) {
        if (!select) {
            return;
        }

        var items = state.chapters.filter(function (item) {
            return !courseId || String(item.course_id) === String(courseId);
        });

        fillSelect(select, placeholder, items.map(function (item) {
            return { value: item.id, label: item.course_name + ' / ' + item.name };
        }));
    }

    /* ---------- 资源卡片 ---------- */

    function resourceCard(item, options) {
        options = options || {};

        var html = ['<div class="resource-card">'];

        html.push('<h4>' + esc(item.title) + '</h4>');

        html.push('<div class="resource-meta">');
        html.push('<span class="badge">'
            + esc(item.rtype_label || item.rtype || '其他') + '</span>');

        if (item.course_name) {
            html.push('<span class="badge">' + esc(item.course_name) + '</span>');
        }

        if (item.chapter_name) {
            html.push('<span class="badge">' + esc(item.chapter_name) + '</span>');
        }

        if (item.major) {
            html.push('<span class="badge">' + esc(item.major) + '</span>');
        }

        if (item.kp_name) {
            html.push('<span class="badge">' + esc(item.kp_name) + '</span>');
        }

        if (item.download_count !== undefined) {
            html.push('<span>下载 ' + esc(String(item.download_count)) + ' 次</span>');
        }

        html.push('</div>');

        if (item.is_demo) {
            html.push('<div class="badge demo">演示数据（非真实校方资源）</div>');
        }

        if (options.matchedPoints && options.matchedPoints.length) {
            html.push('<div class="resource-meta"><span>命中你的薄弱点：'
                + esc(options.matchedPoints.join('、')) + '</span></div>');
        }

        if (item.description) {
            html.push('<div class="resource-desc">' + markup(item.description)
                + '</div>');
        }

        html.push('<div class="resource-meta">');
        html.push('<span>上传者：'
            + esc(item.uploader_name || item.uploader_no || '—') + '</span>');
        html.push('<span>· ' + esc(item.created_at || '') + '</span>');
        html.push('</div>');

        html.push('<div class="resource-actions">');

        if (item.external_url) {
            html.push('<a class="btn-secondary" href="' + esc(item.external_url)
                + '" target="_blank" rel="noopener">打开外链</a>');
        }

        if (item.file_path) {
            html.push('<button class="btn-secondary" data-download="' + item.id
                + '">获取文件</button>');
        }

        if (!item.external_url && !item.file_path) {
            html.push('<span class="hint">该资源没有可访问的文件或链接</span>');
        }

        html.push('</div>');
        html.push('</div>');

        return html.join('');
    }

    function bindDownloadButtons(container) {
        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-download]'),
            function (button) {
                button.addEventListener('click', function () {
                    var id = button.getAttribute('data-download');

                    button.disabled = true;

                    api('/api/resources/' + id + '/download', { method: 'POST' })
                        .then(function (result) {
                            button.disabled = false;

                            if (result.error) {
                                window.alert('获取失败：' + result.error);
                                return;
                            }

                            var info = result.data;

                            if (info.external_url) {
                                window.open(info.external_url, '_blank', 'noopener');
                            } else {
                                window.open(info.file_path, '_blank', 'noopener');
                            }
                        });
                });
            }
        );
    }

    /* ---------- 检索 ---------- */

    function loadResources() {
        var params = [];

        function add(key, value) {
            if (value !== null && value !== undefined && value !== '') {
                params.push(key + '=' + encodeURIComponent(value));
            }
        }

        add('keyword', $('fKeyword') ? $('fKeyword').value.trim() : '');
        add('course_id', $('fCourse') ? $('fCourse').value : '');
        add('chapter_id', $('fChapter') ? $('fChapter').value : '');
        add('rtype', $('fType') ? $('fType').value : '');
        add('major', $('fMajor') ? $('fMajor').value : '');
        add('kp_name', $('fKp') ? $('fKp').value.trim() : '');
        add('is_demo', $('fDemo') ? $('fDemo').value : '');
        add('page', state.page);
        add('page_size', state.pageSize);

        setStatus('searchStatus', '正在检索…');

        api('/api/resources?' + params.join('&')).then(function (result) {
            if (result.error) {
                setStatus('searchStatus', result.error, 'error', loadResources);
                return;
            }

            state.total = result.total;

            if (!result.data.length) {
                setStatus('searchStatus',
                    '没有符合条件的资源（共 ' + result.total + ' 条记录）。');
                $('searchResult').innerHTML = emptyState(
                    '当前筛选条件下没有找到资源。'
                    + '本校知识库里的资源需要管理员或教师先录入，'
                    + '系统不会自动生成任何课件或试卷。'
                );
                $('searchPager').innerHTML = '';
                return;
            }

            var demoCount = result.demo_count || 0;

            setStatus('searchStatus',
                '共 ' + result.total + ' 条，当前第 ' + result.page + ' 页；'
                + (demoCount
                    ? '本页含 ' + demoCount + ' 条演示数据（非真实校方资源）'
                    : '本页全部为真实录入资源'));

            $('searchResult').innerHTML = result.data.map(function (item) {
                return resourceCard(item);
            }).join('');

            bindDownloadButtons($('searchResult'));
            renderPager(result.total, result.page, result.page_size);
        });
    }

    function renderPager(total, page, pageSize) {
        var pages = Math.max(1, Math.ceil(total / pageSize));

        var html = ['<button class="btn-secondary" id="prevPage"'
            + (page <= 1 ? ' disabled' : '') + '>上一页</button>',
        '<span>第 ' + page + ' / ' + pages + ' 页</span>',
        '<button class="btn-secondary" id="nextPage"'
            + (page >= pages ? ' disabled' : '') + '>下一页</button>'];

        $('searchPager').innerHTML = html.join('');

        var prev = $('prevPage');
        var next = $('nextPage');

        if (prev) {
            prev.addEventListener('click', function () {
                state.page = Math.max(1, state.page - 1);
                loadResources();
            });
        }

        if (next) {
            next.addEventListener('click', function () {
                state.page = state.page + 1;
                loadResources();
            });
        }
    }

    /* ---------- 根据我的易错点检索 ---------- */

    function loadRecommend() {
        setStatus('recommendStatus', '正在根据你的错题记录计算推荐…');

        api('/api/resources/recommend?limit=20').then(function (result) {
            if (result.error) {
                setStatus('recommendStatus', result.error, 'error', loadRecommend);
                return;
            }

            var weak = result.weak_points || [];

            if (!weak.length) {
                $('weakPointBox').innerHTML = '';
                setStatus('recommendStatus', '');
                $('recommendResult').innerHTML = emptyState(
                    '你的错题本里还没有知识点标注，因此无法计算易错点推荐。'
                    + '先在 AI 回答或错题集里记录错题后，这里才会出现推荐结果。'
                );
                return;
            }

            $('weakPointBox').innerHTML = '<div class="weak-point-list">'
                + weak.map(function (item) {
                    return '<span class="weak-point">' + esc(item.kp_name)
                        + ' × ' + esc(String(item.total)) + '</span>';
                }).join('')
                + '</div>';

            if (!result.data.length) {
                setStatus('recommendStatus',
                    '已识别 ' + weak.length + ' 个薄弱知识点，但知识库里还没有匹配的资源。'
                    + '请让教师在「资源管理」中补充对应资料。');
                $('recommendResult').innerHTML = emptyState(
                    '没有匹配到资源：本系统不会为了填充页面而生成虚假课件。'
                );
                return;
            }

            setStatus('recommendStatus',
                '已按你的薄弱知识点匹配到 ' + result.total + ' 条资源'
                + '（依据：' + weak.map(function (item) {
                    return item.kp_name;
                }).join('、') + '）');

            $('recommendResult').innerHTML = result.data.map(function (item) {
                return resourceCard(item, { matchedPoints: item.matched_points });
            }).join('');

            bindDownloadButtons($('recommendResult'));
        });
    }

    /* ---------- 课程 / 章节 / 知识点 ---------- */

    function loadCourseTree() {
        setStatus('coursesStatus', '正在读取课程结构…');

        Promise.all([
            api('/api/courses'),
            api('/api/chapters'),
            api('/api/knowledge-points')
        ]).then(function (results) {
            var coursesResult = results[0];

            if (coursesResult.error) {
                setStatus('coursesStatus', coursesResult.error, 'error',
                    loadCourseTree);
                return;
            }

            var courses = coursesResult.data || [];
            var chapters = (results[1] && results[1].data) || [];
            var points = (results[2] && results[2].data) || [];

            if (!courses.length) {
                setStatus('coursesStatus', '');
                $('coursesBody').innerHTML = emptyState(
                    '本校知识库还没有任何课程记录。'
                    + (IS_ADMIN ? '可以在下方创建第一门课程。' : '请联系管理员录入课程。')
                );
                return;
            }

            setStatus('coursesStatus', '共 ' + courses.length + ' 门课程');

            $('coursesBody').innerHTML = courses.map(function (course) {
                var courseChapters = chapters.filter(function (item) {
                    return item.course_id === course.id;
                });

                var html = ['<div class="course-block">'];
                html.push('<h4>' + esc(course.name)
                    + (course.code ? '（' + esc(course.code) + '）' : '')
                    + '</h4>');
                html.push('<div class="resource-meta">'
                    + '<span class="badge">章节 ' + course.chapter_count + '</span>'
                    + '<span class="badge">知识点 ' + course.kp_count + '</span>'
                    + '<span class="badge">资源 ' + course.resource_count + '</span>'
                    + (course.major ? '<span class="badge">' + esc(course.major)
                        + '</span>' : '')
                    + (course.credit ? '<span class="badge">' + esc(String(course.credit))
                        + ' 学分</span>' : '')
                    + '</div>');

                if (course.description) {
                    html.push('<div class="hint">' + markup(course.description)
                        + '</div>');
                }

                if (courseChapters.length) {
                    html.push('<ul class="chapter-list">');

                    courseChapters.forEach(function (chapter) {
                        var kps = points.filter(function (item) {
                            return item.chapter_id === chapter.id;
                        });

                        html.push('<li>📖 ' + esc(chapter.name)
                            + '（排序 ' + esc(String(chapter.sort_order)) + '）');

                        if (kps.length) {
                            html.push('：' + kps.map(function (kp) {
                                return '<span class="kp">' + esc(kp.name)
                                    + ' · ' + esc(kp.difficulty_label || '') + '</span>';
                            }).join(''));
                        }

                        html.push('</li>');
                    });

                    html.push('</ul>');
                } else {
                    html.push('<div class="hint">该课程还没有章节。</div>');
                }

                html.push('</div>');

                return html.join('');
            }).join('');
        });
    }

    function createCourse() {
        var payload = {
            name: $('newCourseName').value.trim(),
            code: $('newCourseCode').value.trim(),
            major: $('newCourseMajor').value.trim(),
            college: $('newCourseCollege').value.trim()
        };

        var credit = $('newCourseCredit').value;

        if (credit) {
            payload.credit = credit;
        }

        if (!payload.name) {
            setStatus('courseCreateResult', '课程名称不能为空', 'error');
            return;
        }

        setStatus('courseCreateResult', '正在创建…');

        api('/api/courses', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('courseCreateResult', result.error, 'error');
                    return;
                }

                setStatus('courseCreateResult',
                    result.message + '（课程 ID ' + result.course_id + '）',
                    'success');

                $('newCourseName').value = '';
                $('newCourseCode').value = '';
                $('newCourseMajor').value = '';
                $('newCourseCredit').value = '';

                refreshCourseSelects();
            });
    }

    function refreshCourseSelects() {
        api('/api/courses').then(function (result) {
            if (result.error) {
                return;
            }

            state.courses = result.data || [];

            var mapped = state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            });

            fillSelect($('fCourse'), '全部课程', mapped);
            fillSelect($('rCourse'), '不指定', mapped);
            fillSelect($('chapCourse'), '请选择课程', mapped);
            fillSelect($('kpCourse'), '不指定', mapped);
        });
    }

    /* ---------- 资源管理 ---------- */

    function createResource() {
        var payload = {
            title: $('rTitle').value.trim(),
            rtype: $('rType').value || 'other',
            course_id: $('rCourse').value || null,
            chapter_id: $('rChapter').value || null,
            kp_name: $('rKp').value.trim(),
            major: $('rMajor').value.trim(),
            file_path: $('rFilePath').value.trim(),
            external_url: $('rExternalUrl').value.trim(),
            source: $('rSource').value.trim(),
            description: $('rDescription').value.trim(),
            is_demo: $('rIsDemo').checked ? 1 : 0
        };

        if (!payload.title) {
            setStatus('resourceCreateResult', '标题不能为空', 'error');
            return;
        }

        if (!payload.file_path && !payload.external_url) {
            setStatus('resourceCreateResult',
                '必须填写站内文件路径或外部链接', 'error');
            return;
        }

        setStatus('resourceCreateResult', '正在提交…');

        api('/api/resources', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('resourceCreateResult', result.error, 'error');
                    return;
                }

                setStatus('resourceCreateResult',
                    result.message + '（资源 ID ' + result.resource_id + '）',
                    'success');

                ['rTitle', 'rKp', 'rMajor', 'rFilePath', 'rExternalUrl',
                    'rSource', 'rDescription'].forEach(function (id) {
                        $(id).value = '';
                    });

                $('rIsDemo').checked = false;
            });
    }

    function importResources() {
        var raw = $('importJson').value.trim();

        if (!raw) {
            setStatus('importResult', '请粘贴 JSON 数组', 'error');
            return;
        }

        var parsed;

        try {
            parsed = JSON.parse(raw);
        } catch (error) {
            setStatus('importResult', 'JSON 解析失败：' + error.message, 'error');
            return;
        }

        if (!Array.isArray(parsed)) {
            setStatus('importResult', '请求体必须是 JSON 数组', 'error');
            return;
        }

        setStatus('importResult', '正在导入 ' + parsed.length + ' 条…');

        api('/api/resources/import', {
            method: 'POST',
            body: { items: parsed, is_demo: 0 }
        }).then(function (result) {
            if (result.error) {
                setStatus('importResult', result.error, 'error');
                return;
            }

            var message = result.message + '（is_demo=' + result.is_demo + '）';

            if (result.errors && result.errors.length) {
                message += '；失败明细：' + result.errors.map(function (item) {
                    return '第 ' + (item.index + 1) + ' 条 ' + (item.message || '');
                }).join('；');
            }

            setStatus('importResult', message, 'success');
        });
    }

    /* ---------- 班级薄弱点匹配（教师 / 管理员） ---------- */

    function loadClassMatchOptions() {
        api('/api/teacher/classes').then(function (result) {
            if (result.error) {
                setStatus('classMatchStatus', result.error, 'error',
                    loadClassMatchOptions);
                return;
            }

            fillSelect($('cmClass'), '请选择班级', (result.data || []).map(
                function (item) {
                    return {
                        value: item.id,
                        label: item.name + '（' + item.student_count + ' 人）'
                    };
                }
            ));

            if (!(result.data || []).length) {
                setStatus('classMatchStatus',
                    '你还没有被授权任何班级，无法做薄弱点资源匹配。');
            } else {
                setStatus('classMatchStatus', '');
            }
        });
    }

    function loadClassMatch() {
        var classId = $('cmClass').value;

        if (!classId) {
            setStatus('classMatchStatus', '请选择班级', 'error');
            return;
        }

        setStatus('classMatchStatus', '正在匹配…');
        $('classMatchBody').innerHTML = '';

        api('/api/resources/for-class?class_id=' + encodeURIComponent(classId))
            .then(function (result) {
                if (result.error) {
                    setStatus('classMatchStatus', result.error, 'error',
                        loadClassMatch);
                    return;
                }

                var weak = result.weak_points || [];

                if (!weak.length) {
                    setStatus('classMatchStatus', '');
                    $('classMatchBody').innerHTML = emptyState(
                        '该班级学生的错题还没有知识点标注，无法计算薄弱点。'
                    );
                    return;
                }

                setStatus('classMatchStatus',
                    '本班共 ' + weak.length + ' 个薄弱知识点，匹配到 '
                    + result.total + ' 条资源');

                var html = ['<div class="weak-point-list">'];

                weak.forEach(function (item) {
                    html.push('<span class="weak-point">' + esc(item.kp_name)
                        + ' × ' + esc(String(item.total)) + '（'
                        + esc(String(item.student_count)) + ' 人）</span>');
                });

                html.push('</div>');

                if (result.uncovered_points && result.uncovered_points.length) {
                    html.push('<div class="empty-state">以下薄弱知识点目前'
                        + '<strong>还没有</strong>对应资源，建议补充：'
                        + esc(result.uncovered_points.join('、')) + '</div>');
                }

                html.push('<div class="resource-grid">');

                if (result.items.length) {
                    html.push(result.items.map(function (item) {
                        return resourceCard(item, {
                            matchedPoints: item.matched_points
                        });
                    }).join(''));
                } else {
                    html.push(emptyState('知识库中暂时没有覆盖本班薄弱点的资源。'));
                }

                html.push('</div>');

                $('classMatchBody').innerHTML = html.join('');
                bindDownloadButtons($('classMatchBody'));
            });
    }

    /* ---------- 事件绑定 ---------- */

    function bind() {
        $('searchBtn').addEventListener('click', function () {
            state.page = 1;
            loadResources();
        });

        $('resetBtn').addEventListener('click', function () {
            ['fKeyword', 'fCourse', 'fChapter', 'fType', 'fMajor', 'fKp',
                'fDemo'].forEach(function (id) {
                    if ($(id)) {
                        $(id).value = '';
                    }
                });

            state.page = 1;
            loadResources();
        });

        if ($('fCourse') && $('fChapter')) {
            $('fCourse').addEventListener('change', function () {
                fillChapterSelect($('fChapter'), '全部章节', $('fCourse').value);
            });
        }

        if ($('loadRecommendBtn')) {
            $('loadRecommendBtn').addEventListener('click', loadRecommend);
        }

        if ($('loadCoursesBtn')) {
            $('loadCoursesBtn').addEventListener('click', loadCourseTree);
        }

        /* 新建课程表单只有管理员会渲染 */
        if (IS_ADMIN && $('createCourseBtn') && $('newCourseName')) {
            $('createCourseBtn').addEventListener('click', createCourse);
        }

        if (CAN_MANAGE) {
            /* 以下控件只对教师 / 管理员渲染，学生页面没有这些节点 */
            if ($('rCourse') && $('rChapter')) {
                $('rCourse').addEventListener('change', function () {
                    fillChapterSelect($('rChapter'), '不指定', $('rCourse').value);
                });
            }

            if ($('createResourceBtn') && $('rTitle')) {
                $('createResourceBtn').addEventListener('click', createResource);
            }

            if ($('importBtn') && $('importJson')) {
                $('importBtn').addEventListener('click', importResources);
            }

            if ($('loadClassMatchBtn') && $('cmClass')) {
                $('loadClassMatchBtn').addEventListener('click', loadClassMatch);
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTabs();
        bind();
        loadFilters();
    });
})();
