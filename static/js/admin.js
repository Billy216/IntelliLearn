/* ============================================================
   admin.js —— 系统管理端（模块十）
   所有数字来自 /api/admin/* 真实聚合；没有任何演示数据。
   前端会隐藏当前角色不能执行的操作，服务端会独立再校验一次。
   ============================================================ */
(function () {
    'use strict';

    var ROLE = document.body.getAttribute('data-role') || '';
    var IS_ADMIN = ROLE === 'admin';
    var OPERATOR_ID = null;

    var state = {
        usersPage: 1,
        usersPageSize: 10,
        usersTotal: 0,
        questionsPage: 1,
        questionsPageSize: 10,
        logsPage: 1,
        logsPageSize: 20,
        classes: [],
        courses: [],
        chapters: []
    };

    /* ---------- 基础工具 ---------- */

    /* TODO: window.ILRender 由 static/js/render.js 提供；
       未加载时使用本地转义 + 换行转换作为降级方案。 */
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

    function pct(value) {
        return (value === null || value === undefined) ? '—' : value + '%';
    }

    function fmt(value) {
        return (value === null || value === undefined || value === '')
            ? '—' : String(value);
    }

    /* ---------- 手写 SVG 图表 ---------- */

    var PALETTE = [
        '#9e62c1', '#4460f1', '#f64f59', '#2e9e6b', '#f0a020',
        '#0aa3c2', '#c471ed', '#7b3fa0', '#d94f8a', '#4b8b3b'
    ];

    function colorAt(index) {
        return PALETTE[index % PALETTE.length];
    }

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

        var parts = ['<svg viewBox="0 0 ' + chartWidth + ' ' + height
            + '" role="img" aria-label="' + esc(options.ariaLabel || '柱状图')
            + '" preserveAspectRatio="xMinYMin meet">'];

        valid.forEach(function (item, index) {
            var y = index * rowHeight + 4;
            var width = Math.max(2, Math.round(item.value / max * barMaxWidth));
            var label = String(item.label === null || item.label === undefined
                ? '（未填写）' : item.label);

            if (label.length > 18) {
                label = label.slice(0, 17) + '…';
            }

            parts.push('<text class="svg-label" x="0" y="' + (y + 15) + '">'
                + esc(label) + '</text>');
            parts.push('<rect x="' + labelWidth + '" y="' + y + '" width="'
                + width + '" height="18" rx="4" fill="' + colorAt(index)
                + '"></rect>');
            parts.push('<text class="svg-value" x="' + (labelWidth + width + 8)
                + '" y="' + (y + 14) + '">' + esc(String(item.value))
                + (item.extra ? esc(' ' + item.extra) : '') + '</text>');
        });

        parts.push('</svg>');

        return parts.join('');
    }

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
        var parts = ['<svg viewBox="0 0 ' + size + ' ' + size
            + '" role="img" aria-label="' + esc(options.ariaLabel || '饼图')
            + '" style="max-width:240px;margin:0 auto;">'];

        if (valid.length === 1) {
            parts.push('<circle cx="' + center + '" cy="' + center + '" r="'
                + radius + '" fill="' + colorAt(0) + '"></circle>');
        } else {
            valid.forEach(function (item, index) {
                var slice = item.value / total * Math.PI * 2;
                var end = angle + slice;

                var x1 = center + radius * Math.cos(angle);
                var y1 = center + radius * Math.sin(angle);
                var x2 = center + radius * Math.cos(end);
                var y2 = center + radius * Math.sin(end);

                parts.push('<path d="M ' + center + ' ' + center
                    + ' L ' + x1.toFixed(2) + ' ' + y1.toFixed(2)
                    + ' A ' + radius + ' ' + radius + ' 0 '
                    + (slice > Math.PI ? 1 : 0) + ' 1 ' + x2.toFixed(2) + ' '
                    + y2.toFixed(2) + ' Z" fill="' + colorAt(index) + '"></path>');

                angle = end;
            });
        }

        parts.push('</svg>');
        parts.push('<div class="chart-legend">');

        valid.forEach(function (item, index) {
            parts.push('<span><span class="dot" style="background:'
                + colorAt(index) + '"></span>' + esc(item.label) + '：'
                + esc(String(item.value)) + '（'
                + (item.value / total * 100).toFixed(1) + '%）</span>');
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

                if (target === 'users') {
                    loadUsers();
                } else if (target === 'classes') {
                    loadClasses();
                    loadTeacherCourses();
                } else if (target === 'courses') {
                    loadCourseTree();
                } else if (target === 'questions') {
                    loadQuestions();
                } else if (target === 'logs') {
                    loadLogs();
                } else if (target === 'system') {
                    loadSettings();
                    loadBackups();
                    loadSso();
                }
            });
        });
    }

    /* ============================================================
       全校统计
       ============================================================ */

    function loadStats() {
        setStatus('statsStatus', '正在统计…');

        api('/api/admin/stats').then(function (result) {
            if (result.error) {
                setStatus('statsStatus', result.error, 'error', loadStats);
                return;
            }

            var data = result.data || {};

            if (data.scope !== 'school') {
                setStatus('statsStatus',
                    '当前返回的是你授权范围内的统计（scope=' + data.scope + '）。');
            } else {
                setStatus('statsStatus', '统计时间：' + fmt(data.generated_at));
            }

            renderStats(data);
        });
    }

    function renderStats(data) {
        var users = data.users || {};
        var wrong = data.wrong_questions || {};
        var resources = data.resources || {};
        var practice = data.practice || {};
        var teaching = data.teaching || {};
        var html = [];

        html.push('<div class="stat-grid">');
        html.push(statCard('用户总数', users.total,
            '正常 ' + fmt(users.active) + ' / 冻结 ' + fmt(users.frozen)));
        html.push(statCard('错题总数', wrong.total,
            '涉及 ' + fmt(wrong.students) + ' 名学生'));
        html.push(statCard('整体掌握率', pct(wrong.mastery_rate),
            '已掌握 ' + fmt(wrong.mastered) + ' 条'));
        html.push(statCard('资源总数', resources.total,
            '其中演示数据 ' + fmt(resources.demo_count) + ' 条'));
        html.push(statCard('资源下载次数', resources.downloads));
        html.push(statCard('练习提交次数', practice.times,
            '平均分 ' + fmt(practice.avg_score)));
        html.push(statCard('练习正确率', pct(practice.accuracy),
            fmt(practice.correct_questions) + ' / '
            + fmt(practice.total_questions) + ' 题'));
        html.push(statCard('课程 / 班级', fmt(teaching.courses) + ' / '
            + fmt(teaching.classes),
            '知识点 ' + fmt(teaching.knowledge_points)));
        html.push('</div>');

        if (resources.demo_count) {
            html.push('<div class="warn-box">注意：资源库中有 '
                + esc(String(resources.demo_count))
                + ' 条演示数据（is_demo=1），它们不是学校真实资料，'
                + '请勿当成校方课件或试卷使用。</div>');
        }

        html.push('<div class="chart-grid">');

        html.push('<div class="chart-box"><h4>用户角色分布</h4>'
            + pieChart((users.by_role || []).map(function (item) {
                return { label: item.role_label, value: item.total };
            }), { ariaLabel: '用户角色分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>错误类型分布</h4>'
            + pieChart((data.by_error_type || []).map(function (item) {
                return { label: item.error_type, value: item.total };
            }), { ariaLabel: '错误类型分布饼图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>资源类型分布</h4>'
            + barChart((resources.by_type || []).map(function (item) {
                return {
                    label: item.rtype_label,
                    value: item.total,
                    extra: '（下载 ' + item.downloads + '）'
                };
            }), { ariaLabel: '资源类型分布柱状图' })
            + '</div>');

        html.push('<div class="chart-box"><h4>全校高频知识点 TOP20</h4>'
            + barChart((data.top_knowledge_points || []).map(function (item) {
                return {
                    label: item.kp_name,
                    value: item.total,
                    extra: '（' + item.student_count + ' 人）'
                };
            }), { ariaLabel: '全校高频知识点柱状图' })
            + '</div>');

        html.push('</div>');

        /* 数据表回退（图表之外始终能看到真实数字） */
        html.push('<div class="card"><h3>统计明细表</h3>'
            + '<div class="table-scroll"><table class="data-table">'
            + '<thead><tr><th>指标</th><th>数值</th></tr></thead><tbody>'
            + '<tr><td>用户总数</td><td class="num">' + esc(fmt(users.total))
            + '</td></tr>'
            + '<tr><td>正常 / 冻结账号</td><td class="num">'
            + esc(fmt(users.active) + ' / ' + fmt(users.frozen)) + '</td></tr>'
            + '<tr><td>错题总数</td><td class="num">' + esc(fmt(wrong.total))
            + '</td></tr>'
            + '<tr><td>未掌握 / 模糊 / 已掌握</td><td class="num">'
            + esc(fmt(wrong.not_mastered) + ' / ' + fmt(wrong.vague) + ' / '
                + fmt(wrong.mastered)) + '</td></tr>'
            + '<tr><td>课程 / 章节 / 知识点</td><td class="num">'
            + esc(fmt(teaching.courses) + ' / ' + fmt(teaching.chapters) + ' / '
                + fmt(teaching.knowledge_points)) + '</td></tr>'
            + '<tr><td>班级 / 授课关系</td><td class="num">'
            + esc(fmt(teaching.classes) + ' / ' + fmt(teaching.teacher_courses))
            + '</td></tr>'
            + '<tr><td>题库题目（在用）</td><td class="num">'
            + esc(fmt(teaching.questions)) + '</td></tr>'
            + '<tr><td>复习任务</td><td class="num">' + esc(fmt(teaching.tasks))
            + '</td></tr>'
            + '<tr><td>学生提问 / 已回复</td><td class="num">'
            + esc(fmt(teaching.questions_asked) + ' / '
                + fmt(teaching.questions_answered)) + '</td></tr>'
            + '<tr><td>资源总数（在用）</td><td class="num">'
            + esc(fmt(teaching.resources)) + '</td></tr>'
            + '</tbody></table></div></div>');

        $('statsBody').innerHTML = html.join('');
    }

    /* ============================================================
       用户管理
       ============================================================ */

    function loadUsers() {
        var params = ['page=' + state.usersPage,
            'page_size=' + state.usersPageSize];

        if ($('uKeyword').value.trim()) {
            params.push('keyword=' + encodeURIComponent($('uKeyword').value.trim()));
        }

        if ($('uRole').value) {
            params.push('role=' + encodeURIComponent($('uRole').value));
        }

        if ($('uStatus').value !== '') {
            params.push('status=' + encodeURIComponent($('uStatus').value));
        }

        setStatus('usersStatus', '正在读取用户…');

        api('/api/admin/users?' + params.join('&')).then(function (result) {
            if (result.error) {
                setStatus('usersStatus', result.error, 'error', loadUsers);
                return;
            }

            OPERATOR_ID = result.operator_id;
            state.usersTotal = result.total;

            if (!result.data.length) {
                setStatus('usersStatus', '没有符合条件的用户。');
                $('usersBody').innerHTML = emptyState('当前筛选条件下没有用户记录。');
                $('usersPager').innerHTML = '';
                return;
            }

            setStatus('usersStatus', '共 ' + result.total + ' 名用户');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>ID</th><th>账号</th><th>姓名</th><th>角色</th>',
                '<th>学院</th><th>邮箱</th><th>状态</th><th>操作</th>',
                '</tr></thead><tbody>'];

            result.data.forEach(function (item) {
                var isSelf = item.id === OPERATOR_ID;
                var frozen = item.status === 0;

                html.push('<tr>'
                    + '<td>' + esc(String(item.id)) + '</td>'
                    + '<td>' + esc(item.user_no) + '</td>'
                    + '<td>' + esc(item.real_name || '—') + '</td>'
                    + '<td><span class="badge">' + esc(item.role_label)
                    + '</span></td>'
                    + '<td>' + esc(item.college || '—') + '</td>'
                    + '<td>' + esc(item.email || '—') + '</td>'
                    + '<td><span class="badge ' + (frozen ? 'danger' : 'ok')
                    + '">' + (frozen ? '已冻结' : '正常') + '</span>'
                    + (isSelf ? ' <span class="badge warn">当前账号</span>' : '')
                    + '</td>'
                    + '<td class="actions">');

                /* 前端隐藏掉角色不能做的操作；服务端仍会独立拒绝 */
                if (!isSelf) {
                    html.push('<button class="btn-mini" data-role-user="'
                        + item.id + '">改角色</button>');

                    if (frozen) {
                        html.push('<button class="btn-mini" data-unfreeze="'
                            + item.id + '">解冻</button>');
                    } else {
                        html.push('<button class="btn-mini danger" data-freeze="'
                            + item.id + '">冻结</button>');
                    }
                } else {
                    html.push('<span class="hint">不能修改自己的角色或状态</span>');
                }

                html.push('</td></tr>');
            });

            html.push('</tbody></table></div>');

            $('usersBody').innerHTML = html.join('');

            bindUserActions(result.data);
            renderUsersPager(result.total, result.page, result.page_size);
        });
    }

    function bindUserActions(users) {
        var container = $('usersBody');

        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-freeze]'),
            function (button) {
                button.addEventListener('click', function () {
                    patchUser(button.getAttribute('data-freeze'),
                        { status: 0 }, '冻结');
                });
            }
        );

        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-unfreeze]'),
            function (button) {
                button.addEventListener('click', function () {
                    patchUser(button.getAttribute('data-unfreeze'),
                        { status: 1 }, '解冻');
                });
            }
        );

        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-role-user]'),
            function (button) {
                button.addEventListener('click', function () {
                    var userId = button.getAttribute('data-role-user');
                    var target = users.filter(function (item) {
                        return String(item.id) === String(userId);
                    })[0];

                    var next = window.prompt(
                        '把用户 ' + (target ? target.user_no : userId)
                        + ' 的角色改为（student / teacher / admin）：',
                        target ? target.role : 'student'
                    );

                    if (next === null) {
                        return;
                    }

                    if (['student', 'teacher', 'admin'].indexOf(next.trim()) === -1) {
                        setStatus('usersStatus',
                            '角色只能是 student / teacher / admin', 'error');
                        return;
                    }

                    patchUser(userId, { role: next.trim() }, '修改角色');
                });
            }
        );
    }

    function patchUser(userId, payload, label) {
        setStatus('usersStatus', '正在' + label + '…');

        api('/api/admin/users/' + userId, { method: 'PATCH', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('usersStatus', result.error, 'error');
                    return;
                }

                setStatus('usersStatus', label + '成功：'
                    + (result.changes || []).join('；'), 'success');
                loadUsers();
            });
    }

    function renderUsersPager(total, page, pageSize) {
        var pages = Math.max(1, Math.ceil(total / pageSize));

        $('usersPager').innerHTML = '<button class="btn-secondary" id="uPrev"'
            + (page <= 1 ? ' disabled' : '') + '>上一页</button>'
            + '<span>第 ' + page + ' / ' + pages + ' 页</span>'
            + '<button class="btn-secondary" id="uNext"'
            + (page >= pages ? ' disabled' : '') + '>下一页</button>';

        var prev = $('uPrev');
        var next = $('uNext');

        if (prev) {
            prev.addEventListener('click', function () {
                state.usersPage = Math.max(1, state.usersPage - 1);
                loadUsers();
            });
        }

        if (next) {
            next.addEventListener('click', function () {
                state.usersPage = state.usersPage + 1;
                loadUsers();
            });
        }
    }

    function createUser() {
        var payload = {
            user_no: $('newUserNo').value.trim(),
            password: $('newUserPassword').value,
            role: $('newUserRole').value,
            real_name: $('newUserRealName').value.trim(),
            college: $('newUserCollege').value.trim(),
            email: $('newUserEmail').value.trim()
        };

        if (!payload.user_no || !payload.password) {
            setStatus('createUserResult', '账号与初始密码不能为空', 'error');
            return;
        }

        setStatus('createUserResult', '正在创建…');

        api('/api/admin/users', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('createUserResult', result.error, 'error');
                    return;
                }

                setStatus('createUserResult',
                    result.message + '（用户 ID ' + result.user_id + '）',
                    'success');

                $('newUserNo').value = '';
                $('newUserPassword').value = '';
                $('newUserRealName').value = '';
                $('newUserEmail').value = '';

                loadUsers();
            });
    }

    /* ============================================================
       班级与授课关系
       ============================================================ */

    function loadClasses() {
        setStatus('classesStatus', '正在读取班级…');

        api('/api/admin/classes').then(function (result) {
            if (result.error) {
                setStatus('classesStatus', result.error, 'error', loadClasses);
                return;
            }

            state.classes = result.data || [];

            fillSelect($('tcClass'), '请选择班级', state.classes.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            if (!state.classes.length) {
                setStatus('classesStatus', '还没有任何班级记录。');
                $('classesBody').innerHTML = emptyState(
                    '本校还没有班级，请先在左侧创建班级。'
                );
                return;
            }

            setStatus('classesStatus', '共 ' + state.classes.length + ' 个班级');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>ID</th><th>班级</th><th>学院</th><th>年级</th>',
                '<th>人数</th><th>授课关系</th><th>备注</th><th>操作</th>',
                '</tr></thead><tbody>'];

            state.classes.forEach(function (item) {
                html.push('<tr>'
                    + '<td>' + esc(String(item.id)) + '</td>'
                    + '<td>' + esc(item.name) + '</td>'
                    + '<td>' + esc(item.college || '—') + '</td>'
                    + '<td>' + esc(fmt(item.grade_year)) + '</td>'
                    + '<td class="num">' + esc(String(item.student_count)) + '</td>'
                    + '<td class="num">' + esc(String(item.link_count)) + '</td>'
                    + '<td>' + esc(item.remark || '—') + '</td>'
                    + '<td class="actions">'
                    + '<button class="btn-mini" data-class-students="' + item.id
                    + '">学生名单</button>'
                    + '<button class="btn-mini" data-class-add="' + item.id
                    + '">加入学生</button>'
                    + '</td></tr>');

                html.push('<tr id="class-students-' + item.id
                    + '" hidden><td colspan="8"><div class="status-line">'
                    + '加载中…</div></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('classesBody').innerHTML = html.join('');

            bindClassActions();
        });
    }

    function bindClassActions() {
        var container = $('classesBody');

        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-class-students]'),
            function (button) {
                button.addEventListener('click', function () {
                    toggleClassStudents(button.getAttribute('data-class-students'),
                        button);
                });
            }
        );

        Array.prototype.forEach.call(
            container.querySelectorAll('button[data-class-add]'),
            function (button) {
                button.addEventListener('click', function () {
                    var classId = button.getAttribute('data-class-add');

                    var raw = window.prompt(
                        '输入要加入该班级的用户 ID，多个用逗号分隔：'
                    );

                    if (!raw) {
                        return;
                    }

                    var ids = raw.split(',').map(function (item) {
                        return parseInt(item.trim(), 10);
                    }).filter(function (item) {
                        return !isNaN(item) && item > 0;
                    });

                    if (!ids.length) {
                        setStatus('classesStatus', '没有解析到合法的用户 ID', 'error');
                        return;
                    }

                    api('/api/admin/classes/' + classId + '/students', {
                        method: 'POST',
                        body: { user_ids: ids }
                    }).then(function (result) {
                        if (result.error) {
                            setStatus('classesStatus', result.error, 'error');
                            return;
                        }

                        setStatus('classesStatus', result.message, 'success');
                        loadClasses();
                    });
                });
            }
        );
    }

    function toggleClassStudents(classId, button) {
        var row = $('class-students-' + classId);

        if (!row) {
            return;
        }

        if (!row.hidden) {
            row.hidden = true;
            button.textContent = '学生名单';
            return;
        }

        row.hidden = false;
        button.textContent = '收起';

        var cell = row.querySelector('td');

        api('/api/admin/classes/' + classId + '/students').then(function (result) {
            if (result.error) {
                cell.innerHTML = '<div class="status-line error">'
                    + esc(result.error) + '</div>';
                return;
            }

            if (!result.data.length) {
                cell.innerHTML = emptyState('该班级还没有学生。');
                return;
            }

            var html = ['<table class="data-table"><thead><tr><th>ID</th>'
                + '<th>学号</th><th>姓名</th><th>学院</th><th>加入时间</th>'
                + '<th>操作</th></tr></thead><tbody>'];

            result.data.forEach(function (item) {
                html.push('<tr><td>' + esc(String(item.id)) + '</td>'
                    + '<td>' + esc(item.user_no) + '</td>'
                    + '<td>' + esc(item.real_name || '—') + '</td>'
                    + '<td>' + esc(item.college || '—') + '</td>'
                    + '<td>' + esc(item.joined_at || '—') + '</td>'
                    + '<td class="actions"><button class="btn-mini danger"'
                    + ' data-remove-student="' + item.id + '" data-class="'
                    + classId + '">移出班级</button></td></tr>');
            });

            html.push('</tbody></table>');

            cell.innerHTML = html.join('');

            Array.prototype.forEach.call(
                cell.querySelectorAll('button[data-remove-student]'),
                function (removeButton) {
                    removeButton.addEventListener('click', function () {
                        var userId = removeButton.getAttribute('data-remove-student');
                        var targetClass = removeButton.getAttribute('data-class');

                        api('/api/admin/classes/' + targetClass + '/students/'
                            + userId, { method: 'DELETE' }).then(function (result) {
                                if (result.error) {
                                    setStatus('classesStatus', result.error, 'error');
                                    return;
                                }

                                setStatus('classesStatus', result.message, 'success');
                                loadClasses();
                            });
                    });
                }
            );
        });
    }

    function loadTeacherCourses() {
        setStatus('tcStatus', '正在读取授课关系…');

        Promise.all([
            api('/api/admin/teacher-courses'),
            api('/api/admin/teachers'),
            api('/api/courses')
        ]).then(function (results) {
            var linksResult = results[0];

            if (linksResult.error) {
                setStatus('tcStatus', linksResult.error, 'error', loadTeacherCourses);
                return;
            }

            var teachers = (results[1] && results[1].data) || [];
            state.courses = (results[2] && results[2].data) || [];

            fillSelect($('tcTeacher'), '请选择教师', teachers.map(function (item) {
                return {
                    value: item.id,
                    label: item.user_no + (item.real_name
                        ? ' ' + item.real_name : '')
                        + '（' + item.role_label + '）'
                };
            }));

            fillSelect($('tcCourse'), '请选择课程', state.courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            if (!linksResult.data.length) {
                setStatus('tcStatus', '还没有任何授课关系。教师端所有权限都来自这里。');
                $('tcBody').innerHTML = emptyState(
                    '没有授课关系时，教师看不到任何班级学情，这是预期的安全行为。'
                );
                return;
            }

            setStatus('tcStatus', '共 ' + linksResult.data.length + ' 条授课关系');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>ID</th><th>教师</th><th>课程</th><th>班级</th>',
                '<th>学期</th><th>建立时间</th><th>操作</th></tr></thead><tbody>'];

            linksResult.data.forEach(function (item) {
                html.push('<tr><td>' + esc(String(item.id)) + '</td>'
                    + '<td>' + esc((item.teacher_name || '')
                        + '（' + (item.teacher_no || '') + '）') + '</td>'
                    + '<td>' + esc(item.course_name || ('#' + item.course_id))
                    + '</td>'
                    + '<td>' + esc(item.class_name || ('#' + item.class_id))
                    + '</td>'
                    + '<td>' + esc(item.term || '—') + '</td>'
                    + '<td>' + esc(item.created_at || '—') + '</td>'
                    + '<td class="actions"><button class="btn-mini danger"'
                    + ' data-del-link="' + item.id + '">解除</button></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('tcBody').innerHTML = html.join('');

            Array.prototype.forEach.call(
                $('tcBody').querySelectorAll('button[data-del-link]'),
                function (button) {
                    button.addEventListener('click', function () {
                        var linkId = button.getAttribute('data-del-link');

                        if (!window.confirm('确认解除该授课关系？'
                            + '解除后该教师将立即失去对应班级的数据权限。')) {
                            return;
                        }

                        api('/api/admin/teacher-courses/' + linkId,
                            { method: 'DELETE' }).then(function (result) {
                                if (result.error) {
                                    setStatus('tcStatus', result.error, 'error');
                                    return;
                                }

                                setStatus('tcStatus', result.message, 'success');
                                loadTeacherCourses();
                            });
                    });
                }
            );
        });
    }

    function createClass() {
        var payload = {
            name: $('newClassName').value.trim(),
            college: $('newClassCollege').value.trim(),
            grade_year: $('newClassYear').value || null,
            remark: $('newClassRemark').value.trim()
        };

        if (!payload.name) {
            setStatus('createClassResult', '班级名称不能为空', 'error');
            return;
        }

        setStatus('createClassResult', '正在创建…');

        api('/api/admin/classes', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('createClassResult', result.error, 'error');
                    return;
                }

                setStatus('createClassResult',
                    result.message + '（班级 ID ' + result.class_id + '）',
                    'success');

                $('newClassName').value = '';
                $('newClassRemark').value = '';
                loadClasses();
            });
    }

    function createTeacherCourse() {
        var payload = {
            teacher_id: $('tcTeacher').value,
            course_id: $('tcCourse').value,
            class_id: $('tcClass').value,
            term: $('tcTerm').value.trim()
        };

        if (!payload.teacher_id || !payload.course_id || !payload.class_id) {
            setStatus('createTcResult', '教师、课程、班级都必须选择', 'error');
            return;
        }

        setStatus('createTcResult', '正在建立…');

        api('/api/admin/teacher-courses', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('createTcResult', result.error, 'error');
                    return;
                }

                setStatus('createTcResult',
                    result.message + '（关系 ID ' + result.link_id + '）',
                    'success');

                loadTeacherCourses();
            });
    }

    /* ============================================================
       课程 / 章节 / 知识点
       ============================================================ */

    function loadCourseTree() {
        setStatus('treeStatus', '正在读取课程结构…');

        api('/api/admin/course-tree').then(function (result) {
            if (result.error) {
                setStatus('treeStatus', result.error, 'error', loadCourseTree);
                return;
            }

            var courses = result.courses || [];
            var chapters = result.chapters || [];
            var points = result.knowledge_points || [];

            state.courses = courses;
            state.chapters = chapters;

            fillSelect($('chapCourse'), '请选择课程', courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            fillSelect($('kpCourse'), '不指定', courses.map(function (item) {
                return { value: item.id, label: item.name };
            }));

            if (!courses.length) {
                setStatus('treeStatus', '本校还没有课程记录。');
                $('treeBody').innerHTML = emptyState('请先创建课程。');
                return;
            }

            setStatus('treeStatus', courses.length + ' 门课程 / '
                + chapters.length + ' 个章节 / ' + points.length + ' 个知识点');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>课程</th><th>代码</th><th>学科</th><th>学院</th>',
                '<th>学分</th><th>章节</th><th>知识点</th><th>资源</th>',
                '<th>状态</th><th>操作</th></tr></thead><tbody>'];

            courses.forEach(function (course) {
                html.push('<tr>'
                    + '<td>' + esc(course.name) + '</td>'
                    + '<td>' + esc(course.code || '—') + '</td>'
                    + '<td>' + esc(course.major || '—') + '</td>'
                    + '<td>' + esc(course.college || '—') + '</td>'
                    + '<td class="num">' + esc(fmt(course.credit)) + '</td>'
                    + '<td class="num">' + esc(String(course.chapter_count)) + '</td>'
                    + '<td class="num">' + esc(String(course.kp_count)) + '</td>'
                    + '<td class="num">' + esc(String(course.resource_count)) + '</td>'
                    + '<td>' + (course.status ? '在用' : '停用') + '</td>'
                    + '<td class="actions">'
                    + '<button class="btn-mini" data-course-chapters="'
                    + course.id + '">章节与知识点</button>'
                    + '<button class="btn-mini danger" data-del-course="'
                    + course.id + '">删除课程</button>'
                    + '</td></tr>');

                html.push('<tr id="course-detail-' + course.id
                    + '" hidden><td colspan="10"><div class="status-line">'
                    + '加载中…</div></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('treeBody').innerHTML = html.join('');

            Array.prototype.forEach.call(
                $('treeBody').querySelectorAll('button[data-course-chapters]'),
                function (button) {
                    button.addEventListener('click', function () {
                        var courseId = button.getAttribute('data-course-chapters');
                        var row = $('course-detail-' + courseId);

                        if (!row.hidden) {
                            row.hidden = true;
                            button.textContent = '章节与知识点';
                            return;
                        }

                        row.hidden = false;
                        button.textContent = '收起';

                        renderCourseDetail(courseId, row.querySelector('td'));
                    });
                }
            );

            Array.prototype.forEach.call(
                $('treeBody').querySelectorAll('button[data-del-course]'),
                function (button) {
                    button.addEventListener('click', function () {
                        var courseId = button.getAttribute('data-del-course');

                        if (!window.confirm('确认删除该课程？'
                            + '若课程下仍有章节 / 知识点 / 资源 / 授课关系，'
                            + '服务端会拒绝删除。')) {
                            return;
                        }

                        api('/api/courses/' + courseId, { method: 'DELETE' })
                            .then(function (result) {
                                if (result.error) {
                                    setStatus('treeStatus', result.error, 'error');
                                    return;
                                }

                                setStatus('treeStatus', result.message, 'success');
                                loadCourseTree();
                            });
                    });
                }
            );
        });
    }

    function renderCourseDetail(courseId, cell) {
        var chapters = state.chapters.filter(function (item) {
            return String(item.course_id) === String(courseId);
        });

        api('/api/knowledge-points?course_id=' + courseId)
            .then(function (result) {
                if (result.error) {
                    cell.innerHTML = '<div class="status-line error">'
                        + esc(result.error) + '</div>';
                    return;
                }

                var points = result.data || [];

                if (!chapters.length && !points.length) {
                    cell.innerHTML = emptyState('该课程还没有章节与知识点。');
                    return;
                }

                var html = [];

                if (chapters.length) {
                    html.push('<table class="data-table"><thead><tr>'
                        + '<th>章节 ID</th><th>名称</th><th>排序</th>'
                        + '<th>知识点数</th><th>操作</th></tr></thead><tbody>');

                    chapters.forEach(function (chapter) {
                        html.push('<tr><td>' + esc(String(chapter.id)) + '</td>'
                            + '<td>' + esc(chapter.name) + '</td>'
                            + '<td class="num">' + esc(String(chapter.sort_order))
                            + '</td>'
                            + '<td class="num">' + esc(String(chapter.kp_count))
                            + '</td>'
                            + '<td class="actions"><button class="btn-mini danger"'
                            + ' data-del-chapter="' + chapter.id + '">删除章节'
                            + '</button></td></tr>');
                    });

                    html.push('</tbody></table>');
                }

                if (points.length) {
                    html.push('<table class="data-table" style="margin-top:10px">'
                        + '<thead><tr><th>知识点 ID</th><th>名称</th>'
                        + '<th>章节</th><th>难度</th><th>考频权重</th>'
                        + '<th>操作</th></tr></thead><tbody>');

                    points.forEach(function (item) {
                        html.push('<tr><td>' + esc(String(item.id)) + '</td>'
                            + '<td>' + esc(item.name) + '</td>'
                            + '<td>' + esc(item.chapter_name || '—') + '</td>'
                            + '<td>' + esc(item.difficulty_label || '') + '</td>'
                            + '<td class="num">' + esc(fmt(item.exam_weight))
                            + '</td>'
                            + '<td class="actions"><button class="btn-mini danger"'
                            + ' data-del-kp="' + item.id + '">删除知识点</button>'
                            + '</td></tr>');
                    });

                    html.push('</tbody></table>');
                }

                cell.innerHTML = html.join('');

                Array.prototype.forEach.call(
                    cell.querySelectorAll('button[data-del-chapter]'),
                    function (button) {
                        button.addEventListener('click', function () {
                            var id = button.getAttribute('data-del-chapter');

                            api('/api/chapters/' + id, { method: 'DELETE' })
                                .then(function (result) {
                                    if (result.error) {
                                        setStatus('treeStatus', result.error,
                                            'error');
                                        return;
                                    }

                                    setStatus('treeStatus', result.message,
                                        'success');
                                    loadCourseTree();
                                });
                        });
                    }
                );

                Array.prototype.forEach.call(
                    cell.querySelectorAll('button[data-del-kp]'),
                    function (button) {
                        button.addEventListener('click', function () {
                            var id = button.getAttribute('data-del-kp');

                            api('/api/knowledge-points/' + id,
                                { method: 'DELETE' }).then(function (result) {
                                    if (result.error) {
                                        setStatus('treeStatus', result.error,
                                            'error');
                                        return;
                                    }

                                    setStatus('treeStatus', result.message,
                                        'success');
                                    loadCourseTree();
                                });
                        });
                    }
                );
            });
    }

    function createChapter() {
        var payload = {
            course_id: $('chapCourse').value,
            name: $('chapName').value.trim(),
            sort_order: $('chapSort').value || 0
        };

        if (!payload.course_id || !payload.name) {
            setStatus('chapterResult', '课程与章节名称必填', 'error');
            return;
        }

        setStatus('chapterResult', '正在创建…');

        api('/api/chapters', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('chapterResult', result.error, 'error');
                    return;
                }

                setStatus('chapterResult',
                    result.message + '（章节 ID ' + result.chapter_id + '）',
                    'success');

                $('chapName').value = '';
                loadCourseTree();
            });
    }

    function createKp() {
        var payload = {
            course_id: $('kpCourse').value || null,
            chapter_id: $('kpChapter').value || null,
            name: $('kpName').value.trim(),
            difficulty: $('kpDifficulty').value,
            exam_weight: $('kpWeight').value || null
        };

        if (!payload.name) {
            setStatus('kpResult', '知识点名称不能为空', 'error');
            return;
        }

        setStatus('kpResult', '正在创建…');

        api('/api/knowledge-points', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('kpResult', result.error, 'error');
                    return;
                }

                setStatus('kpResult',
                    result.message + '（知识点 ID ' + result.kp_id + '）',
                    'success');

                $('kpName').value = '';
                loadCourseTree();
            });
    }

    /* ============================================================
       题库管理
       ============================================================ */

    function loadQuestions() {
        var params = ['page=' + state.questionsPage,
            'page_size=' + state.questionsPageSize];

        if ($('qKeyword').value.trim()) {
            params.push('keyword=' + encodeURIComponent($('qKeyword').value.trim()));
        }

        if ($('qType').value) {
            params.push('qtype=' + encodeURIComponent($('qType').value));
        }

        if ($('qVerified').value !== '') {
            params.push('verified=' + encodeURIComponent($('qVerified').value));
        }

        setStatus('questionsStatus', '正在读取题库…');

        api('/api/admin/questions?' + params.join('&')).then(function (result) {
            if (result.error) {
                setStatus('questionsStatus', result.error, 'error', loadQuestions);
                return;
            }

            if (!result.data.length) {
                setStatus('questionsStatus', '没有符合条件的题目。');
                $('questionsBody').innerHTML = emptyState(
                    '题库中还没有题目。教师审核通过的题目会自动出现在这里。'
                );
                $('questionsPager').innerHTML = '';
                return;
            }

            setStatus('questionsStatus', '共 ' + result.total + ' 道题目');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>ID</th><th>题干</th><th>题型</th><th>学科</th>',
                '<th>知识点</th><th>难度</th><th>来源</th><th>审核</th>',
                '<th>创建人</th><th>操作</th></tr></thead><tbody>'];

            result.data.forEach(function (item) {
                html.push('<tr>'
                    + '<td>' + esc(String(item.id)) + '</td>'
                    + '<td class="cell-question">' + markup(item.question)
                    + '</td>'
                    + '<td>' + esc(item.qtype) + '</td>'
                    + '<td>' + esc(item.major || '—') + '</td>'
                    + '<td>' + esc(item.kp_name || '—') + '</td>'
                    + '<td class="num">' + esc(String(item.difficulty)) + '</td>'
                    + '<td>' + esc(item.source) + '</td>'
                    + '<td><span class="badge ' + (item.verified ? 'ok' : 'warn')
                    + '">' + (item.verified ? '已审核' : '未审核') + '</span></td>'
                    + '<td>' + esc(item.creator_name || item.creator_no || '—')
                    + '</td>'
                    + '<td class="actions">');

                if (!item.verified) {
                    html.push('<button class="btn-mini" data-verify="'
                        + item.id + '">标记已审核</button>');
                }

                html.push('<button class="btn-mini danger" data-del-question="'
                    + item.id + '">下架</button></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('questionsBody').innerHTML = html.join('');

            Array.prototype.forEach.call(
                $('questionsBody').querySelectorAll('button[data-verify]'),
                function (button) {
                    button.addEventListener('click', function () {
                        var id = button.getAttribute('data-verify');

                        api('/api/admin/questions/' + id, {
                            method: 'PATCH',
                            body: { verified: 1 }
                        }).then(function (result) {
                            if (result.error) {
                                setStatus('questionsStatus', result.error, 'error');
                                return;
                            }

                            setStatus('questionsStatus',
                                '已标记为审核通过（审核人：当前管理员）', 'success');
                            loadQuestions();
                        });
                    });
                }
            );

            Array.prototype.forEach.call(
                $('questionsBody').querySelectorAll('button[data-del-question]'),
                function (button) {
                    button.addEventListener('click', function () {
                        var id = button.getAttribute('data-del-question');

                        api('/api/admin/questions/' + id, { method: 'DELETE' })
                            .then(function (result) {
                                if (result.error) {
                                    setStatus('questionsStatus', result.error,
                                        'error');
                                    return;
                                }

                                setStatus('questionsStatus', result.message,
                                    'success');
                                loadQuestions();
                            });
                    });
                }
            );

            var pages = Math.max(1, Math.ceil(result.total / result.page_size));

            $('questionsPager').innerHTML =
                '<button class="btn-secondary" id="qPrev"'
                + (result.page <= 1 ? ' disabled' : '') + '>上一页</button>'
                + '<span>第 ' + result.page + ' / ' + pages + ' 页</span>'
                + '<button class="btn-secondary" id="qNext"'
                + (result.page >= pages ? ' disabled' : '') + '>下一页</button>';

            if ($('qPrev')) {
                $('qPrev').addEventListener('click', function () {
                    state.questionsPage = Math.max(1, state.questionsPage - 1);
                    loadQuestions();
                });
            }

            if ($('qNext')) {
                $('qNext').addEventListener('click', function () {
                    state.questionsPage = state.questionsPage + 1;
                    loadQuestions();
                });
            }
        });
    }

    function createQuestion() {
        var payload = {
            course_id: $('qCourse').value || null,
            major: $('qMajor').value.trim(),
            kp_name: $('qKp').value.trim(),
            qtype: $('qNewType').value,
            difficulty: $('qDifficulty').value,
            question: $('qQuestion').value.trim(),
            answer: $('qAnswer').value.trim(),
            analysis: $('qAnalysis').value.trim(),
            verified: $('qNewVerified').checked ? 1 : 0
        };

        var optionsRaw = $('qOptions').value.trim();

        if (optionsRaw) {
            try {
                payload.options_json = JSON.parse(optionsRaw);
            } catch (error) {
                setStatus('createQuestionResult',
                    '选项不是合法 JSON：' + error.message, 'error');
                return;
            }
        }

        if (!payload.question) {
            setStatus('createQuestionResult', '题干不能为空', 'error');
            return;
        }

        setStatus('createQuestionResult', '正在创建…');

        api('/api/admin/questions', { method: 'POST', body: payload })
            .then(function (result) {
                if (result.error) {
                    setStatus('createQuestionResult', result.error, 'error');
                    return;
                }

                setStatus('createQuestionResult',
                    result.message + '（题目 ID ' + result.question_id
                    + '，verified=' + result.verified + '）', 'success');

                $('qQuestion').value = '';
                $('qAnswer').value = '';
                $('qAnalysis').value = '';
                $('qOptions').value = '';

                loadQuestions();
            });
    }

    /* ============================================================
       操作日志
       ============================================================ */

    function loadLogs() {
        var params = ['page=' + state.logsPage,
            'page_size=' + state.logsPageSize];

        if ($('logUserId').value) {
            params.push('user_id=' + encodeURIComponent($('logUserId').value));
        }

        if ($('logAction').value.trim()) {
            params.push('action=' + encodeURIComponent($('logAction').value.trim()));
        }

        if ($('logStart').value) {
            params.push('start_date=' + encodeURIComponent($('logStart').value));
        }

        if ($('logEnd').value) {
            params.push('end_date=' + encodeURIComponent($('logEnd').value));
        }

        setStatus('logsStatus', '正在读取日志…');

        api('/api/admin/logs?' + params.join('&')).then(function (result) {
            if (result.error) {
                setStatus('logsStatus', result.error, 'error', loadLogs);
                return;
            }

            if (!result.data.length) {
                setStatus('logsStatus', '没有符合条件的日志。');
                $('logsBody').innerHTML = emptyState('当前筛选条件下没有操作日志。');
                $('logsPager').innerHTML = '';
                return;
            }

            setStatus('logsStatus', '共 ' + result.total + ' 条日志');

            var html = ['<div class="table-scroll"><table class="data-table">',
                '<thead><tr><th>ID</th><th>时间</th><th>操作者</th><th>角色</th>',
                '<th>动作</th><th>对象</th><th>说明</th><th>IP</th>',
                '<th>结果</th></tr></thead><tbody>'];

            result.data.forEach(function (item) {
                var operator = item.real_name
                    ? item.real_name + '（' + (item.user_no || '') + '）'
                    : (item.user_no || ('用户 #' + item.user_id));

                html.push('<tr>'
                    + '<td>' + esc(String(item.id)) + '</td>'
                    + '<td>' + esc(item.created_at || '—') + '</td>'
                    + '<td>' + esc(operator) + '</td>'
                    + '<td>' + esc(item.role || '—') + '</td>'
                    + '<td>' + esc(item.action) + '</td>'
                    + '<td>' + esc((item.target_type || '—')
                        + (item.target_id ? '#' + item.target_id : '')) + '</td>'
                    + '<td class="mono-cell">' + esc(item.detail || '—') + '</td>'
                    + '<td>' + esc(item.ip || '—') + '</td>'
                    + '<td><span class="badge '
                    + (item.status === 'ok' ? 'ok' : 'danger') + '">'
                    + esc(item.status) + '</span></td></tr>');
            });

            html.push('</tbody></table></div>');

            $('logsBody').innerHTML = html.join('');

            var pages = Math.max(1, Math.ceil(result.total / result.page_size));

            $('logsPager').innerHTML = '<button class="btn-secondary" id="lPrev"'
                + (result.page <= 1 ? ' disabled' : '') + '>上一页</button>'
                + '<span>第 ' + result.page + ' / ' + pages + ' 页</span>'
                + '<button class="btn-secondary" id="lNext"'
                + (result.page >= pages ? ' disabled' : '') + '>下一页</button>';

            if ($('lPrev')) {
                $('lPrev').addEventListener('click', function () {
                    state.logsPage = Math.max(1, state.logsPage - 1);
                    loadLogs();
                });
            }

            if ($('lNext')) {
                $('lNext').addEventListener('click', function () {
                    state.logsPage = state.logsPage + 1;
                    loadLogs();
                });
            }
        });
    }

    /* ============================================================
       系统参数与备份
       ============================================================ */

    function loadSettings() {
        setStatus('settingsStatus', '正在读取系统参数…');

        api('/api/admin/settings').then(function (result) {
            if (result.error) {
                setStatus('settingsStatus', result.error, 'error', loadSettings);
                return;
            }

            setStatus('settingsStatus', result.notice || '');

            var html = [];

            if (result.blocked_keys && result.blocked_keys.length) {
                html.push('<div class="warn-box">'
                    + esc(result.blocked_hint) + '<br>被拒绝的键：'
                    + esc(result.blocked_keys.join('、')) + '</div>');
            }

            if (!result.data.length) {
                html.push(emptyState(
                    'system_settings 表中还没有非敏感参数。'
                    + '模型密钥与数据库密码永远不会出现在这里。'
                ));
            } else {
                html.push('<div class="table-scroll"><table class="data-table">'
                    + '<thead><tr><th>参数名</th><th>参数值</th><th>说明</th>'
                    + '<th>更新时间</th></tr></thead><tbody>'
                    + result.data.map(function (item) {
                        return '<tr><td>' + esc(item.setting_key) + '</td>'
                            + '<td class="mono-cell">'
                            + esc(item.setting_value || '') + '</td>'
                            + '<td>' + esc(item.description || '—') + '</td>'
                            + '<td>' + esc(item.updated_at || '—') + '</td></tr>';
                    }).join('')
                    + '</tbody></table></div>');
            }

            $('settingsBody').innerHTML = html.join('');
        });
    }

    function saveSetting() {
        var key = $('settingKey').value.trim();
        var value = $('settingValue').value;

        if (!key) {
            setStatus('settingResult', '参数名不能为空', 'error');
            return;
        }

        setStatus('settingResult', '正在保存…');

        api('/api/admin/settings', {
            method: 'PATCH',
            body: {
                settings: [{
                    setting_key: key,
                    setting_value: value,
                    description: $('settingDesc').value.trim()
                }]
            }
        }).then(function (result) {
            if (result.error) {
                setStatus('settingResult', result.error, 'error');
                return;
            }

            setStatus('settingResult', result.message
                + '（写入：' + (result.updated_keys || []).join('、') + '）',
                'success');

            $('settingKey').value = '';
            $('settingValue').value = '';
            $('settingDesc').value = '';

            loadSettings();
        });
    }

    function loadBackups() {
        setStatus('backupsStatus', '正在读取备份记录…');

        api('/api/admin/backups').then(function (result) {
            if (result.error) {
                setStatus('backupsStatus', result.error, 'error', loadBackups);
                return;
            }

            var tool = result.tool || {};

            setStatus('backupsStatus',
                '备份目录：' + result.backup_dir + '；mysqldump：'
                + (tool.available ? '可用（' + (tool.version || '') + '）'
                    : '不可用 —— ' + (tool.message || '')));

            var html = [];

            if (!result.records.length) {
                html.push(emptyState(
                    '还没有通过本系统执行过备份。磁盘上已有的文件会列在下方。'
                ));
            } else {
                html.push('<div class="table-scroll"><table class="data-table">'
                    + '<thead><tr><th>ID</th><th>文件名</th><th>大小(字节)</th>'
                    + '<th>方式</th><th>操作人</th><th>时间</th></tr></thead>'
                    + '<tbody>'
                    + result.records.map(function (item) {
                        return '<tr><td>' + esc(String(item.id)) + '</td>'
                            + '<td class="mono-cell">' + esc(item.file_name)
                            + '</td>'
                            + '<td class="num">' + esc(String(item.file_size))
                            + '</td>'
                            + '<td>' + esc(item.method) + '</td>'
                            + '<td>' + esc(item.operator_name || item.operator_no
                                || '—') + '</td>'
                            + '<td>' + esc(item.created_at || '—') + '</td></tr>';
                    }).join('')
                    + '</tbody></table></div>');
            }

            html.push('<h4 style="margin:14px 0 8px;font-size:14px;color:#3d2455">'
                + '磁盘上的备份文件（真实文件列表）</h4>');

            if (!result.files.length) {
                html.push(emptyState('备份目录里还没有文件。'));
            } else {
                html.push('<div class="table-scroll"><table class="data-table">'
                    + '<thead><tr><th>文件名</th><th>大小(字节)</th>'
                    + '<th>修改时间</th><th>有记录</th></tr></thead><tbody>'
                    + result.files.map(function (item) {
                        return '<tr><td class="mono-cell">' + esc(item.file_name)
                            + '</td>'
                            + '<td class="num">' + esc(String(item.file_size))
                            + '</td>'
                            + '<td>' + esc(item.modified_at) + '</td>'
                            + '<td>' + (item.in_records ? '是' : '否（外部产生）')
                            + '</td></tr>';
                    }).join('')
                    + '</tbody></table></div>');
            }

            $('backupsBody').innerHTML = html.join('');
        });
    }

    function runBackup() {
        setStatus('backupResult', '正在执行 mysqldump，请稍候…');

        api('/api/admin/backup', { method: 'POST' }).then(function (result) {
            if (result.error) {
                setStatus('backupResult', result.error, 'error');
                return;
            }

            setStatus('backupResult',
                result.message + '（' + result.file_size + ' 字节，记录 ID '
                + result.backup_id + '）', 'success');

            loadBackups();
        });
    }

    function loadSso() {
        setStatus('ssoStatus', '正在读取 SSO 配置…');

        api('/api/admin/sso-config').then(function (result) {
            if (result.error) {
                setStatus('ssoStatus', result.error, 'error', loadSso);
                return;
            }

            var data = result.data || {};

            setStatus('ssoStatus', data.message || '');

            var rows = [
                ['是否已实现', data.implemented ? '是' : '否（当前项目未实现）'],
                ['是否已启用（环境变量）', data.enabled ? '是' : '否'],
                ['是否配置完整', data.configured ? '是' : '否'],
                ['身份提供方', data.provider || '—'],
                ['登录地址', data.login_url || '—'],
                ['回调地址', data.callback_url || '—'],
                ['Client ID 是否已配置', data.client_id_configured ? '是' : '否'],
                ['Metadata 是否已配置', data.metadata_url_configured ? '是' : '否'],
                ['相关环境变量', (data.env_keys || []).join('、')]
            ];

            $('ssoBody').innerHTML = '<div class="table-scroll">'
                + '<table class="data-table"><thead><tr><th>项目</th>'
                + '<th>状态</th></tr></thead><tbody>'
                + rows.map(function (row) {
                    return '<tr><td>' + esc(row[0]) + '</td><td>'
                        + esc(row[1]) + '</td></tr>';
                }).join('')
                + '</tbody></table></div>'
                + '<div class="warn-box" style="margin-top:12px">'
                + '本接口只读取环境变量判断配置状态，不提供任何可用的单点登录流程。'
                + '请勿在未完成对接前把 SSO 登录入口暴露给用户。</div>';
        });
    }

    /* ============================================================
       事件绑定
       ============================================================ */

    function bind() {
        $('reloadStatsBtn').addEventListener('click', loadStats);

        $('searchUsersBtn').addEventListener('click', function () {
            state.usersPage = 1;
            loadUsers();
        });

        $('createUserBtn').addEventListener('click', createUser);

        $('createClassBtn').addEventListener('click', createClass);
        $('createTcBtn').addEventListener('click', createTeacherCourse);

        $('reloadTreeBtn').addEventListener('click', loadCourseTree);
        $('createChapterBtn').addEventListener('click', createChapter);
        $('createKpBtn').addEventListener('click', createKp);

        if ($('kpCourse')) {
            $('kpCourse').addEventListener('change', function () {
                var courseId = $('kpCourse').value;

                var items = state.chapters.filter(function (item) {
                    return !courseId || String(item.course_id) === String(courseId);
                }).map(function (item) {
                    return { value: item.id, label: item.name };
                });

                fillSelect($('kpChapter'), '不指定', items);
            });
        }

        $('searchQuestionsBtn').addEventListener('click', function () {
            state.questionsPage = 1;
            loadQuestions();
        });

        $('createQuestionBtn').addEventListener('click', createQuestion);

        $('searchLogsBtn').addEventListener('click', function () {
            state.logsPage = 1;
            loadLogs();
        });

        $('saveSettingBtn').addEventListener('click', saveSetting);
        $('backupBtn').addEventListener('click', runBackup);
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

    document.addEventListener('DOMContentLoaded', function () {
        initTabs();
        bind();

        if (!IS_ADMIN) {
            /* 非管理员理论上访问不到本页面（页面路由已限制），
               这里再兜底一次：直接提示并停止发起管理端请求。 */
            $('statsStatus').textContent =
                '当前角色不是管理员，管理端接口会被服务端拒绝（403）。';
            return;
        }

        loadStats();
    });
})();
