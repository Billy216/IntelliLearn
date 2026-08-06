// ===== 密码切换可见性 =====
function togglePasswordVisibility(inputId, button) {
    const input = document.getElementById(inputId);
    if (!input) return;
    
    const type = input.getAttribute('type') === 'password' ? 'text' : 'password';
    input.setAttribute('type', type);
    
    // 更新图标
    const svg = button.querySelector('svg');
    if (type === 'text') {
        // 显示为可见状态（眼睛睁开）
        svg.innerHTML = `
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
            <line x1="1" y1="1" x2="23" y2="23"></line>
        `;
    } else {
        // 显示为隐藏状态（眼睛闭合）
        svg.innerHTML = `
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
            <circle cx="12" cy="12" r="3"></circle>
        `;
    }
}

// ===== 密码强度检测 =====
function checkPasswordStrength(password) {
    let score = 0;
    const checks = {
        length: password.length >= 8,
        case: /[a-z]/.test(password) && /[A-Z]/.test(password),
        number: /\d/.test(password),
        special: /[^a-zA-Z0-9]/.test(password)
    };
    
    // 计算分数
    if (checks.length) score++;
    if (checks.case) score++;
    if (checks.number) score++;
    if (checks.special) score++;
    
    return { score, checks };
}

// ===== 更新密码要求显示 =====
function updateRequirements(password) {
    const { score, checks } = checkPasswordStrength(password);
    
    // 更新各项要求
    const requirements = {
        'req-length': checks.length,
        'req-case': checks.case,
        'req-number': checks.number,
        'req-special': checks.special
    };
    
    Object.keys(requirements).forEach(id => {
        const element = document.getElementById(id);
        if (!element) return;
        
        const icon = element.querySelector('.req-icon');
        if (requirements[id]) {
            element.classList.add('met');
            element.classList.remove('fail');
            icon.textContent = '✓';
        } else {
            element.classList.remove('met');
            element.classList.add('fail');
            icon.textContent = '✕';
        }
    });
    
    // 更新强度条
    const fill = document.querySelector('.strength-fill');
    const label = document.querySelector('.strength-label');
    
    const percentage = (score / 4) * 100;
    const colors = ['#ef4444', '#f59e0b', '#f59e0b', '#10b981', '#10b981'];
    const texts = ['极弱', '弱', '中等', '强', '极强'];
    
    fill.style.width = percentage + '%';
    fill.style.background = colors[score];
    label.textContent = password.length > 0 ? texts[score] : '请输入密码';
}

// ===== 检查密码匹配 =====
function checkPasswordMatch() {
    const newPwd = document.getElementById('new_password');
    const confirmPwd = document.getElementById('confirm_password');
    const hint = document.getElementById('match-hint');
    
    if (!newPwd || !confirmPwd || !hint) return false;
    
    const newVal = newPwd.value;
    const confirmVal = confirmPwd.value;
    
    if (confirmVal.length === 0) {
        hint.className = 'match-hint';
        hint.textContent = '请再次输入新密码';
        return false;
    } else if (newVal === confirmVal) {
        hint.className = 'match-hint match';
        hint.textContent = '✓ 密码匹配';
        return true;
    } else {
        hint.className = 'match-hint mismatch';
        hint.textContent = '✕ 密码不匹配';
        return false;
    }
}

// ===== 验证表单 =====
function validateForm() {
    const newPwd = document.getElementById('new_password');
    const confirmPwd = document.getElementById('confirm_password');
    const submitBtn = document.getElementById('submit-btn');
    
    if (!newPwd || !confirmPwd || !submitBtn) return;
    
    const { score } = checkPasswordStrength(newPwd.value);
    const isMatch = checkPasswordMatch();
    
    // 密码强度至少中等（2分以上），且匹配
    const isValid = newPwd.value.length >= 8 && score >= 2 && isMatch;
    
    submitBtn.disabled = !isValid;
}

// ===== Toast 提示 =====
function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    
    toast.textContent = message;
    toast.classList.add('show');
    
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.classList.remove('show');
    }, duration);
}

// ===== 表单提交 =====
document.getElementById('change_form')?.addEventListener('submit', function(e) {
    e.preventDefault();
    
    const username = document.getElementById('username').value;
    const newPassword = document.getElementById('new_password').value;
    const confirmPassword = document.getElementById('confirm_password').value;
    
    // 前端验证
    if (!username || !newPassword || !confirmPassword) {
        showToast('❌ 请填写完整信息');
        return;
    }
    
    if (newPassword !== confirmPassword) {
        showToast('❌ 两次输入的密码不一致');
        return;
    }
    
    // 提交表单
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = '提交中...';
    
    fetch('/change_passwd', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            username: username,
            new_password: newPassword,
            confirm_password: confirmPassword
        })
    })
    .then(response => response.json())
    .then(data => {
        submitBtn.disabled = false;
        submitBtn.textContent = '确认修改';
        
        if (data.success) {
            showToast('✅ ' + (data.message || '密码修改成功，请重新登录'));
            setTimeout(() => {
                window.location.href = '/login';
            }, 2000);
        } else {
            showToast('❌ ' + (data.message || '修改失败，请重试'));
        }
    })
    .catch(error => {
        submitBtn.disabled = false;
        submitBtn.textContent = '确认修改';
        console.error('Error:', error);
        showToast('❌ 网络错误，请检查连接');
    });
});

// ===== 事件监听 =====
document.addEventListener('DOMContentLoaded', function() {
    const newPwd = document.getElementById('new_password');
    const confirmPwd = document.getElementById('confirm_password');
    
    // 新密码输入时更新要求
    newPwd?.addEventListener('input', function() {
        updateRequirements(this.value);
        validateForm();
    });
    
    // 确认密码输入时验证匹配
    confirmPwd?.addEventListener('input', function() {
        validateForm();
    });
    
    // 新密码获得焦点时显示要求
    newPwd?.addEventListener('focus', function() {
        const requirements = document.getElementById('password-requirements');
        if (requirements) {
            requirements.classList.remove('hidden');
        }
    });
    
    // 新密码失去焦点时，如果密码为空则隐藏要求
    newPwd?.addEventListener('blur', function() {
        const requirements = document.getElementById('password-requirements');
        if (requirements && this.value.length === 0) {
            requirements.classList.add('hidden');
        }
    });
    
    // 初始化时隐藏密码要求
    const requirements = document.getElementById('password-requirements');
    if (requirements) {
        requirements.classList.add('hidden');
    }
});

// ===== 处理模板变量（如果后端使用模板引擎） =====
// 如果有错误信息从后端传来，显示Toast
// 示例：
// {% if not_succeed %}
//     showToast('❌ {{ not_succeed }}');
// {% endif %}