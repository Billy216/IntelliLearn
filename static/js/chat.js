/**
 * IntelliLearn AI 答疑页逻辑
 *
 * 设计原则：
 *   - 所有会话数据都来自后端接口，前端不预置任何"演示对话"；
 *   - 接口失败时显示真实错误并提供重试，绝不用假数据填充；
 *   - 系统提示（欢迎语、状态）与 AI 生成内容使用不同样式区分。
 */
(function () {
    'use strict';

    var R = window.ILRender;

    // ======================== 状态 ========================

    var urlParams = new URLSearchParams(window.location.search);
    var initialImageUrl = urlParams.get('img') || '';
    var initialConvId = urlParams.get('conv');

    var currentConversationId = initialConvId ? parseInt(initialConvId, 10) : null;
    var conversations = [];
    var streamToken = 0;          // 作废仍在进行的流式请求
    var isSending = false;
    var lastRequest = null;       // 用于失败重试

    var pendingImageFile = null;  // 本地 File 对象
    var pendingImageUrl = '';     // 本地预览 dataURL

    // ======================== DOM ========================

    var container = document.getElementById('messagesContainer');
    var input = document.getElementById('messageInput');
    var sendBtn = document.getElementById('sendBtn');
    var conversationListEl = document.getElementById('conversationList');
    var searchInput = document.getElementById('convSearchInput');

    var attachBtn = document.getElementById('attachBtn');
    var imageInput = document.getElementById('imageInput');
    var imagePreviewBar = document.getElementById('imagePreviewBar');
    var previewImage = document.getElementById('previewImage');
    var removeImageBtn = document.getElementById('removeImageBtn');

    // ======================== 工具 ========================

    function escapeHtml(text) {
        return R ? R.escapeHtml(text) : String(text || '');
    }

    function renderInto(element, text, options) {
        if (R) {
            R.renderInto(element, text, options);
            return;
        }

        // render.js 未加载时的最小兜底：只做转义与换行
        element.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    }

    function showToast(message) {
        // 用页面内提示条替代 alert，避免阻塞输入
        var bar = document.getElementById('mathLibWarning');
        if (!bar) {
            return;
        }

        bar.textContent = message;
        bar.classList.add('show');

        clearTimeout(bar._timer);
        bar._timer = setTimeout(function () {
            bar.classList.remove('show');
        }, 4000);
    }

    function scrollToBottom() {
        container.scrollTop = container.scrollHeight;
    }

    // ======================== 消息渲染 ========================

    /**
     * 追加一条消息。
     * role: 'user' | 'assistant' | 'system'
     */
    function addMessage(role, content, imageUrl, options) {
        options = options || {};

        var wrapper = document.createElement('div');
        wrapper.className = 'message ' + (role === 'system' ? 'system-hint' : role);

        if (role === 'user') {
            if (imageUrl) {
                var img = document.createElement('img');
                img.src = imageUrl;
                img.className = 'image-preview';
                img.alt = '上传的题目图片';
                img.loading = 'lazy';
                wrapper.appendChild(img);
            }

            if (content) {
                var textNode = document.createElement('div');
                textNode.className = 'user-text';
                textNode.textContent = content;
                wrapper.appendChild(textNode);
            }
        } else {
            var body = document.createElement('div');
            body.className = 'il-content';

            renderInto(body, content || '', {
                plain: options.plain || ''
            });

            wrapper.appendChild(body);
        }

        if (options.analysis) {
            wrapper.appendChild(buildAnalysisPanel(options.analysis));
        }

        if (options.actions) {
            wrapper.appendChild(options.actions);
        }

        container.appendChild(wrapper);
        scrollToBottom();

        return wrapper;
    }

    /** 系统提示气泡（与 AI 真实回答区分开） */
    function addSystemHint(text) {
        var div = document.createElement('div');
        div.className = 'system-hint';
        div.textContent = text;
        container.appendChild(div);
        scrollToBottom();
        return div;
    }

    /**
     * 识别结果 / 作答分析折叠面板。
     * 只展示后端真实返回的字段，缺失的字段不渲染。
     */
    function buildAnalysisPanel(analysis) {
        var panel = document.createElement('div');
        panel.className = 'analysis-panel';

        var head = document.createElement('div');
        head.className = 'analysis-head';
        head.innerHTML = '<span>🔍 识别结果与作答分析</span>'
            + '<span class="arrow">▶</span>';

        head.addEventListener('click', function () {
            panel.classList.toggle('open');
        });

        panel.appendChild(head);

        var body = document.createElement('div');
        body.className = 'analysis-body';

        var tags = document.createElement('div');
        tags.className = 'tag-row';

        if (analysis.major) {
            tags.appendChild(makeTag(
                '学科：' + displayMajor(analysis.major),
                'tag-major'
            ));
        }

        (analysis.sub || []).forEach(function (sub) {
            tags.appendChild(makeTag('章节：' + sub, 'tag-sub'));
        });

        (analysis.knowledge_points || []).forEach(function (kp) {
            tags.appendChild(makeTag('知识点：' + kp, 'tag-kp'));
        });

        (analysis.error_types || []).forEach(function (type) {
            tags.appendChild(makeTag('错误类型：' + type, 'tag-error'));
        });

        if (analysis.has_student_work) {
            tags.appendChild(makeTag('已识别到你的作答', 'tag-warn'));
        }

        if (analysis.confidence === 'low') {
            tags.appendChild(makeTag('识别把握较低', 'tag-warn'));
        }

        if (tags.children.length) {
            body.appendChild(tags);
        }

        if (analysis.question_text) {
            body.appendChild(makeAnalysisRow('识别题目', analysis.question_text));
        }

        if (analysis.unclear_reason) {
            body.appendChild(makeAnalysisRow('未识别清楚', analysis.unclear_reason));
        }

        if (analysis.student_work) {
            body.appendChild(makeAnalysisRow('你的作答', analysis.student_work));
        }

        if (analysis.error_analysis) {
            body.appendChild(makeAnalysisRow('错因分析', analysis.error_analysis));
        }

        if (!body.children.length) {
            body.appendChild(makeAnalysisRow(
                '说明',
                '本次未获得结构化识别结果。'
            ));
        }

        panel.appendChild(body);

        return panel;
    }

    function makeTag(text, className) {
        var span = document.createElement('span');
        span.className = 'tag ' + className;
        span.textContent = text;
        return span;
    }

    function makeAnalysisRow(label, value) {
        var row = document.createElement('div');
        row.className = 'analysis-row';

        var labelEl = document.createElement('span');
        labelEl.className = 'analysis-label';
        labelEl.textContent = label;

        var textEl = document.createElement('div');
        textEl.className = 'analysis-text';
        textEl.textContent = value;

        row.appendChild(labelEl);
        row.appendChild(textEl);

        return row;
    }

    function displayMajor(major) {
        return major === 'py' ? 'Python' : major;
    }

    /** 加入错题集按钮（真实调用后端） */
    function buildWrongButton(payload) {
        var bar = document.createElement('div');
        bar.className = 'tag-row';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'wrong-btn';
        btn.textContent = '📒 加入错题本';

        btn.addEventListener('click', function () {
            btn.disabled = true;
            btn.textContent = '正在加入…';

            fetch('/api/wrong_questions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify(payload)
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.success) {
                        btn.textContent = '✅ ' + (data.message || '已加入错题本');
                        btn.classList.add('done');
                    } else {
                        btn.disabled = false;
                        btn.textContent = '📒 加入错题本';
                        showToast(data.message || '加入失败，请重试');
                    }
                })
                .catch(function () {
                    btn.disabled = false;
                    btn.textContent = '📒 加入错题本';
                    showToast('网络错误，加入错题本失败');
                });
        });

        bar.appendChild(btn);

        return bar;
    }

    // ======================== 会话列表 ========================

    function loadConversationList() {
        fetch('/api/conversations', {
            method: 'GET',
            credentials: 'same-origin'
        })
            .then(function (res) {
                if (!res.ok) {
                    throw new Error('HTTP ' + res.status);
                }
                return res.json();
            })
            .then(function (data) {
                if (!data.success) {
                    throw new Error(data.message || '读取失败');
                }

                conversations = data.data || [];
                renderConversationList(conversations);
            })
            .catch(function (error) {
                // 接口失败时给出真实错误与重试入口，不用假数据填充
                conversationListEl.innerHTML = '';

                var box = document.createElement('div');
                box.className = 'sidebar-error';
                box.textContent = '历史对话加载失败：' + error.message;

                var retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'sidebar-retry';
                retry.textContent = '重试';
                retry.addEventListener('click', loadConversationList);

                box.appendChild(retry);
                conversationListEl.appendChild(box);
            });
    }

    function renderConversationList(list) {
        var keyword = (searchInput && searchInput.value || '').trim().toLowerCase();

        var filtered = list.filter(function (conv) {
            if (!keyword) {
                return true;
            }

            return (conv.title || '').toLowerCase().indexOf(keyword) !== -1
                || (conv.preview || '').toLowerCase().indexOf(keyword) !== -1;
        });

        conversationListEl.innerHTML = '';

        if (!list.length) {
            var empty = document.createElement('div');
            empty.className = 'sidebar-empty';
            empty.textContent = '还没有历史对话，提问后会自动保存到这里';
            conversationListEl.appendChild(empty);
            return;
        }

        if (!filtered.length) {
            var noMatch = document.createElement('div');
            noMatch.className = 'sidebar-empty';
            noMatch.textContent = '没有匹配「' + keyword + '」的对话';
            conversationListEl.appendChild(noMatch);
            return;
        }

        filtered.forEach(function (conv) {
            var item = document.createElement('div');
            item.className = 'chat-sidebar-item conversation';
            item.dataset.id = conv.id;

            if (currentConversationId === conv.id) {
                item.classList.add('active');
            }

            var titleRow = document.createElement('div');
            titleRow.className = 'conv-title-row';

            var title = document.createElement('span');
            title.className = 'conv-title';
            title.textContent = conv.title || '新对话';
            titleRow.appendChild(title);

            if (conv.major) {
                var tag = document.createElement('span');
                tag.className = 'conv-major';
                tag.textContent = displayMajor(conv.major);
                titleRow.appendChild(tag);
            }

            var tools = document.createElement('span');
            tools.className = 'conv-tools';

            var renameBtn = document.createElement('button');
            renameBtn.type = 'button';
            renameBtn.className = 'conv-tool';
            renameBtn.title = '重命名';
            renameBtn.textContent = '✏️';
            renameBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                renameConversation(conv.id, conv.title);
            });

            var deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'conv-tool danger';
            deleteBtn.title = '删除对话';
            deleteBtn.textContent = '🗑';
            deleteBtn.addEventListener('click', function (event) {
                event.stopPropagation();
                deleteConversation(conv.id, conv.title);
            });

            tools.appendChild(renameBtn);
            tools.appendChild(deleteBtn);
            titleRow.appendChild(tools);

            var preview = document.createElement('span');
            preview.className = 'conv-preview';
            preview.textContent = conv.preview || '（暂无内容）';

            item.appendChild(titleRow);
            item.appendChild(preview);

            item.addEventListener('click', function () {
                loadConversationDetail(conv.id);
            });

            conversationListEl.appendChild(item);
        });
    }

    // ======================== 会话切换 / 新建 / 删除 ========================

    function setActiveConversation(id) {
        currentConversationId = id;

        document.querySelectorAll('.conversation').forEach(function (el) {
            el.classList.toggle('active', Number(el.dataset.id) === id);
        });

        updateConversationUrl(id);
    }

    function updateConversationUrl(id) {
        if (!window.history || !window.history.pushState) {
            return;
        }

        var params = new URLSearchParams();

        if (initialImageUrl) {
            params.set('img', initialImageUrl);
        }

        if (id) {
            params.set('conv', id);
        }

        var query = params.toString();

        window.history.pushState(
            {},
            '',
            window.location.pathname + (query ? '?' + query : '')
        );
    }

    function loadConversationDetail(id) {
        streamToken += 1;
        resetSendButton();

        container.innerHTML = '';
        setActiveConversation(id);

        fetch('/api/conversations/' + id, {
            method: 'GET',
            credentials: 'same-origin'
        })
            .then(function (res) {
                return res.json().then(function (data) {
                    return { ok: res.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok || !result.data.success) {
                    throw new Error(result.data.message || '读取失败');
                }

                var history = (result.data.data && result.data.data.messages) || [];

                if (!history.length) {
                    addSystemHint('该对话暂无消息，开始提问吧');
                    return;
                }

                var lastAnalysis = null;

                history.forEach(function (msg) {
                    if (msg.role === 'user') {
                        lastAnalysis = msg.analysis || null;
                        addMessage('user', msg.content, msg.image_url || '');
                        return;
                    }

                    if (msg.role === 'assistant') {
                        addMessage('assistant', msg.content, '', {
                            plain: msg.reply_plain || '',
                            analysis: lastAnalysis
                        });
                    }
                });

                scrollToBottom();
            })
            .catch(function (error) {
                // 加载失败时明确报错并允许重试，不展示演示数据
                container.innerHTML = '';

                var notice = document.createElement('div');
                notice.className = 'il-notice il-notice-error';
                notice.textContent = '对话加载失败：' + error.message;

                var retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'il-retry';
                retry.textContent = '重试';
                retry.addEventListener('click', function () {
                    loadConversationDetail(id);
                });

                notice.appendChild(retry);
                container.appendChild(notice);
            });
    }

    function startNewChat() {
        streamToken += 1;
        resetSendButton();

        container.innerHTML = '';
        currentConversationId = null;

        document.querySelectorAll('.conversation').forEach(function (el) {
            el.classList.remove('active');
        });

        updateConversationUrl(null);

        addSystemHint('新对话已开启，可以输入题目文字，或点击左下角「+」上传题目/作答照片');
    }

    function deleteConversation(id, title) {
        var confirmed = window.confirm(
            '确定要删除对话「' + (title || '新对话') + '」吗？\n删除后该对话不再出现在历史列表中。'
        );

        if (!confirmed) {
            return;
        }

        fetch('/api/conversations/' + id, {
            method: 'DELETE',
            credentials: 'same-origin'
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data.success) {
                    showToast(data.message || '删除失败');
                    return;
                }

                if (currentConversationId === id) {
                    startNewChat();
                }

                loadConversationList();
                showToast('对话已删除');
            })
            .catch(function () {
                showToast('网络错误，删除失败');
            });
    }

    function renameConversation(id, oldTitle) {
        var title = window.prompt('输入新的对话名称：', oldTitle || '新对话');

        if (title === null) {
            return;
        }

        title = title.trim();

        if (!title) {
            showToast('名称不能为空');
            return;
        }

        fetch('/api/conversations/' + id, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ title: title })
        })
            .then(function (res) { return res.json(); })
            .then(function (data) {
                if (!data.success) {
                    showToast(data.message || '重命名失败');
                    return;
                }

                loadConversationList();
                showToast('已重命名');
            })
            .catch(function () {
                showToast('网络错误，重命名失败');
            });
    }

    // ======================== 图片上传 ========================

    attachBtn.addEventListener('click', function () {
        imageInput.click();
    });

    imageInput.addEventListener('change', function () {
        var file = this.files[0];

        if (!file) {
            return;
        }

        if (!file.type || file.type.indexOf('image/') !== 0) {
            showToast('请选择图片文件（jpg / png / gif / webp）');
            this.value = '';
            return;
        }

        var maxSize = 5 * 1024 * 1024;

        if (file.size > maxSize) {
            showToast('图片大小不能超过 5MB');
            this.value = '';
            return;
        }

        pendingImageFile = file;

        var reader = new FileReader();

        reader.onload = function (event) {
            pendingImageUrl = event.target.result;
            previewImage.src = pendingImageUrl;
            imagePreviewBar.style.display = 'flex';
        };

        reader.readAsDataURL(file);
        this.value = '';
    });

    removeImageBtn.addEventListener('click', function () {
        pendingImageFile = null;
        pendingImageUrl = '';
        previewImage.src = '';
        imagePreviewBar.style.display = 'none';
    });

    function uploadImage(file) {
        return new Promise(function (resolve, reject) {
            var formData = new FormData();
            formData.append('image', file);

            fetch('/api/upload_image', {
                method: 'POST',
                body: formData,
                credentials: 'same-origin'
            })
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    if (data.success && data.image_url) {
                        resolve(data.image_url);
                    } else {
                        reject(data.message || '图片上传失败');
                    }
                })
                .catch(function () {
                    reject('网络错误，图片上传失败');
                });
        });
    }

    // ======================== 发送消息 ========================

    function resetSendButton() {
        isSending = false;
        sendBtn.disabled = false;
        sendBtn.textContent = '发送';
    }

    function setSending(text) {
        isSending = true;
        sendBtn.disabled = true;
        sendBtn.textContent = text;
    }

    /**
     * 发送一轮消息。
     * options.retry 为 true 时不重复追加用户气泡（重试上一次失败的消息）。
     */
    function sendMessage(text, options) {
        options = options || {};

        if (isSending) {
            return;
        }

        var imageToSend = pendingImageUrl || initialImageUrl || '';

        if (pendingImageFile) {
            setSending('上传中…');

            uploadImage(pendingImageFile)
                .then(function (url) {
                    pendingImageFile = null;
                    pendingImageUrl = '';
                    previewImage.src = '';
                    imagePreviewBar.style.display = 'none';
                    doSend(text, url, options);
                })
                .catch(function (error) {
                    resetSendButton();
                    addMessage('assistant', '', '', {});
                    var notice = document.createElement('div');
                    notice.className = 'il-notice il-notice-error';
                    notice.textContent = String(error);
                    container.appendChild(notice);
                    scrollToBottom();
                });

            return;
        }

        doSend(text, imageToSend, options);
    }

    function doSend(text, imageUrl, options) {
        var trimmed = (text || '').trim();

        if (!trimmed && !imageUrl) {
            return;
        }

        var question = trimmed || '请分析这张图片';

        lastRequest = { text: trimmed, imageUrl: imageUrl };

        if (!options.retry) {
            // 只发图片时界面不显示"请分析这张图片"这句占位文字
            addMessage('user', trimmed, imageUrl);
        }

        setSending('发送中…');

        var myToken = ++streamToken;
        var bubble = addMessage('assistant', '', '', {});
        var contentEl = bubble.querySelector('.il-content');

        var stageEl = document.createElement('div');
        stageEl.className = 'il-notice il-notice-info';
        stageEl.textContent = '正在处理…';
        bubble.insertBefore(stageEl, contentEl);

        var streamedText = '';
        var plainText = '';
        var analysis = null;
        var doneReceived = false;
        var errorReceived = false;
        var renderScheduled = false;

        function clearStage() {
            if (stageEl && stageEl.parentNode) {
                stageEl.parentNode.removeChild(stageEl);
            }
            stageEl = null;
        }

        function scheduleRender() {
            if (renderScheduled) {
                return;
            }

            renderScheduled = true;

            window.requestAnimationFrame(function () {
                renderScheduled = false;

                if (myToken !== streamToken) {
                    return;
                }

                renderInto(contentEl, streamedText, {
                    plain: plainText,
                    streaming: true
                });

                var cursor = document.createElement('span');
                cursor.className = 'il-cursor';
                contentEl.appendChild(cursor);

                scrollToBottom();
            });
        }

        function appendError(message) {
            clearStage();

            var notice = document.createElement('div');
            notice.className = 'il-notice il-notice-error';
            notice.textContent = '❌ ' + message;

            var retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'il-retry';
            retry.textContent = '重试';
            retry.addEventListener('click', function () {
                retry.disabled = true;
                if (lastRequest) {
                    sendMessage(lastRequest.text, {
                        retry: true
                    });
                }
            });

            notice.appendChild(retry);
            bubble.appendChild(notice);
            scrollToBottom();
        }

        var payload = {
            image_url: imageUrl || '',
            messages: [{ role: 'user', content: question }]
        };

        if (currentConversationId) {
            payload.conversation_id = currentConversationId;
        }

        fetch('/api/chat/stream', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload)
        })
            .then(function (response) {
                if (!response.ok) {
                    return response.json()
                        .catch(function () { return {}; })
                        .then(function (data) {
                            throw new Error(data.message || ('请求失败（HTTP ' + response.status + '）'));
                        });
                }

                if (!response.body) {
                    throw new Error('当前浏览器不支持流式输出，请更换浏览器后重试');
                }

                var reader = response.body.getReader();
                var decoder = new TextDecoder('utf-8');
                var buffer = '';

                function handleEvent(obj) {
                    if (myToken !== streamToken) {
                        return;
                    }

                    if (obj.type === 'stage') {
                        if (stageEl) {
                            stageEl.textContent = obj.message || '正在处理…';
                        }
                        return;
                    }

                    if (obj.type === 'analysis') {
                        analysis = obj.analysis;
                        return;
                    }

                    if (obj.type === 'notice') {
                        var notice = document.createElement('div');
                        notice.className = 'il-notice il-notice-warn';
                        notice.textContent = '⚠️ ' + (obj.message || '');
                        bubble.appendChild(notice);
                        return;
                    }

                    if (obj.type === 'start') {
                        var hints = [];

                        if (obj.history_used) {
                            hints.push('已结合本对话上下文');
                        }

                        if (obj.memory_used) {
                            hints.push('已参考你最近的提问记录');
                        }

                        if (hints.length && stageEl) {
                            stageEl.textContent = hints.join('，') + '，正在生成讲解…';
                        }

                        return;
                    }

                    if (obj.type === 'delta') {
                        clearStage();
                        streamedText += obj.text || '';
                        scheduleRender();
                        return;
                    }

                    if (obj.type === 'done') {
                        doneReceived = true;
                        clearStage();

                        streamedText = obj.reply || streamedText;
                        plainText = obj.reply_plain || '';
                        analysis = obj.analysis || analysis;

                        renderInto(contentEl, streamedText, { plain: plainText });

                        if (analysis) {
                            bubble.appendChild(buildAnalysisPanel(analysis));
                        }

                        if (obj.partial) {
                            var partialNotice = document.createElement('div');
                            partialNotice.className = 'il-notice il-notice-warn';
                            partialNotice.textContent = '⚠️ 回答可能未完整生成，可点击「重试」重新提问。';
                            bubble.appendChild(partialNotice);
                        }

                        if (analysis && analysis.major && analysis.question_text) {
                            bubble.appendChild(buildWrongButton({
                                question: analysis.question_text,
                                answer: streamedText,
                                image_url: obj.image_url || '',
                                major: analysis.major,
                                sub: analysis.sub || [],
                                knowledge_points: analysis.knowledge_points || [],
                                error_types: analysis.error_types || [],
                                user_answer: analysis.student_work || '',
                                analysis: analysis.error_analysis || '',
                                conversation_id: obj.conversation_id || currentConversationId,
                                message_id: obj.message_id || null
                            }));
                        }

                        if (obj.conversation_id) {
                            setActiveConversation(obj.conversation_id);
                            loadConversationList();
                        }

                        scrollToBottom();
                        return;
                    }

                    if (obj.type === 'error') {
                        errorReceived = true;
                        appendError(obj.message || 'AI 服务暂时不可用，请稍后重试');
                    }
                }

                function pump() {
                    return reader.read().then(function (chunk) {
                        if (myToken !== streamToken) {
                            reader.cancel();
                            return;
                        }

                        if (chunk.done) {
                            // 流结束但没有 done/error：保留已生成内容并提示
                            if (!doneReceived && !errorReceived && streamedText.trim()) {
                                clearStage();
                                renderInto(contentEl, streamedText, { plain: plainText });
                                appendError('回答传输中断，内容可能不完整');
                            } else if (!doneReceived && !errorReceived) {
                                appendError('未收到 AI 回复，请重试');
                            }

                            return;
                        }

                        buffer += decoder.decode(chunk.value, { stream: true });

                        var newlineIndex;

                        while ((newlineIndex = buffer.indexOf('\n')) !== -1) {
                            var line = buffer.slice(0, newlineIndex).trim();
                            buffer = buffer.slice(newlineIndex + 1);

                            if (line.indexOf('data:') !== 0) {
                                continue;
                            }

                            var dataText = line.slice(5).trim();

                            if (!dataText) {
                                continue;
                            }

                            try {
                                handleEvent(JSON.parse(dataText));
                            } catch (error) {
                                console.error('解析流式数据失败:', error, dataText);
                            }
                        }

                        return pump();
                    });
                }

                return pump();
            })
            .catch(function (error) {
                if (myToken !== streamToken) {
                    return;
                }

                errorReceived = true;
                appendError(error.message || '网络错误，请稍后重试');
            })
            .then(function () {
                if (myToken === streamToken) {
                    resetSendButton();
                }
            });
    }

    // ======================== 初始化 ========================

    function init() {
        if (!R) {
            console.error('render.js 未加载，公式与 Markdown 将降级为纯文本');
        }

        // KaTeX 未加载成功时给出明确提示（不静默失败）
        if (R && !R.hasKatex()) {
            var warning = document.getElementById('mathLibWarning');
            if (warning) {
                warning.classList.add('show');
                warning.textContent =
                    '数学公式渲染库未能加载（可能是网络受限），已自动切换为纯文本公式显示。';
            }
        }

        loadConversationList();

        if (currentConversationId) {
            loadConversationDetail(currentConversationId);
        } else if (initialImageUrl) {
            setTimeout(function () {
                sendMessage('请分析这张图片');
            }, 200);
        } else {
            addSystemHint(
                '欢迎使用 AI 答疑。可以输入题目文字，或上传题目/作答照片；'
                + '如果照片里有你的解题过程，我会一并分析对错与错因。'
            );
        }

        document.getElementById('newChatBtn')
            .addEventListener('click', startNewChat);

        sendBtn.addEventListener('click', function () {
            var text = input.value;

            if (!text.trim() && !pendingImageUrl && !pendingImageFile && !initialImageUrl) {
                showToast('请输入问题或选择图片');
                return;
            }

            input.value = '';
            sendMessage(text);
        });

        input.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.isComposing) {
                event.preventDefault();
                sendBtn.click();
            }
        });

        if (searchInput) {
            searchInput.addEventListener('input', function () {
                renderConversationList(conversations);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
