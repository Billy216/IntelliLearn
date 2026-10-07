/* ============================================================
   teacher.js —— 教师工作台（模块八 师生互动 / 模块九 学情报表）
   纯原生 JS：数据全部来自后端真实接口，图表由本文件手写 SVG 绘制，
   不引入任何图表库，也不允许出现任何假数字。
   ============================================================ */
(function () {
    'use strict';

    var API = '/api/teacher';

    // ============================================================
    // 基础工具
    // ============================================================

    /* 统一转义：优先使用全局 ILRender，缺省时本地兜底。
       TODO: 若 static/js/render.js 未加载，这里使用本地转义 +
       换行转换作为降级方案；加载后会自动改用 window.ILRender。 */
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

    /* 富文本（可能含 LaTeX）渲染。
       TODO: window.ILRender 由 static/js/render.js 提供；
       未加载时退化为「转义 + <br>」，保证任何情况下都不会把
       未转义文本塞进 innerHTML。 */
    function markup(text) {
        if (text === null || text === undefined || text === '') {
            return '';
        }

        if (window.ILRender && typeof window.ILRender.render === 'function') {
            try {
                return window.ILRender.render(String(text));
            } catch (error) {
                /* 渲染失败也不能把原文直接注入 */
                return esc(text).replace(/\n/g, '<br>');
            }
        }

        return esc(text).replace(/\n/g, '<br>');
    }

    function $(id) {
        return document.getElementById(id);
    }

    /**
     * 统一请求封装。
     * 无论 HTTP 状态还是业务 success=false，都返回一个带 error 的对象，
     * 由调用方决定如何展示（绝不在失败时提示成功）。
     */
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
                    var message = (data && data.message)
                        || ('请求失败（HTTP ' + response.status + '）');

                    return {
                        error: message,
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

    /* 状态行：支持失败时提供「重试」按钮 */
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

    function fmt(value, suffix) {
        if (value === null || value === undefined || value === '') {
            return '—';
        }

        return String(value) + (suffix || '');
    }

    function pct(value) {
        return (value === null || value === undefined) ? '—' : value + '%';
    }

    // ============================================================
    // 手写 SVG 图表（柱状图 / 饼图），输入必须是真实数据数组
    // ============================================================

    var PALETTE = [
        '#9e62c1', '#4460f1', '#f64f59', '#2e9e6b', '#f0a020',
        '#0aa3c2', '#c471ed', '#7b3fa0', '#d94f8a', '#4b8b3b'
    ];

    function colorAt(index) {
        return PALETTE[index % PALETTE.length];
    }

    /**
     * 横向柱状图。
     * items: [{label, value, extra}]；value 必须为数字。
     */
    function barChart(items, options) {
        options = options || {};

        var valid = (items || []).filter(function (item) {
            return item && typeof item.value === 'number' && isFinite(item.value);
        });

        if (!valid.length) {
            return emptyState(options.emptyText || '暂无数据');
        }

        var max = Math.max.apply(null, valid.map(function (item) {
            return item.value;
        }));

        if (max <= 0) {
            max = 1;
        }

        var rowHeight = 30;
        var labelWidth = options.labelWidth || 190;
        var chartWidth = 620;
        var barMaxWidth = chartWidth - labelWidth - 70;
        var height = valid.length * rowHeight + 12;

        var parts = [
            '<svg viewBox="0 0 ' + chartWidth + ' ' + height +
            '" role="img" aria-label="' + esc(options.ariaLabel || '柱状图') +
            '" preserveAspectRatio="xMinYMin meet">'
        ];

        valid.forEach(function (item, index) {
            var y = index * rowHeight + 4;
            var width = Math.max(2, Math.round(item.value / max * barMaxWidth));
            var label = String(item.label === null || item.label === undefined
                ? '（未填写）' : item.label);

            if (label.length > 18) {
                label = label.slice(0, 17) + '…';
            }

            parts.push(
                '<text class="svg-label" x="0" y="' + (y + 15) + '">' +
                esc(label) + '</text>'
            );
            parts.push(
                '<rect x="' + labelWidth + '" y="' + y + '" width="' + width +
                '" height="18" rx="4" fill="' + colorAt(index) + '"></rect>'
            );
            parts.push(
                '<text class="svg-value" x="' + (labelWidth + width + 8) +
                '" y="' + (y + 14) + '">' + esc(String(item.value)) +
                (item.extra ? esc(' ' + item.extra) : '') + '</text>'
            );
        });

        parts.push('</svg>');

        return parts.join('');
    }

    /**
     * 饼图（含图例）。
     * items: [{label, value}]；总和为 0 时返回空状态。
     */
    function pieChart(items, options) {
        options = options || {};

        var valid = (items || []).filter(function (item) {
            return item && typeof item.value === 'number' && item.value > 0;
        });

        var total = valid.reduce(function (sum, item) {
            return sum + item.value;
        }, 0);

        if (!valid.length || total <= 0) {
            return emptyState(options.emptyText || '暂无数据');
        }

        var size = 220;
        var center = size / 2;
        var radius = 88;
        var angle = -Math.PI / 2;
        var parts = [
            '<svg viewBox="0 0 ' + size + ' ' + size +
            '" role="img" aria-label="' + esc(options.ariaLabel || '饼图') +
            '" style="max-width:240px;margin:0 auto;">'
        ];

        if (valid.length === 1) {
            parts.push(
                '<circle cx="' + center + '" cy="' + center + '" r="' + radius +
                '" fill="' + colorAt(0) + '"></circle>'
            );
        } else {
            valid.forEach(function (item, index) {
                var slice = item.value / total * Math.PI * 2;
                var end = angle + slice;

                var x1 = center + radius * Math.cos(angle);
                var y1 = center + radius * Math.sin(angle);
                var x2 = center + radius * Math.cos(end);
                var y2 = center + radius * Math.sin(end);

                var largeArc = slice > Math.PI ? 1 : 0;

                parts.push(
                    '<path d="M ' + center + ' ' + center +
                    ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2) +
                    ' A ' + radius + ' ' + radius + ' 0 ' + largeArc +
                    ' 1 ' + x2.toFixed(2) + ' ' + y2.toFixed(2) + ' Z" fill="' +
                    colorAt(index) + '"></path>'
                );

                /* 标注百分比（占比 >= 8% 才画，避免文字重叠） */
                if (item.value / total >= 0.08) {
                    var mid = angle + slice / 2;
                    var tx = center + radius * 0.62 * Math.cos(mid);
                    var ty = center + radius * 0.62 * Math.sin(mid);

                    parts.push(
                        '<text class="svg-value" text-anchor="middle" x="' +
                        tx.toFixed(2) + '" y="' + ty.toFixed(2) +
                        '" fill="#fff">' +
                        (item.value / total * 100).toFixed(1) + '%</text>'
                    );
                }

                angle = end;
            });
        }

        parts.push('</svg>');

        /* 图例 + 真实数值（表格形式的可读回退） */
        parts.push('<div class="chart-legend">');

        valid.forEach(function (item, index) {
            parts.push(
                '<span><span class="dot" style="background:' + colorAt(index) +
                '"></span>' + esc(item.label) + '：' + esc(String(item.value)) +
                '（' + (item.value / total * 100).toFixed(1) + '%）</span>'
            );
        });

        parts.push('</div>');

        return parts.join('');
    }

    function statCard(label, value, extra) {
        return '<div class="stat-card">'
            + '<div class="stat-label">' + esc(label) + '</div>'
            + '<div class="stat-value">' + esc(String(value)) + '</div>'
            + (extra ? '<div class="stat-extra">' + esc(extra) + '</div>' : '')
            + '</div>';
    }

    // ============================================================
    // 全局状态
    // ============================================================

    var state = {
        classes: [],
        links: []
    };

    var ERROR_TYPES = [
        '概念理解错误', '计算错误', '步骤错误', '审题错误',
        '公式使用错误', '方法选择不当', '格式不规范', '无明显错误'
    ];

    function classOptions(select, placeholder, useId) {
        if (!select) {
            return;
        }

        select.innerHTML = '';

        if (placeholder) {
            var option = document.createElement('option');
            option.value = '';
            option.textContent = placeholder;
            select.appendChild(option);
        }

        state.classes.forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = String(item.id);
            opt.textContent = item.name
                + (item.student_count !== undefined
                    ? '（' + item.student_count + ' 人）' : '');
            select.appendChild(opt);
        });

        if (useId) {
            select.value = String(useId);
        }
    }

    /* 课程下拉：来自 /api/teacher/courses（教师真实授课关系） */
    function fillCourseSelect(select, withEmpty) {
        if (!select) {
            return;
        }

        select.innerHTML = '';

        if (withEmpty) {
            var option = document.createElement('option');
            option.value = '';
            option.textContent = withEmpty;
            select.appendChild(option);
        }

        var seen = {};

        state.links.forEach(function (link) {
            if (!link.course_id || seen[link.course_id]) {
                return;
            }

            seen[link.course_id] = true;

            var opt = document.createElement('option');
            opt.value = String(link.course_id);
            opt.textContent = (link.course_name || ('课程 #' + link.course_id))
                + (link.class_name ? '（' + link.class_name + '）' : '');
            select.appendChild(opt);
        });
    }

    // ============================================================
    // 初始化
    // ============================================================

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

                if (target === 'tasks') {
                    loadTasks();
                } else if (target === 'qa') {
                    loadQa();
                }
            });
        });
    }

    function loadBasics() {
        setStatus('overviewStatus', '正在读取你的授课班级…');

        return Promise.all([
            api(API + '/classes'),
            api(API + '/courses')
        ]).then(function (results) {
            var classesResult = results[0];
            var coursesResult = results[1];

            if (classesResult.error) {
                setStatus('overviewStatus', classesResult.error, 'error',
                    loadBasics);
                return;
            }

            state.classes = classesResult.data || [];
            state.links = (coursesResult && coursesResult.data) || [];

            if (classesResult.scope_note) {
                $('scopeNote').textContent = classesResult.scope_note
                    + ' 所有数据来自真实错题与练习记录。';
            }

            ['overviewClass', 'studentClass', 'taskClass', 'noticeClass',
                'taskFilterClass'].forEach(function (id) {
                    classOptions($(id),
                        id === 'taskFilterClass' ? '全部班级' : null);
                });

            fillCourseSelect($('overviewCourse'), '全部课程');
            fillCourseSelect($('studentCourse'), '全部课程');
            fillCourseSelect($('taskCourse'), '不指定课程');
            fillCourseSelect($('noticeCourse'), '不指定课程');

            if (!state.classes.length) {
                setStatus('overviewStatus',
                    '你还没有被授权任何班级：请让管理员在「系统管理端 → 班级与授课关系」中'
                    + '为你的账号绑定课程与班级。', 'error', loadBasics);
                return;
            }

            setStatus('overviewStatus', '');
            loadOverview();
        });
    }

    // ============================================================
    // 班级学情报表（模块九）
    // ============================================================

    function loadOverview() {
        var classId = $('overviewClass').value;
        var courseId = $('overviewCourse').value;
        var days = $('overviewDays').value || '30';

        if (!classId) {
            setStatus('overviewStatus', '请先选择班级');
            $('overviewBody').innerHTML = '';
            return;
        }

        setStatus('overviewStatus', '正在统计…');
        $('overviewBody').innerHTML = '';

        var url = API + '/class-report?class_id=' + encodeURIComponent(classId)
            + '&days=' + encodeURIComponent(days);

        if (courseId) {
            url += '&course_id=' + encodeURIComponent(courseId);
        }

        api(url).then(function (result) {
            if (result.error) {
                setStatus('overviewStatus', result.error, 'error', loadOverview);
                return;
            }

            setStatus('overviewStatus',
                '统计完成：课程范围 ' + (courseId || '全部课程')
                + '，时间窗口近 ' + result.data.days + ' 天。');

            renderClassReport(result.data);
        });
    }

    function renderClassReport(data) {
        var summary = data.summary || {};
        var html = [];

        html.push('<div class="stat-grid">');
        html.push(statCard('班级人数', data.class.student_count, '人'));
        html.push(statCard('错题总数', summary.wrong_total,
            '涉及 ' + fmt(summary.wrong_students) + ' 名学生'));
        html.push(statCard('已掌握', summary.mastered,
            '掌握率 ' + pct(summary.mastery_rate)));
        html.push(statCard('未掌握 / 模糊',
            fmt(summary.not_mastered) + ' / ' + fmt(summary.vague)));
        html.push(statCard('复习次数合计', summary.review_total));
        html.push(statCard('练习平均分', fmt(summary.practice_avg_score),
            '共 ' + fmt(summary.practice_times) + ' 次提交'));
        html.push('</div>');

        if (!summary.wrong_total) {
            html.push(emptyState(
                '该班级在当前筛选条件下没有错题记录，因此没有可统计的学情数据。'
            ));
        }

        html.push('<div class="chart-grid">');

        html.push('<div class="chart-box"><h4>高频错题（题目原文 + 出现次数）</h4>'
            + (data.top_questions && data.top_questions.length
                ? '<div class="table-scroll"><table class="data-table">'
                + '<thead><tr><th>#</th><th>题目</th><th>学科/小类</th>'
                + '<th>出现次数</th><th>涉及学生</th></tr></thead><tbody>'
                + data.top_questions.map(function (item, index) {
                    return '<tr><td>' + (index + 1) + '</td>'
                        + '<td class="cell-question">' + markup(item.question)
                        + '</td>'
                        + '<td>' + esc(item.major || '') + ' / '
                        + esc(item.sub || '') + '</td>'
                        + '<td class="num">' + esc(String(item.total)) + '</td>'
                        + '<td class="num">' + esc(String(item.student_count))
                        + '</td></tr>';
                }).join('')
                + '</tbody></table></div>'
                : emptyState('暂无高频错题数据'))
            + '</div>');

        html.push('<div class="chart-box"><h4>知识点错误分布</h4>'
            + barChart((data.by_knowledge_point || []).map(function (item) {
                return {
                    label: item.kp_name,
                    value: item.total,
                    extra: '（' + item.student_count + ' 人）'
                };
            }), { ariaLabel: '知识点错误分布柱状图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>错误类型分布</h4>'
            + pieChart((data.by_error_type || []).map(function (item) {
                return { label: item.error_type, value: item.total };
            }), { ariaLabel: '错误类型分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>掌握度分布</h4>'
            + pieChart((data.by_mastery || []).map(function (item) {
                return { label: item.label, value: item.total };
            }), { ariaLabel: '掌握度分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>近 ' + esc(String(data.days))
            + ' 天新增错题趋势</h4>'
            + barChart((data.trend || []).map(function (item) {
                return { label: item.day, value: item.total };
            }), { ariaLabel: '新增错题趋势柱状图', labelWidth: 100 })
            + '</div>');

        html.push('<div class="chart-box"><h4>学生错题对比</h4>'
            + '<div class="table-scroll"><table class="data-table">'
            + '<thead><tr><th>学号</th><th>姓名</th><th>错题数</th>'
            + '<th>已掌握</th><th>掌握率</th></tr></thead><tbody>'
            + (data.students || []).map(function (item) {
                return '<tr><td>' + esc(item.user_no) + '</td>'
                    + '<td>' + esc(item.real_name || '—') + '</td>'
                    + '<td class="num">' + esc(String(item.wrong_total)) + '</td>'
                    + '<td class="num">' + esc(String(item.mastered_total)) + '</td>'
                    + '<td class="num">' + esc(pct(item.mastery_rate)) + '</td></tr>';
            }).join('')
            + '</tbody></table></div></div>');

        html.push('</div>');

        html.push('<div class="card"><h3>任务完成情况</h3>');

        if (!data.tasks || !data.tasks.length) {
            html.push(emptyState('该班级还没有发布过复习任务。'));
        } else {
            html.push('<div class="table-scroll"><table class="data-table">'
                + '<thead><tr><th>任务</th><th>课程</th><th>截止时间</th>'
                + '<th>应完成</th><th>已完成</th><th>完成率</th>'
                + '<th>平均分</th></tr></thead><tbody>'
                + data.tasks.map(function (item) {
                    return '<tr><td>' + esc(item.title) + '</td>'
                        + '<td>' + esc(item.course_name || '—') + '</td>'
                        + '<td>' + esc(item.due_at || '—') + '</td>'
                        + '<td class="num">' + esc(String(item.student_total))
                        + '</td>'
                        + '<td class="num">' + esc(String(item.done_count))
                        + '</td>'
                        + '<td class="num">' + esc(pct(item.rate)) + '</td>'
                        + '<td class="num">' + esc(fmt(item.avg_score)) + '</td>'
                        + '</tr>';
                }).join('')
                + '</tbody></table></div>');
        }

        html.push('</div>');

        $('overviewBody').innerHTML = html.join('');
    }

    // ============================================================
    // 学生个人报告
    // ============================================================

    function loadClassStudents() {
        var classId = $('studentClass').value;
        var select = $('studentSelect');

        select.innerHTML = '<option value="">加载中…</option>';

        if (!classId) {
            select.innerHTML = '<option value="">请先选择班级</option>';
            return;
        }

        api(API + '/students?class_id=' + encodeURIComponent(classId))
            .then(function (result) {
                if (result.error) {
                    select.innerHTML = '<option value="">加载失败</option>';
                    setStatus('studentStatus', result.error, 'error',
                        loadClassStudents);
                    return;
                }

                select.innerHTML = '';

                if (!result.data.length) {
                    select.innerHTML = '<option value="">该班级还没有学生</option>';
                    setStatus('studentStatus', '该班级暂无学生记录。');
                    return;
                }

                setStatus('studentStatus', '');

                result.data.forEach(function (item) {
                    var option = document.createElement('option');
                    option.value = String(item.id);
                    option.textContent = item.user_no
                        + (item.real_name ? ' ' + item.real_name : '')
                        + '（错题 ' + item.wrong_count + '）';
                    select.appendChild(option);
                });

                loadStudentReport();
            });
    }

    function loadStudentReport() {
        var studentId = $('studentSelect').value;
        var courseId = $('studentCourse').value;

        if (!studentId) {
            setStatus('studentStatus', '请选择学生');
            $('studentBody').innerHTML = '';
            return;
        }

        setStatus('studentStatus', '正在生成报告…');
        $('studentBody').innerHTML = '';

        var url = API + '/student-report?student_id='
            + encodeURIComponent(studentId);

        if (courseId) {
            url += '&course_id=' + encodeURIComponent(courseId);
        }

        api(url).then(function (result) {
            if (result.error) {
                setStatus('studentStatus', result.error, 'error',
                    loadStudentReport);
                return;
            }

            var student = result.data.student;
            setStatus('studentStatus',
                '学生：' + (student.real_name || student.user_no)
                + '（' + student.user_no + '）');

            renderStudentReport(result.data);
        });
    }

    function renderStudentReport(data) {
        var summary = data.summary || {};
        var practice = data.practice_summary || {};
        var html = [];

        html.push('<div class="stat-grid">');
        html.push(statCard('错题总数', summary.wrong_total));
        html.push(statCard('已掌握', summary.mastered,
            '掌握率 ' + pct(summary.mastery_rate)));
        html.push(statCard('未掌握', summary.not_mastered));
        html.push(statCard('模糊', summary.vague));
        html.push(statCard('已复习过的错题', summary.reviewed));
        html.push(statCard('练习次数', practice.times,
            '平均分 ' + fmt(practice.avg_score)));
        html.push('</div>');

        if (!summary.wrong_total) {
            html.push(emptyState('该学生当前筛选条件下没有错题记录。'));
        }

        html.push('<div class="chart-grid">');

        html.push('<div class="chart-box"><h4>知识点薄弱排行</h4>'
            + '<div class="table-scroll"><table class="data-table">'
            + '<thead><tr><th>知识点</th><th>错题数</th><th>已掌握</th>'
            + '<th>未掌握</th></tr></thead><tbody>'
            + ((data.weak_points || []).length
                ? data.weak_points.map(function (item) {
                    return '<tr><td>' + esc(item.kp_name) + '</td>'
                        + '<td class="num">' + esc(String(item.total)) + '</td>'
                        + '<td class="num">' + esc(String(item.mastered)) + '</td>'
                        + '<td class="num">' + esc(String(item.not_mastered))
                        + '</td></tr>';
                }).join('')
                : '<tr><td colspan="4">该学生还没有知识点标注数据</td></tr>')
            + '</tbody></table></div></div>');

        html.push('<div class="chart-box"><h4>错误类型分布</h4>'
            + pieChart((data.by_error_type || []).map(function (item) {
                return { label: item.error_type, value: item.total };
            }), { ariaLabel: '错误类型分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>掌握度分布</h4>'
            + pieChart((data.by_mastery || []).map(function (item) {
                return { label: item.label, value: item.total };
            }), { ariaLabel: '掌握度分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>薄弱知识点错题数</h4>'
            + barChart((data.weak_points || []).map(function (item) {
                return { label: item.kp_name, value: item.total };
            }), { ariaLabel: '薄弱知识点柱状图' })
            + '</div>');

        html.push('</div>');

        html.push('<div class="card"><h3>练习历史</h3>');

        if (!data.practice_history || !data.practice_history.length) {
            html.push(emptyState('该学生还没有练习记录。'));
        } else {
            html.push('<div class="table-scroll"><table class="data-table">'
                + '<thead><tr><th>试卷</th><th>学科</th><th>来源</th>'
                + '<th>题数</th><th>正确</th><th>得分</th><th>提交时间</th>'
                + '</tr></thead><tbody>'
                + data.practice_history.map(function (item) {
                    return '<tr><td>' + esc(item.title || ('试卷 #' + item.paper_id))
                        + '</td><td>' + esc(item.major || '—') + '</td>'
                        + '<td>' + esc(item.source || '—') + '</td>'
                        + '<td class="num">' + esc(String(item.total_count))
                        + '</td>'
                        + '<td class="num">' + esc(String(item.correct_count))
                        + '</td>'
                        + '<td class="num">' + esc(fmt(item.score)) + '</td>'
                        + '<td>' + esc(item.submitted_at || '—') + '</td></tr>';
                }).join('')
                + '</tbody></table></div>');
        }

        html.push('</div>');

        html.push('<div class="card"><h3>所在班级任务完成情况</h3>');

        if (!data.tasks || !data.tasks.length) {
            html.push(emptyState('该学生所在班级还没有发布复习任务。'));
        } else {
            html.push('<div class="table-scroll"><table class="data-table">'
                + '<thead><tr><th>任务</th><th>截止时间</th><th>状态</th>'
                + '<th>得分</th><th>提交时间</th></tr></thead><tbody>'
                + data.tasks.map(function (item) {
                    var status = item.status || 'not_started';
                    var label = status === 'done' ? '已完成'
                        : (status === 'pending' ? '未完成' : '未开始');
                    var cls = status === 'done' ? 'ok' : 'warn';

                    return '<tr><td>' + esc(item.title) + '</td>'
                        + '<td>' + esc(item.due_at || '—') + '</td>'
                        + '<td><span class="badge ' + cls + '">' + esc(label)
                        + '</span></td>'
                        + '<td class="num">' + esc(fmt(item.score)) + '</td>'
                        + '<td>' + esc(item.submitted_at || '—') + '</td></tr>';
                }).join('')
                + '</tbody></table></div>');
        }

        html.push('</div>');

        $('studentBody').innerHTML = html.join('');
    }

    // ============================================================
    // 任务与通知
    // ============================================================

    function createTask() {
        var payload = {
            class_id: $('taskClass').value,
            course_id: $('taskCourse').value || null,
            title: $('taskTitle').value.trim(),
            content: $('taskContent').value.trim(),
            due_at: $('taskDue').value,
            paper_id: $('taskPaper').value || null
        };

        if (!payload.class_id) {
            setStatus('taskResult', '请选择要发布任务的班级', 'error');
            return;
        }

        if (!payload.title) {
            setStatus('taskResult', '任务标题不能为空', 'error');
            return;
        }

        setStatus('taskResult', '正在发布…');

        api(API + '/tasks', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('taskResult', result.error, 'error');
                    return;
                }

                setStatus('taskResult',
                    result.message + '（已为 ' + result.student_count
                    + ' 名学生建立待完成记录）', 'success');

                $('taskTitle').value = '';
                $('taskContent').value = '';
                loadTasks();
            });
    }

    function createNotice() {
        var payload = {
            class_id: $('noticeClass').value,
            course_id: $('noticeCourse').value || null,
            title: $('noticeTitle').value.trim(),
            content: $('noticeContent').value.trim()
        };

        if (!payload.class_id) {
            setStatus('noticeResult', '请选择要发布通知的班级', 'error');
            return;
        }

        if (!payload.content) {
            setStatus('noticeResult', '通知内容不能为空', 'error');
            return;
        }

        setStatus('noticeResult', '正在发布…');

        api(API + '/notices', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('noticeResult', result.error, 'error');
                    return;
                }

                setStatus('noticeResult',
                    result.message + '：' + result.title, 'success');

                $('noticeTitle').value = '';
                $('noticeContent').value = '';
                loadTasks();
            });
    }

    function loadTasks() {
        var classId = $('taskFilterClass').value;
        var url = API + '/tasks';

        if (classId) {
            url += '?class_id=' + encodeURIComponent(classId);
        }

        setStatus('taskListStatus', '正在读取任务列表…');

        api(url).then(function (result) {
            if (result.error) {
                setStatus('taskListStatus', result.error, 'error', loadTasks);
                return;
            }

            if (!result.data.length) {
                setStatus('taskListStatus', '');
                $('taskList').innerHTML = emptyState(
                    '你还没有发布过复习任务或错题讲解通知。'
                );
                return;
            }

            setStatus('taskListStatus',
                '共 ' + result.data.length + ' 条（按发布时间倒序）');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>类型</th><th>标题</th><th>班级</th>',
                '<th>课程</th><th>截止时间</th><th>应完成</th><th>已完成</th>',
                '<th>完成率</th><th>平均分</th><th>操作</th></tr></thead><tbody>'];

            result.data.forEach(function (item) {
                html.push('<tr>'
                    + '<td><span class="badge'
                    + (item.is_notice ? ' warn' : '') + '">'
                    + (item.is_notice ? '讲解通知' : '复习任务') + '</span></td>'
                    + '<td>' + esc(item.title) + '</td>'
                    + '<td>' + esc(item.class_name || '—') + '</td>'
                    + '<td>' + esc(item.course_name || '—') + '</td>'
                    + '<td>' + esc(item.due_at || '—') + '</td>'
                    + '<td class="num">' + esc(String(item.student_total)) + '</td>'
                    + '<td class="num">' + esc(String(item.done_count)) + '</td>'
                    + '<td class="num">' + esc(pct(item.rate)) + '</td>'
                    + '<td class="num">' + esc(fmt(item.avg_score)) + '</td>'
                    + '<td><button class="btn-mini" data-task="' + item.id
                    + '">查看完成情况</button></td>'
                    + '</tr>');

                html.push('<tr id="subs-' + item.id + '" hidden><td colspan="10">'
                    + '<div class="status-line">加载中…</div></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('taskList').innerHTML = html.join('');

            Array.prototype.forEach.call(
                $('taskList').querySelectorAll('button[data-task]'),
                function (button) {
                    button.addEventListener('click', function () {
                        toggleSubmissions(button.getAttribute('data-task'),
                            button);
                    });
                }
            );
        });
    }

    function toggleSubmissions(taskId, button) {
        var row = $('subs-' + taskId);

        if (!row) {
            return;
        }

        if (!row.hidden) {
            row.hidden = true;
            button.textContent = '查看完成情况';
            return;
        }

        row.hidden = false;
        button.textContent = '收起';

        var cell = row.querySelector('td');

        api(API + '/tasks/' + taskId + '/submissions').then(function (result) {
            if (result.error) {
                cell.innerHTML = '<div class="status-line error">'
                    + esc(result.error) + '</div>';
                return;
            }

            var summary = result.summary || {};

            var html = ['<div class="status-line">应完成 '
                + esc(String(summary.student_total)) + ' 人，已完成 '
                + esc(String(summary.done_count)) + ' 人，完成率 '
                + esc(pct(summary.rate)) + '</div>'];

            html.push('<div class="table-scroll"><table class="data-table">'
                + '<thead><tr><th>学号</th><th>姓名</th><th>状态</th>'
                + '<th>得分</th><th>提交时间</th></tr></thead><tbody>');

            result.data.forEach(function (item) {
                var cls = item.status === 'done' ? 'ok'
                    : (item.status === 'pending' ? 'warn' : '');

                html.push('<tr><td>' + esc(item.user_no) + '</td>'
                    + '<td>' + esc(item.real_name || '—') + '</td>'
                    + '<td><span class="badge ' + cls + '">'
                    + esc(item.status_label) + '</span></td>'
                    + '<td class="num">' + esc(fmt(item.score)) + '</td>'
                    + '<td>' + esc(item.submitted_at || '—') + '</td></tr>');
            });

            html.push('</tbody></table></div>');

            cell.innerHTML = html.join('');
        });
    }

    // ============================================================
    // 答疑
    // ============================================================

    function loadQa() {
        var status = $('qaStatus').value;
        var url = API + '/questions';

        if (status) {
            url += '?status=' + encodeURIComponent(status);
        }

        setStatus('qaStatusLine', '正在读取学生提问…');

        api(url).then(function (result) {
            if (result.error) {
                setStatus('qaStatusLine', result.error, 'error', loadQa);
                return;
            }

            if (!result.data.length) {
                setStatus('qaStatusLine', '');
                $('qaList').innerHTML = emptyState(
                    '当前筛选条件下没有学生提问。'
                );
                return;
            }

            var open = result.data.filter(function (item) {
                return item.status === 'open';
            }).length;

            setStatus('qaStatusLine',
                '共 ' + result.data.length + ' 条，其中待回复 ' + open + ' 条');

            var dot = $('qaDot');

            if (dot) {
                dot.hidden = open === 0;
            }

            var html = [];

            result.data.forEach(function (item) {
                var statusLabel = item.status === 'answered' ? '已回复'
                    : (item.status === 'closed' ? '已关闭' : '待回复');
                var statusClass = item.status === 'answered' ? 'ok'
                    : (item.status === 'closed' ? '' : 'warn');

                html.push('<div class="qa-item">');
                html.push('<div class="qa-head">'
                    + '<span class="qa-title">' + esc(item.title) + '</span>'
                    + '<span><span class="badge ' + statusClass + '">'
                    + esc(statusLabel) + '</span> '
                    + '<span class="badge">' + esc(item.student_no || '') + '</span>'
                    + '</span></div>');
                html.push('<div class="qa-body">' + markup(item.question)
                    + '</div>');

                if (item.image_url) {
                    html.push('<div class="hint">附图：<a href="'
                        + esc(item.image_url) + '" target="_blank"'
                        + ' rel="noopener">查看图片</a></div>');
                }

                html.push('<div class="hint">提交时间：'
                    + esc(item.created_at || '—')
                    + (item.class_name ? ' · 班级：' + esc(item.class_name) : '')
                    + '</div>');

                (item.replies || []).forEach(function (reply) {
                    html.push('<div class="qa-reply"><div class="who">'
                        + esc(reply.real_name || reply.user_no || '用户')
                        + '（' + esc(reply.role) + '） · '
                        + esc(reply.created_at) + '</div>'
                        + markup(reply.content) + '</div>');
                });

                if (item.status !== 'closed') {
                    html.push('<textarea rows="3" id="reply-'
                        + item.id + '" placeholder="写下你的讲解…"></textarea>');
                    html.push('<div class="resource-actions">'
                        + '<button class="btn-primary" data-reply="' + item.id
                        + '">发送回复</button></div>');
                    html.push('<div class="hint" id="replymsg-'
                        + item.id + '"></div>');
                }

                html.push('</div>');
            });

            $('qaList').innerHTML = html.join('');

            Array.prototype.forEach.call(
                $('qaList').querySelectorAll('button[data-reply]'),
                function (button) {
                    button.addEventListener('click', function () {
                        submitReply(button.getAttribute('data-reply'), button);
                    });
                }
            );
        });
    }

    function submitReply(questionId, button) {
        var textarea = $('reply-' + questionId);
        var content = (textarea.value || '').trim();

        if (!content) {
            setStatus('replymsg-' + questionId, '回复内容不能为空', 'error');
            return;
        }

        button.disabled = true;
        setStatus('replymsg-' + questionId, '正在发送…');

        api(API + '/questions/' + questionId + '/reply', {
            method: 'POST',
            body: { content: content }
        }).then(function (result) {
            button.disabled = false;

            if (result.error) {
                setStatus('replymsg-' + questionId, result.error, 'error');
                return;
            }

            setStatus('replymsg-' + questionId, '回复已发送', 'success');
            loadQa();
        });
    }

    // ============================================================
    // 错题标注纠正与题库
    // ============================================================

    function submitReview() {
        var questionId = $('reviewWqId').value;
        var payload = {};

        if (!questionId) {
            setStatus('reviewResult', '请填写错题 ID', 'error');
            return;
        }

        if ($('reviewKps').value.trim()) {
            payload.knowledge_points = $('reviewKps').value.trim();
        }

        if ($('reviewErrorType').value) {
            payload.error_type = $('reviewErrorType').value;
        }

        if ($('reviewMastery').value !== '') {
            payload.mastery = Number($('reviewMastery').value);
        }

        if (!Object.keys(payload).length) {
            setStatus('reviewResult', '请至少填写一项要修改的内容', 'error');
            return;
        }

        setStatus('reviewResult', '正在提交…');

        api(API + '/wrong-questions/' + encodeURIComponent(questionId), {
            method: 'PATCH',
            body: payload
        }).then(function (result) {
            if (result.error) {
                setStatus('reviewResult', result.error, 'error');
                return;
            }

            setStatus('reviewResult', result.message, 'success');
        });
    }

    function submitBank() {
        var payload = {
            course_id: $('bankCourse').value || null,
            chapter_id: $('bankChapter').value || null,
            major: $('bankMajor').value.trim(),
            kp_name: $('bankKp').value.trim(),
            qtype: $('bankQtype').value,
            difficulty: $('bankDifficulty').value,
            question: $('bankQuestion').value.trim(),
            answer: $('bankAnswer').value.trim(),
            analysis: $('bankAnalysis').value.trim()
        };

        var optionsRaw = $('bankOptions').value.trim();

        if (optionsRaw) {
            try {
                payload.options = JSON.parse(optionsRaw);
            } catch (error) {
                setStatus('bankResult', '选项不是合法 JSON：' + error.message,
                    'error');
                return;
            }
        }

        if (!payload.question) {
            setStatus('bankResult', '题干不能为空', 'error');
            return;
        }

        setStatus('bankResult', '正在写入题库…');

        api(API + '/question-bank', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('bankResult', result.error, 'error');
                    return;
                }

                setStatus('bankResult',
                    result.message + '（题目 ID ' + result.question_id
                    + '，verified=' + result.verified + '）', 'success');
            });
    }

    // ============================================================
    // 事件绑定
    // ============================================================

    function bind() {
        $('loadOverviewBtn').addEventListener('click', loadOverview);
        $('overviewClass').addEventListener('change', loadOverview);
        $('overviewCourse').addEventListener('change', loadOverview);
        $('overviewDays').addEventListener('change', loadOverview);

        $('studentClass').addEventListener('change', loadClassStudents);
        $('loadStudentBtn').addEventListener('click', loadStudentReport);
        $('studentCourse').addEventListener('change', loadStudentReport);

        $('createTaskBtn').addEventListener('click', createTask);
        $('createNoticeBtn').addEventListener('click', createNotice);
        $('reloadTasksBtn').addEventListener('click', loadTasks);
        $('taskFilterClass').addEventListener('change', loadTasks);

        $('loadQaBtn').addEventListener('click', loadQa);
        $('qaStatus').addEventListener('change', loadQa);

        $('submitReviewBtn').addEventListener('click', submitReview);
        $('submitBankBtn').addEventListener('click', submitBank);

        var errorSelect = $('reviewErrorType');

        ERROR_TYPES.forEach(function (item) {
            var option = document.createElement('option');
            option.value = item;
            option.textContent = item;
            errorSelect.appendChild(option);
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initTabs();
        bind();
        loadBasics();
    });
})();
