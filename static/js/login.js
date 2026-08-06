(function() {
    'use strict';

    // ========== DOM 引用 ==========
    const form = document.getElementById('loginForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('password');
    const submitBtn = document.getElementById('loginBtn');
    const toast = document.getElementById('toast');

    // 密码切换
    const togglePwd = document.getElementById('togglePwd');
    if (togglePwd && passwordInput) {
        togglePwd.addEventListener('click', function(e) {
            e.preventDefault();
            const isPassword = passwordInput.type === 'password';
            passwordInput.type = isPassword ? 'text' : 'password';
            const iconHidden = this.querySelector('.icon-hidden');
            const iconVisible = this.querySelector('.icon-visible');
            if (isPassword) {
                iconHidden.style.display = 'none';
                iconVisible.style.display = 'block';
            } else {
                iconHidden.style.display = 'block';
                iconVisible.style.display = 'none';
            }
        });
    }

    // ========== Toast 轻提示 ==========
    let toastTimer = null;
    function showToast(msg) {
        toast.textContent = msg;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }

    // ========== 表单提交 ==========
    form.addEventListener('submit', function(e) {
        e.preventDefault();

        // 收集表单数据
        const data = {
            username: usernameInput.value.trim(),
            password: passwordInput.value
        };

        // 禁用按钮，防止重复提交
        submitBtn.disabled = true;
        submitBtn.textContent = '登录中...';

        // 发送 POST 请求到后端登录 API
        fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                // 登录成功
                showToast(`🎉 ${result.message}`);
                // 延迟 1 秒后跳转到主页
                setTimeout(() => {
                    window.location.href = '/home';  // 跳转到主页
                }, 1000);
            } else {
                // 登录失败（用户名或密码错误）
                showToast(`❌ ${result.message}`);
                submitBtn.disabled = false;
                submitBtn.textContent = '登录';
            }
        })
        .catch(error => {
            // 网络错误
            showToast('❌ 网络异常，请稍后重试');
            submitBtn.disabled = false;
            submitBtn.textContent = '登录';
        });
    });

})();