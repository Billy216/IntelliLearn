// ===== 头像上传功能 =====
document.getElementById('change-avatar-button')?.addEventListener('click', function () {
    document.getElementById('avatar-input').click();
});

// 点击头像也可触发上传
document.querySelector('.avatar-wrapper')?.addEventListener('click', function () {
    document.getElementById('avatar-input').click();
});

document.getElementById('avatar-input')?.addEventListener('change', function (event) {
    const file = event.target.files[0];
    if (!file) return;
    
    // 验证文件类型
    const validTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
    if (!validTypes.includes(file.type)) {
        showToast('请上传 JPG、PNG、GIF 或 WEBP 格式的图片');
        this.value = '';
        return;
    }
    
    // 验证文件大小（限制 5MB）
    if (file.size > 5 * 1024 * 1024) {
        showToast('图片大小不能超过 5MB');
        this.value = '';
        return;
    }
    
    const formData = new FormData();
    formData.append('avatar', file);

    // 显示加载状态
    const avatarImg = document.getElementById('user-avatar');
    const originalSrc = avatarImg.src;
    avatarImg.style.opacity = '0.5';

    fetch('/upload_avatar', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        avatarImg.style.opacity = '1';
        if (data.success) {
            // 添加时间戳防止缓存
            avatarImg.src = data.avatar_path + '?t=' + new Date().getTime();
            showToast('✅ 头像更新成功');
        } else {
            showToast('❌ ' + (data.message || '上传失败，请重试'));
        }
    })
    .catch(error => {
        avatarImg.style.opacity = '1';
        console.error('Error:', error);
        showToast('❌ 网络错误，请检查连接');
    });
});

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

// ===== 页面初始化 =====
document.addEventListener('DOMContentLoaded', function() {
    // 可以在这里添加页面初始化逻辑
    console.log('个人页面已加载');
    
    // 示例：如果有用户信息，可以在这里更新
    // 例如：从 localStorage 或 sessionStorage 读取用户信息
});