(function() {
    const urlParams = new URLSearchParams(window.location.search);
    const imageUrl = urlParams.get('img') || '';
    const convId = urlParams.get('conv') || null;

    let messages = [];
    let currentConversationId = convId ? parseInt(convId) : null; // 当前对话ID

    const container = document.getElementById('messagesContainer');
    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    const conversationListEl = document.getElementById('conversationList');

    // ======================== 本地默认数据（接口未就绪时兜底） ========================
    const FALLBACK_CONVERSATIONS = [
        { id: 1, title: '数学问题咨询', preview: '关于微积分的疑问...', updated_at: '2026-08-10 14:32' },
        { id: 2, title: '物理作业讨论', preview: '牛顿第二定律应用', updated_at: '2026-08-09 10:15' },
        { id: 3, title: '代码调试帮助', preview: 'Python 报错排查', updated_at: '2026-08-08 22:01' },
        { id: 4, title: '英语作文润色', preview: '学术写作建议', updated_at: '2026-08-07 09:43' }
    ];

    // ======================== 工具函数 ========================
    function addMessage(role, content, imgUrl = '') {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;
        if (role === 'user' && imgUrl) {
            const img = document.createElement('img');
            img.src = imgUrl;
            img.className = 'image-preview';
            img.alt = '上传图片';
            msgDiv.appendChild(img);
            if (content) {
                const textNode = document.createElement('div');
                textNode.textContent = content;
                msgDiv.appendChild(textNode);
            }
        } else {
            msgDiv.textContent = content;
        }
        container.appendChild(msgDiv);
        container.scrollTop = container.scrollHeight;
    }

    function showToast(msg) {
        // 简单提示，可自行替换为好看的 toast
        alert(msg);
    }

    // ======================== 接口1：获取对话列表（侧边栏渲染） ========================
    function loadConversationList() {
        fetch('/api/conversations', {
            method: 'GET',
            credentials: 'same-origin' // 携带 session cookie
        })
        .then(res => {
            if (!res.ok) throw new Error('接口未就绪');
            return res.json();
        })
        .then(data => {
            if (data.success && data.data && data.data.length > 0) {
                renderConversationList(data.data);
            } else {
                // 后端返回空列表，使用兜底数据
                renderConversationList(FALLBACK_CONVERSATIONS);
            }
        })
        .catch(() => {
            // 接口报错（如404），使用兜底数据
            renderConversationList(FALLBACK_CONVERSATIONS);
        });
    }

    function renderConversationList(convs) {
        conversationListEl.innerHTML = '';
        convs.forEach(conv => {
            const div = document.createElement('div');
            div.className = 'chat-sidebar-item conversation';
            div.dataset.id = conv.id;
            // 高亮当前选中的对话
            if (currentConversationId === conv.id) {
                div.classList.add('active');
            }
            div.innerHTML = `
                <span class="conv-title">${conv.title}</span>
                <span class="conv-preview">${conv.preview || ''}</span>
            `;
            // 绑定点击事件（加载历史消息）
            div.addEventListener('click', function() {
                loadConversationDetail(conv.id);
            });
            conversationListEl.appendChild(div);
        });
    }

    // ======================== 接口2：加载指定对话的历史消息 ========================
    function loadConversationDetail(id) {
        // 高亮切换
        document.querySelectorAll('.conversation').forEach(el => el.classList.remove('active'));
        const target = document.querySelector(`.conversation[data-id="${id}"]`);
        if (target) target.classList.add('active');

        currentConversationId = id;
        // 更新 URL 参数（便于刷新保留状态）
        if (window.history && window.history.pushState) {
            const params = new URLSearchParams();
            if (imageUrl) params.set('img', imageUrl);
            params.set('conv', id);
            window.history.pushState({}, '', window.location.pathname + '?' + params.toString());
        }

        // 清空当前消息区
        container.innerHTML = '';
        messages = [];

        // 请求后端获取历史
        fetch(`/api/conversations/${id}`, {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(res => {
            if (!res.ok) throw new Error('接口未就绪');
            return res.json();
        })
        .then(data => {
            if (data.success && data.data && data.data.messages) {
                const history = data.data.messages;
                if (history.length === 0) {
                    addMessage('assistant', '该对话暂无消息，开始提问吧！');
                } else {
                    history.forEach(msg => {
                        addMessage(msg.role, msg.content);
                        messages.push(msg); // 同步本地上下文
                    });
                }
            } else {
                // 接口返回空或格式不对，用演示数据占位
                addMessage('assistant', `已加载对话 ID ${id}（演示数据，请后端实现接口后替换）`);
                // 给两条模拟消息方便预览
                addMessage('user', '你好，请问这道题怎么解？');
                addMessage('assistant', '请把题目发给我看看～');
            }
        })
        .catch(() => {
            // 接口未实现，用模拟数据
            addMessage('assistant', `已加载对话 ID ${id}（接口未实现，当前为本地演示数据）`);
            addMessage('user', '示例问题：什么是人工智能？');
            addMessage('assistant', '人工智能是研究、开发用于模拟、延伸和扩展人类智能的理论...');
        });
    }

    // ======================== 接口3：发送消息（核心） ========================
    function sendMessage(text) {
        if (!text.trim() && !imageUrl) return;
        const userMsg = text.trim() || '请分析这张图片';
        messages.push({ role: 'user', content: userMsg });
        addMessage('user', userMsg, imageUrl);

        sendBtn.disabled = true;
        sendBtn.textContent = '发送中...';

        // 组装请求体，附带当前对话ID（若存在）
        const payload = {
            image_url: imageUrl || '',
            messages: messages
        };
        if (currentConversationId) {
            payload.conversation_id = currentConversationId;
        }

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify(payload)
        })
        .then(res => res.json())
        .then(data => {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送';
            if (data.success && data.reply) {
                // 如果后端返回了新的 conversation_id，更新本地
                if (data.conversation_id) {
                    currentConversationId = data.conversation_id;
                    // 同时刷新侧边栏列表（新对话会出现）
                    loadConversationList();
                }
                messages.push({ role: 'assistant', content: data.reply });
                addMessage('assistant', data.reply);
            } else {
                addMessage('assistant', data.message || '抱歉，我没有收到有效回复。');
            }
        })
        .catch(err => {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送';
            addMessage('assistant', '网络错误，请稍后重试。');
            console.error(err);
        });
    }

    // ======================== 开启新对话 ========================
    function startNewChat() {
        messages = [];
        container.innerHTML = '';
        currentConversationId = null;
        // 清除高亮
        document.querySelectorAll('.conversation').forEach(el => el.classList.remove('active'));
        // 清除 URL 中的 conv 参数
        if (window.history && window.history.pushState) {
            const params = new URLSearchParams();
            if (imageUrl) params.set('img', imageUrl);
            window.history.pushState({}, '', window.location.pathname + (params.toString() ? '?' + params.toString() : ''));
        }
        addMessage('assistant', '✨ 新对话已开启，请问有什么可以帮您？');
    }

    // ======================== 初始化 ========================
    function init() {
        // 1. 加载对话列表
        loadConversationList();

        // 2. 根据 URL 参数决定初始内容
        if (currentConversationId) {
            // 有 conv 参数，加载指定对话
            loadConversationDetail(currentConversationId);
        } else if (imageUrl) {
            // 有图片，自动分析
            addMessage('assistant', '📷 收到图片，正在分析...');
            setTimeout(() => {
                sendMessage('请分析这张图片');
            }, 300);
        } else {
            // 默认欢迎
            addMessage('assistant', '👋 欢迎来到对话！您可以上传图片或输入问题。');
        }

        // 3. 绑定事件
        document.getElementById('newChatBtn').addEventListener('click', startNewChat);

        document.getElementById('backHomeBtn').addEventListener('click', function() {
            window.location.href = '/home';
        });

        sendBtn.addEventListener('click', function() {
            const text = input.value.trim();
            if (text) {
                sendMessage(text);
                input.value = '';
            }
        });

        input.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendBtn.click();
            }
        });
    }

    // 页面加载完成后初始化
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();