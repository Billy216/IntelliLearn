(function() {
    const urlParams = new URLSearchParams(window.location.search);
    const imageUrl = urlParams.get('img') || '';

    let messages = [];
    const container = document.getElementById('messagesContainer');
    const input = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');

    // 在聊天区添加一条消息
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

    // 发送消息（含自动和手动）
    function sendMessage(text) {
        if (!text.trim() && !imageUrl) return;
        const userMsg = text.trim() || '请分析这张图片';
        messages.push({ role: 'user', content: userMsg });
        addMessage('user', userMsg, imageUrl);

        sendBtn.disabled = true;
        sendBtn.textContent = '发送中...';

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image_url: imageUrl, messages: messages })
        })
        .then(res => res.json())
        .then(data => {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送';
            if (data.reply) {
                messages.push({ role: 'assistant', content: data.reply });
                addMessage('assistant', data.reply);
            } else {
                addMessage('assistant', '抱歉，我没有收到回复。');
            }
        })
        .catch(err => {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送';
            addMessage('assistant', '网络错误，请稍后重试。');
            console.error(err);
        });
    }

    // 初始化
    function init() {
        if (imageUrl) {
            addMessage('assistant', '收到图片，正在分析...');
            setTimeout(() => {
                sendMessage('请分析这张图片');
            }, 300);
        } else {
            addMessage('assistant', '欢迎来到对话！您可以上传图片或输入问题。');
        }

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

    init();
})();