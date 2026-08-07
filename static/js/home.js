// 获取元素
const photo = document.getElementById('photoPreview');
const fileInput = document.getElementById('image');
const previewImg = document.getElementById('previewImage');
const placeholder = document.getElementById('placeholderText');
const uploadBtn = document.getElementById('uploadBtn');
const result = document.getElementById('result');

// 当前选中的文件
let selectedFile = null;

// ===== 1. 点击 photo 区域 → 触发文件选择 =====
photo.addEventListener('click', function() {
    fileInput.click();  // 弹出文件选择窗口
});

// ===== 2. 文件选择变化时 =====
fileInput.addEventListener('change', function(e) {
    const file = this.files[0];
    if (!file) {
        // 用户取消选择，清空状态
        selectedFile = null;
        previewImg.style.display = 'none';
        placeholder.style.display = 'block';
        result.textContent = '';
        return;
    }

    // 校验类型
    if (!file.type.startsWith('image/')) {
        result.textContent = '❌ 请选择图片文件（jpg / png 等）';
        result.style.color = '#f64f59';
        this.value = '';      // 清空 input
        selectedFile = null;
        return;
    }

    // 校验大小（5MB 限制）
    const MAX_SIZE = 5 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
        result.textContent = '❌ 图片大小不能超过 5MB';
        result.style.color = '#f64f59';
        this.value = '';
        selectedFile = null;
        return;
    }

    // 保存文件
    selectedFile = file;

    // 预览图片
    const reader = new FileReader();
    reader.onload = function(ev) {
        previewImg.src = ev.target.result;
        previewImg.style.display = 'block';
        placeholder.style.display = 'none';
        // 显示文件名
        result.textContent = `📎 已选择：${file.name}`;
        result.style.color = '#4CAF50';
    };
    reader.readAsDataURL(file);
});

// ===== 3. 点击“上传图片”按钮 → 发送到后端 =====
uploadBtn.addEventListener('click', function() {
    if (!selectedFile) {
        result.textContent = '⚠️ 请先选择一张图片';
        result.style.color = '#f64f59';
        return;
    }

    // 准备 FormData
    const formData = new FormData();
    formData.append('image', selectedFile);

    // 显示上传中
    result.textContent = '⏳ 上传中...';
    result.style.color = '#f64f59';
    uploadBtn.disabled = true;

    // 发送到后端（接口地址已修改为 /api/upload_image）
    fetch('/api/upload_image', {
        method: 'POST',
        body: formData
        // 注意：不要手动设置 Content-Type，浏览器会自动添加 boundary
    })
    .then(response => response.json())
    .then(data => {
        uploadBtn.disabled = false;
        if (data.success) {
            result.textContent = '✅ 上传成功，正在跳转...';
            result.style.color = '#4CAF50';
            // 跳转到 chat.html，并将图片 URL 作为参数
            const imageUrl = encodeURIComponent(data.image_url);
            window.location.href = `/chat?img=${imageUrl}`;
        } else {
            result.textContent = '❌ 上传失败：' + (data.message || '未知错误');
            result.style.color = '#f64f59';
        }
    })
    .catch(err => {
        uploadBtn.disabled = false;
        result.textContent = '❌ 网络错误，请稍后重试';
        result.style.color = '#f64f59';
        console.error(err);
    });
});