(function() {
    'use strict';

    // ========== DOM 引用 ==========
    const form = document.getElementById('changeForm');
    const usernameInput = document.getElementById('username');
    const passwordInput = document.getElementById('new_password');
    const confirmInput = document.getElementById('confirm_password');
    const submitBtn = document.getElementById('submitBtn');
    const matchHint = document.getElementById('matchHint');
    const strengthFill = document.getElementById('strengthFill');
    const strengthLabel = document.getElementById('strengthLabel');
    const toast = document.getElementById('toast');

    const togglePwd = document.getElementById('togglePwd');
    const toggleConfirmPwd = document.getElementById('toggleConfirmPwd');

    // ========== SVG 图标定义（与注册页一致） ==========
    const ICON_RED_CIRCLE = `<svg viewBox="0 0 1024 1024" width="20" height="20"><path d="M512 85.333333C276.48 85.333333 85.333333 276.48 85.333333 512s191.146667 426.666667 426.666667 426.666667 426.666667-191.146667 426.666667-426.666667S747.52 85.333333 512 85.333333z m0 768c-188.586667 0-341.333333-152.746667-341.333333-341.333333s152.746667-341.333333 341.333333-341.333333 341.333333 152.746667 341.333333 341.333333-152.746667 341.333333-341.333333 341.333333z" fill="#dc2626"/></svg>`;
    const ICON_GREEN_CHECK = `<svg viewBox="0 0 1024 1024" width="20" height="20"><path d="M366.36444445 714.43342222L163.93102222 512l-68.93416334 68.44871111L366.36444445 851.81629667 948.90666667 269.27407445l-68.44871112-68.44871111L366.36444445 714.43342222z" fill="#10b981"/></svg>`;
    const ICON_RED_CROSS = `<svg viewBox="0 0 1024 1024" width="20" height="20"><path d="M768.952 847.2L515.159 593.306 261.365 847.2l-84.564-84.564 253.793-253.794L176.7 254.847l84.564-84.564 253.794 253.793L768.85 170.283l84.564 84.564-253.692 253.894 253.793 253.794z" fill="#dc2626"/></svg>`;

    // ========== 密码要求配置 ==========
    const REQUIREMENTS = [
        { key: 'length', regex: /.{8,}/, text: '至少 8 个字符' },
        { key: 'lowercase', regex: /[a-z]/, text: '包含小写字母 (a–z)' },
        { key: 'uppercase', regex: /[A-Z]/, text: '包含大写字母 (A–Z)' },
        { key: 'digit', regex: /\d/, text: '包含数字 (0–9)' },
        { key: 'special', regex: /[!@#$%^&*()\-_=+{}[\]|;:'",.<>?/`~]/, text: '包含特殊字符 (!@#$%^&* 等)' }
    ];

    // 获取每个 requirement 的 DOM 元素
    const reqElements = {};
    document.querySelectorAll('.requirement-item').forEach(el => {
        const key = el.dataset.req;
        if (key) reqElements[key] = el;
    });

    // ========== 更新单个要求状态 ==========
    function updateRequirement(key, met) {
        const el = reqElements[key];
        if (!el) return;
        const icon = el.querySelector('.req-icon');
        if (met) {
            el.classList.add('met');
            el.classList.remove('fail');
            icon.innerHTML = ICON_GREEN_CHECK;
        } else {
            el.classList.remove('met');
            el.classList.add('fail');
            icon.innerHTML = ICON_RED_CIRCLE;
        }
    }

    // ========== 计算密码强度 (0-100) ==========
    function calcStrength(pwd) {
        if (!pwd) return 0;
        let score = 0;
        if (pwd.length >= 8) score += 20;
        if (pwd.length >= 12) score += 10;
        if (/[a-z]/.test(pwd)) score += 15;
        if (/[A-Z]/.test(pwd)) score += 15;
        if (/\d/.test(pwd)) score += 15;
        if (/[!@#$%^&*()\-_=+{}[\]|;:'",.<>?/`~]/.test(pwd)) score += 15;
        if (pwd.length >= 14) score += 10;
        const types = [
            /[a-z]/.test(pwd),
            /[A-Z]/.test(pwd),
            /\d/.test(pwd),
            /[!@#$%^&*()\-_=+{}[\]|;:'",.<>?/`~]/.test(pwd)
        ].filter(Boolean).length;
        if (types >= 3) score += 5;
        if (types >= 4) score += 5;
        return Math.min(100, score);
    }

    // ========== 更新密码检测 UI ==========
    function updatePasswordChecks(pwd) {
        let allMet = true;
        REQUIREMENTS.forEach(({ key, regex }) => {
            const met = regex.test(pwd);
            updateRequirement(key, met);
            if (!met) allMet = false;
        });

        const strength = calcStrength(pwd);
        strengthFill.style.width = strength + '%';
        if (strength < 30) {
            strengthFill.style.background = '#ef4444';
            strengthLabel.textContent = '弱';
        } else if (strength < 55) {
            strengthFill.style.background = '#f59e0b';
            strengthLabel.textContent = '一般';
        } else if (strength < 80) {
            strengthFill.style.background = '#3b82f6';
            strengthLabel.textContent = '强';
        } else {
            strengthFill.style.background = '#10b981';
            strengthLabel.textContent = '很强';
        }
        return allMet;
    }

    // ========== 更新确认密码匹配 ==========
    function updateConfirmMatch() {
        const pwd = passwordInput.value;
        const confirm = confirmInput.value;
        if (!confirm) {
            matchHint.className = 'match-hint';
            matchHint.innerHTML = `<span class="match-icon">${ICON_RED_CIRCLE}</span> 请确认两次密码一致`;
            return false;
        }
        if (pwd === confirm) {
            matchHint.className = 'match-hint match';
            matchHint.innerHTML = `<span class="match-icon">${ICON_GREEN_CHECK}</span> 密码匹配`;
            return true;
        } else {
            matchHint.className = 'match-hint mismatch';
            matchHint.innerHTML = `<span class="match-icon">${ICON_RED_CROSS}</span> 密码不匹配`;
            return false;
        }
    }

    // ========== 整体校验，控制提交按钮 ==========
    function validateAll() {
        const username = usernameInput.value.trim();
        const pwd = passwordInput.value;
        const confirm = confirmInput.value;

        // 学号校验（非空）
        const usernameValid = username.length > 0;
        // 密码要求全部满足
        const pwdValid = REQUIREMENTS.every(({ regex }) => regex.test(pwd));
        // 确认密码匹配
        const confirmValid = pwd === confirm && confirm.length > 0;

        const allValid = usernameValid && pwdValid && confirmValid;
        submitBtn.disabled = !allValid;
        return allValid;
    }

    // ========== 切换密码显示 + 切换 SVG 图标 ==========
    function togglePasswordVisibility(input, button) {
        const isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';

        const iconHidden = button.querySelector('.icon-hidden');
        const iconVisible = button.querySelector('.icon-visible');

        if (isPassword) {
            iconHidden.style.display = 'none';
            iconVisible.style.display = 'block';
        } else {
            iconHidden.style.display = 'block';
            iconVisible.style.display = 'none';
        }
    }

    // ========== 绑定切换事件 ==========
    togglePwd.addEventListener('click', function(e) {
        e.preventDefault();
        togglePasswordVisibility(passwordInput, this);
    });

    toggleConfirmPwd.addEventListener('click', function(e) {
        e.preventDefault();
        togglePasswordVisibility(confirmInput, this);
    });

    // ========== 输入事件监听 ==========
    passwordInput.addEventListener('input', function() {
        const pwd = this.value;
        updatePasswordChecks(pwd);
        updateConfirmMatch();
        validateAll();
    });

    confirmInput.addEventListener('input', function() {
        updateConfirmMatch();
        validateAll();
    });

    usernameInput.addEventListener('input', function() {
        validateAll();
    });

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

    // ========== 重置 UI（修改成功后调用） ==========
    function resetFormUI() {
        // 重置密码要求图标（全部变成红色圈）
        REQUIREMENTS.forEach(({ key }) => {
            const el = reqElements[key];
            if (el) {
                el.classList.remove('met', 'fail');
                const icon = el.querySelector('.req-icon');
                icon.innerHTML = ICON_RED_CIRCLE;
            }
        });
        strengthFill.style.width = '0%';
        strengthLabel.textContent = '密码强度';
        matchHint.className = 'match-hint';
        matchHint.innerHTML = `<span class="match-icon">${ICON_RED_CIRCLE}</span> 请确认两次密码一致`;

        // 重置密码框为密文状态，并恢复图标为“不可见”
        if (passwordInput.type === 'text') {
            passwordInput.type = 'password';
            const pBtn = togglePwd;
            pBtn.querySelector('.icon-hidden').style.display = 'block';
            pBtn.querySelector('.icon-visible').style.display = 'none';
        }
        if (confirmInput.type === 'text') {
            confirmInput.type = 'password';
            const cBtn = toggleConfirmPwd;
            cBtn.querySelector('.icon-hidden').style.display = 'block';
            cBtn.querySelector('.icon-visible').style.display = 'none';
        }

        // 重新触发校验
        usernameInput.dispatchEvent(new Event('input'));
        passwordInput.dispatchEvent(new Event('input'));
        confirmInput.dispatchEvent(new Event('input'));
    }

    // ========== 表单提交 ==========
    form.addEventListener('submit', function(e) {
        e.preventDefault();

        if (!validateAll()) {
            submitBtn.disabled = true;
            return;
        }

        const data = {
            username: usernameInput.value.trim(),
            new_password: passwordInput.value
        };

        submitBtn.disabled = true;
        submitBtn.textContent = '提交中...';

        fetch('/api/change_password', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                showToast(`✅ ${result.message}`);
                form.reset();
                resetFormUI();
                // 延迟跳转到登录页（重新登录）
                setTimeout(() => {
                    window.location.href = '/login';
                }, 1500);
            } else {
                showToast(`❌ ${result.message}`);
                submitBtn.disabled = false;
                submitBtn.textContent = '确认修改';
                validateAll();
            }
        })
        .catch(error => {
            showToast('❌ 网络异常，请稍后重试');
            submitBtn.disabled = false;
            submitBtn.textContent = '确认修改';
            validateAll();
        });
    });

    // ========== 初始化 ==========
    // 设置初始状态（所有要求显示红色圈）
    REQUIREMENTS.forEach(({ key }) => {
        const el = reqElements[key];
        if (el) {
            const icon = el.querySelector('.req-icon');
            icon.innerHTML = ICON_RED_CIRCLE;
        }
    });
    // 触发初始校验
    passwordInput.dispatchEvent(new Event('input'));
    confirmInput.dispatchEvent(new Event('input'));
    usernameInput.dispatchEvent(new Event('input'));

})();